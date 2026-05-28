"""
cache_manager.py — CRUD de la caché musical + motor de confidence.

Arquitectura de datos:
  tracks       → caché global de metadatos + stream URLs (compartida entre usuarios)
  user_queries → asociaciones usuario-específicas (1:N por query, con scoring)

Motor de confidence:
  Cada asociación (user, query) → track tiene 3 dimensiones:
    source_score   : qué tan confiable fue la fuente de resolución (0.60–1.00)
    recency_weight : cuánto tiempo tiene la asociación sin actualizarse (decae con el tiempo)
    usage_weight   : cuántas veces el usuario confirmó implícitamente la asociación
  final_confidence = source_score × recency_weight × usage_weight

Umbrales de decisión:
    >= 0.80  → Hit confiable   → usar directamente (L1/L2)
    0.50–0.79 → Hit dudoso     → usar, pero si hay búsqueda nueva reemplazar
    < 0.50   → Hit inválido   → ignorar, forzar búsqueda completa
"""

import re
import hashlib
import time
import asyncio
import collections
from .database import get_connection

# ─── Constantes de confidence ─────────────────────────────────────────────────

# source_score por fuente de resolución
SOURCE_SCORES = {
    "spotify_url":      1.00,   # URL directa de Spotify → canción exacta
    "spotify_personal": 0.95,   # Biblioteca personal del usuario → preferencia explícita
    "spotify_refine":   0.90,   # Spotify refinó el texto → muy confiable
    "youtube_text":     0.70,   # Solo YouTube + texto libre → puede ser cover/remix
    "fallback":         0.60,   # Sin Spotify, solo YouTube → mínima garantía
}

# Umbrales de decisión para final_confidence
CONFIDENCE_HIGH   = 0.80   # Hit confiable → usar sin dudar
CONFIDENCE_LOW    = 0.50   # Por debajo → ignorar, forzar búsqueda nueva


# ─── Lock por track_key ────────────────────────────────────────────────────────
# Evita doble-refresh y race conditions cuando dos coroutines quieren refrescar
# el mismo track_key simultáneamente (múltiples guilds, múltiples comandos).
_track_locks: dict[str, asyncio.Lock] = {}

def _get_track_lock(track_key: str) -> asyncio.Lock:
    """Retorna (o crea) el Lock asyncio correspondiente a este track_key."""
    if track_key not in _track_locks:
        _track_locks[track_key] = asyncio.Lock()
    return _track_locks[track_key]


# ─── Hit ratio en memoria ──────────────────────────────────────────────────────
_hit_counters: dict[str, int] = collections.Counter()

def record_hit(event_type: str):
    """Incrementa el contador en memoria para este tipo de evento."""
    _hit_counters[event_type] += 1

def get_hit_ratio_report() -> dict:
    """
    Retorna el hit ratio del período actual.

    Métricas objetivo:
      L1 hit ratio   → > 60%
      L2 hit ratio   → 20–30%
      MISS ratio     → < 20%
    """
    total = sum(_hit_counters.values())
    if total == 0:
        return {"total": 0, "message": "Sin eventos aún"}
    report = {}
    for key in ("CACHE_L1_HIT", "CACHE_L2_HIT", "STREAM_REFRESH",
                "CACHE_MISS", "PLAYBACK_FAIL_REFRESH", "CONFIDENCE_SKIP"):
        count = _hit_counters.get(key, 0)
        report[key] = {"count": count, "pct": round(count / total * 100, 1)}
    report["total"] = total
    l1_pct   = report["CACHE_L1_HIT"]["pct"]
    miss_pct = report["CACHE_MISS"]["pct"]
    skip_pct = report.get("CONFIDENCE_SKIP", {}).get("pct", 0)
    alerts = []
    if l1_pct < 30:
        alerts.append(f"L1 Hit ratio bajo ({l1_pct}%) — caché subutilizada")
    if miss_pct > 60:
        alerts.append(f"Miss ratio alto ({miss_pct}%) — muchas canciones nuevas")
    if skip_pct > 20:
        alerts.append(f"Confidence skip alto ({skip_pct}%) — muchas asociaciones poco confiables")
    if alerts:
        report["alerta"] = "⚠️  " + " | ".join(alerts)
    return report


# ─── Motor de confidence ──────────────────────────────────────────────────────

def compute_confidence(source_score: float, updated_at: int, usage_count: int) -> float:
    """
    Calcula el final_confidence de una asociación (user, query) → track.

    Fórmula: source_score × recency_weight × usage_weight

    recency_weight: decae con el tiempo desde la última vez que el usuario
    usó esta asociación. Una query que nadie pide en 90 días vale menos.

      < 7 días   → 1.00
      < 30 días  → 0.85
      < 90 días  → 0.70
      >= 90 días → 0.50

    usage_weight: sube con el uso, indicando que el usuario confirma la
    asociación implícitamente cada vez que la pide.
    No hay boost externo; el score sube solo con el uso acumulado.

      usage_count=1   → 0.52
      usage_count=10  → 0.75
      usage_count=20  → 1.00  (saturación)
      usage_count=40+ → 1.00
    """
    now = int(time.time())
    age_days = (now - updated_at) / 86400

    if age_days < 7:
        recency = 1.00
    elif age_days < 30:
        recency = 0.85
    elif age_days < 90:
        recency = 0.70
    else:
        recency = 0.50

    usage = min(1.0, 0.50 + usage_count / 40.0)

    return round(source_score * recency * usage, 4)


def should_trust_cache(confidence: float) -> bool:
    """
    True si el hit de caché es lo suficientemente confiable para usarse sin
    forzar una nueva búsqueda.
    """
    return confidence >= CONFIDENCE_LOW


# ─── Helpers ──────────────────────────────────────────────────────────────────

def extract_track_key(webpage_url: str) -> str:
    """Extrae una clave única y estable para el video, preferiblemente 'youtube:VIDEO_ID'."""
    if not webpage_url:
        return ""
    if "youtube.com" in webpage_url or "youtu.be" in webpage_url:
        match = re.search(r"(?:v=|\/|embed\/|v\/|shorts\/)([a-zA-Z0-9_-]{11})", webpage_url)
        if match:
            return f"youtube:{match.group(1)}"
    h = hashlib.md5(webpage_url.encode("utf-8")).hexdigest()[:12]
    return f"url:{h}"


# ─── Lookups ──────────────────────────────────────────────────────────────────

def get_best_cached_query(user_key: str, normalized_query: str) -> dict | None:
    """
    Busca el MEJOR candidato para esta (user, query) según final_confidence.

    Esquema 1:N: puede haber múltiples registros para (user_key, normalized_query).
    Retorna el de mayor confidence calculado en tiempo real, o None si:
      - No hay ningún candidato
      - El mejor candidato tiene confidence < CONFIDENCE_LOW (0.50)

    Si el hit es encontrado pero poco confiable (0.50–0.79), el dict incluye
    `_confidence_low=True` como señal para que resolve_query lo trate como
    "usar pero reemplazar si hay resultado nuevo".

    Siempre incrementa usage_count del candidato ganador (confirma uso implícito).
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()
        # Obtener todos los candidatos para (user, query)
        cursor.execute("""
            SELECT uq.*, t.*,
                   uq.source_score AS uq_source_score,
                   uq.usage_count  AS uq_usage_count,
                   uq.updated_at   AS uq_updated_at,
                   uq.id           AS uq_id
            FROM user_queries uq
            JOIN tracks t ON uq.track_key = t.track_key
            WHERE uq.user_key = ? AND uq.normalized_query = ?
        """, (user_key.lower(), normalized_query))
        rows = cursor.fetchall()

        if not rows:
            return None

        # Calcular confidence en tiempo real y elegir el mejor
        best_row = None
        best_conf = -1.0
        for row in rows:
            conf = compute_confidence(
                source_score=row["uq_source_score"] or 0.70,
                updated_at=row["uq_updated_at"] or int(time.time()),
                usage_count=row["uq_usage_count"] or 1,
            )
            if conf > best_conf:
                best_conf = conf
                best_row = row

        if best_row is None:
            return None

        # Si el mejor candidato no es confiable, informar a quien llama
        if not should_trust_cache(best_conf):
            print(f"[CACHE CONF] Query '{normalized_query}' tiene confidence {best_conf:.2f} < {CONFIDENCE_LOW} → ignorando")
            return None

        # Incrementar uso del candidato ganador
        now = int(time.time())
        cursor.execute("""
            UPDATE user_queries
            SET usage_count = usage_count + 1, updated_at = ?, confidence = ?
            WHERE id = ?
        """, (now, best_conf, best_row["uq_id"]))

        # Incrementar play_count del track global
        cursor.execute("""
            UPDATE tracks
            SET play_count = play_count + 1, updated_at = ?
            WHERE track_key = ?
        """, (now, best_row["track_key"]))

        conn.commit()

        result = dict(best_row)
        result["_final_confidence"] = best_conf
        result["_confidence_low"]   = best_conf < CONFIDENCE_HIGH
        return result

    except Exception as e:
        print(f"[CACHE DB] Error en get_best_cached_query: {e}")
        return None
    finally:
        conn.close()


# Alias para retrocompatibilidad con código que llame get_cached_query
get_cached_query = get_best_cached_query


def get_hot_tracks(min_usage: int = 50, limit: int = 20) -> list[dict]:
    """
    Retorna los tracks más usados globalmente (para pre-refresh proactivo).
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT t.*, MAX(uq.usage_count) as top_usage
            FROM tracks t
            JOIN user_queries uq ON t.track_key = uq.track_key
            WHERE uq.usage_count >= ?
            GROUP BY t.track_key
            ORDER BY top_usage DESC
            LIMIT ?
        """, (min_usage, limit))
        return [dict(r) for r in cursor.fetchall()]
    except Exception as e:
        print(f"[CACHE DB] Error en get_hot_tracks: {e}")
        return []
    finally:
        conn.close()


# ─── Escrituras ───────────────────────────────────────────────────────────────

def save_query(user_key: str, normalized_query: str, track_key: str,
               source_score: float = 0.70):
    """
    Guarda o actualiza la asociación (user, query) → track con confidence.

    Esquema 1:N:
      - Si ya existe un registro para (user_key, normalized_query, track_key),
        incrementa usage_count y recalcula confidence.
      - Si existe la query para otro track_key (source_score <= existente),
        no sobrescribe.
      - Si el track_key nuevo tiene source_score mayor al existente más alto,
        inserta un nuevo candidato.

    La decisión de cuál usar en runtime la toma get_best_cached_query.
    """
    conn = get_connection()
    now = int(time.time())
    try:
        cursor = conn.cursor()

        # Buscar si ya existe este par exacto (user, query, track_key)
        cursor.execute("""
            SELECT id, usage_count, source_score
            FROM user_queries
            WHERE user_key = ? AND normalized_query = ? AND track_key = ?
        """, (user_key.lower(), normalized_query, track_key))
        existing = cursor.fetchone()

        if existing:
            # Actualizar: sumar uso, actualizar source_score si mejoró, recalcular confidence
            new_usage = existing["usage_count"] + 1
            new_source = max(source_score, existing["source_score"] or 0.70)
            new_conf = compute_confidence(new_source, now, new_usage)
            cursor.execute("""
                UPDATE user_queries
                SET usage_count = ?, source_score = ?, confidence = ?, updated_at = ?
                WHERE id = ?
            """, (new_usage, new_source, new_conf, now, existing["id"]))
        else:
            # Nuevo candidato para esta query
            init_conf = compute_confidence(source_score, now, 1)
            cursor.execute("""
                INSERT INTO user_queries
                    (user_key, normalized_query, track_key, source_score,
                     usage_count, confidence, created_at, updated_at)
                VALUES (?, ?, ?, ?, 1, ?, ?, ?)
            """, (user_key.lower(), normalized_query, track_key,
                  source_score, init_conf, now, now))

        conn.commit()
    except Exception as e:
        print(f"[CACHE DB] Error en save_query: {e}")
    finally:
        conn.close()


def get_track(track_key: str) -> dict | None:
    """Retorna los datos de un track por su clave única."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM tracks WHERE track_key = ?", (track_key,))
        row = cursor.fetchone()
        return dict(row) if row else None
    except Exception as e:
        print(f"[CACHE DB] Error en get_track: {e}")
        return None
    finally:
        conn.close()


def save_track(track_key: str, title: str, artist: str, duration: int,
               webpage_url: str, stream_url: str, stream_expires_at: int,
               source: str = "youtube", thumbnail: str = None):
    """Guarda o actualiza un track en la caché global. Resetea stream_invalid al guardar URL nueva."""
    conn = get_connection()
    now = int(time.time())
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO tracks (
                track_key, title, artist, duration, webpage_url, stream_url,
                stream_expires_at, source, thumbnail, created_at, updated_at,
                last_stream_refresh, stream_invalid
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            ON CONFLICT(track_key) DO UPDATE SET
                title=excluded.title,
                artist=excluded.artist,
                duration=excluded.duration,
                webpage_url=excluded.webpage_url,
                stream_url=excluded.stream_url,
                stream_expires_at=excluded.stream_expires_at,
                updated_at=excluded.updated_at,
                last_stream_refresh=excluded.last_stream_refresh,
                stream_invalid=0
        """, (
            track_key, title, artist, duration, webpage_url, stream_url,
            stream_expires_at, source, thumbnail, now, now, now
        ))
        conn.commit()
    except Exception as e:
        print(f"[CACHE DB] Error en save_track: {e}")
    finally:
        conn.close()


def refresh_stream_url(track_key: str, stream_url: str, expires_at: int):
    """Actualiza únicamente el stream URL de un track. Resetea stream_invalid."""
    conn = get_connection()
    now = int(time.time())
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE tracks
            SET stream_url = ?, stream_expires_at = ?, last_stream_refresh = ?,
                updated_at = ?, stream_invalid = 0
            WHERE track_key = ?
        """, (stream_url, expires_at, now, now, track_key))
        conn.commit()
    except Exception as e:
        print(f"[CACHE DB] Error en refresh_stream_url: {e}")
    finally:
        conn.close()


def mark_stream_invalid(track_key: str):
    """
    Marca un track como con URL inválida aunque el TTL no haya expirado.
    Debe llamarse cuando playback falla con HTTP 403/429 o firma inválida.
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE tracks
            SET stream_invalid = 1, stream_url = NULL, updated_at = ?
            WHERE track_key = ?
        """, (int(time.time()), track_key))
        conn.commit()
        print(f"[CACHE DB] Track marcado como inválido: {track_key}")
    except Exception as e:
        print(f"[CACHE DB] Error en mark_stream_invalid: {e}")
    finally:
        conn.close()


# ─── Métricas ─────────────────────────────────────────────────────────────────

def log_stat(event_type: str, query: str, cache_level: str, latency_ms: int):
    """Registra una métrica de rendimiento en cache_stats y en contadores en memoria."""
    record_hit(event_type)
    conn = get_connection()
    now = int(time.time())
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO cache_stats (event_type, query, cache_level, latency_ms, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (event_type, query, cache_level, latency_ms, now))
        conn.commit()
    except Exception as e:
        print(f"[CACHE DB] Error guardando estadísticas: {e}")
    finally:
        conn.close()


def get_stats_summary(hours: int = 24) -> dict:
    """Retorna resumen de hits/misses de las últimas N horas + live ratio en memoria."""
    conn = get_connection()
    since = int(time.time()) - hours * 3600
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT event_type, COUNT(*) as count, AVG(latency_ms) as avg_ms
            FROM cache_stats
            WHERE created_at >= ?
            GROUP BY event_type
            ORDER BY count DESC
        """, (since,))
        rows = cursor.fetchall()
        stats = {row["event_type"]: {"count": row["count"], "avg_ms": round(row["avg_ms"] or 0)}
                 for row in rows}
        total = sum(s["count"] for s in stats.values())
        return {
            "period_hours": hours,
            "total_events": total,
            "breakdown": stats,
            "live_ratio": get_hit_ratio_report(),
        }
    except Exception as e:
        print(f"[CACHE DB] Error en get_stats_summary: {e}")
        return {}
    finally:
        conn.close()


# ─── Mantenimiento ────────────────────────────────────────────────────────────

def cleanup_expired():
    """
    Limpieza periódica:
      1. Invalida stream_urls expirados (TTL).
      2. Borra user_queries inactivas > 90 días.
      3. Elimina candidatos de baja confidence que no se usan hace > 30 días.
      4. Purga cache_stats de > 30 días.
    """
    conn = get_connection()
    now = int(time.time())
    ttl_queries   = 90 * 24 * 3600
    ttl_bad_conf  = 30 * 24 * 3600
    try:
        cursor = conn.cursor()

        # 1. Invalidar streams expirados
        r = cursor.execute("""
            UPDATE tracks
            SET stream_url = NULL, stream_expires_at = NULL
            WHERE stream_expires_at < ? AND stream_url IS NOT NULL
        """, (now,))
        expired_streams = r.rowcount

        # 2. Borrar queries inactivas > 90 días
        r = cursor.execute("""
            DELETE FROM user_queries
            WHERE updated_at < ?
        """, (now - ttl_queries,))
        deleted_old = r.rowcount

        # 3. Borrar candidatos de baja confidence inactivos > 30 días
        #    (no han sido usados en un mes y su score es < CONFIDENCE_LOW)
        r = cursor.execute("""
            DELETE FROM user_queries
            WHERE confidence < ? AND updated_at < ?
        """, (CONFIDENCE_LOW, now - ttl_bad_conf))
        deleted_low = r.rowcount

        # 4. Purgar estadísticas antiguas
        cursor.execute("""
            DELETE FROM cache_stats WHERE created_at < ?
        """, (now - 30 * 24 * 3600,))

        conn.commit()
        print(f"[CACHE DB] Limpieza: {expired_streams} streams, "
              f"{deleted_old} queries antiguas, {deleted_low} candidatos de baja conf.")
    except Exception as e:
        print(f"[CACHE DB] Error en cleanup_expired: {e}")
    finally:
        conn.close()


async def maybe_pre_refresh_hot_tracks(yt_search_fn, min_usage: int = 50, ttl_margin: int = 1800):
    """
    Pre-refresh proactivo de hot tracks (usage_count >= min_usage) cuyo
    stream_url expira en menos de ttl_margin segundos.
    """
    hot = get_hot_tracks(min_usage=min_usage)
    now = int(time.time())
    refreshed = 0
    for track_data in hot:
        expires_at   = track_data.get("stream_expires_at") or 0
        needs_refresh = (
            track_data.get("stream_invalid", 0)
            or not track_data.get("stream_url")
            or expires_at < now + ttl_margin
        )
        if not needs_refresh:
            continue

        track_key = track_data["track_key"]
        lock = _get_track_lock(track_key)
        if lock.locked():
            continue   # Ya hay un refresh en progreso

        async with lock:
            try:
                webpage_url = track_data.get("webpage_url", "")
                if not webpage_url:
                    continue
                print(f"[CACHE PRE-REFRESH] Hot track '{track_data['title'][:50]}' — refrescando")
                fresh   = await yt_search_fn(webpage_url, log=False, fast=True)
                expires = int(fresh["_resolved_at"] + 4 * 3600)
                refresh_stream_url(track_key, fresh["url"], expires)
                refreshed += 1
            except Exception as e:
                print(f"[CACHE PRE-REFRESH] Error: {e}")

    if refreshed:
        print(f"[CACHE PRE-REFRESH] {refreshed} hot tracks refrescados.")
