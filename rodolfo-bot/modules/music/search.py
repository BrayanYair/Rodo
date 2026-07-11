"""
search.py — Búsqueda de audio en YouTube y resolución de URLs de Spotify.
Incluye logging de queries para análisis (query_log.jsonl).
"""

import os
import re
import json
import time
import asyncio
from datetime import datetime
from pathlib import Path

import yt_dlp
from dotenv import load_dotenv
from .cache import (
    normalize_query,
    get_best_cached_query,
    get_cached_query,       # alias retrocompatible
    save_query,
    get_track,
    save_track,
    refresh_stream_url,
    extract_track_key,
    log_stat,
    cleanup_expired,
    SOURCE_SCORES,
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    should_trust_cache,
)

load_dotenv()

# ─── Spotify (opcional) ────────────────────────────────────────────────────────
try:
    import spotipy
    from spotipy.oauth2 import SpotifyClientCredentials
    _SPOTIFY_LIB = True
except ImportError:
    _SPOTIFY_LIB = False

SPOTIFY_CLIENT_ID     = os.getenv("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "")
SPOTIFY_URL_RE        = re.compile(r"https?://open\.spotify\.com/(track|playlist|album)/([a-zA-Z0-9]+)")

sp = None
if _SPOTIFY_LIB and SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET:
    try:
        sp = spotipy.Spotify(client_credentials_manager=SpotifyClientCredentials(
            client_id=SPOTIFY_CLIENT_ID,
            client_secret=SPOTIFY_CLIENT_SECRET,
        ))
        print("[SPOTIFY] Conectado.")
    except Exception as e:
        print(f"[SPOTIFY] No disponible: {e}")

# ─── yt-dlp ────────────────────────────────────────────────────────────────────
YTDL_OPTIONS = {
    "format":         "bestaudio/best",
    "noplaylist":     True,
    "quiet":          True,
    "no_warnings":    True,
    "source_address": "0.0.0.0",
}
ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)

_URL_RE = re.compile(r"^https?://")

# Cuántas canciones mantener listas en la cola regular durante lazy streaming
PREFETCH_AHEAD = 2

def _build_search_query(query: str, fast: bool = False) -> str:
    """
    URLs directas → sin cambios.
    fast=True  → ytsearch1 (query ya refinada por Spotify, 1 resultado basta)
    fast=False → ytsearch1 (ytmsearch no está instalado en yt-dlp — caería a
                             ytsearch5 internamente con ~7.8s de latencia;
                             ytsearch1 directo son ~2.4s)
    """
    if _URL_RE.match(query):
        return query
    # Nota: ytmsearch (YouTube Music) NO está disponible en yt-dlp estándar.
    # Usarlo hace que yt-dlp caiga a ytsearch5 como fallback interno → 7.8s.
    # ytsearch1 (YouTube normal, 1 resultado) es suficiente y tarda ~2.4s.
    return f"ytsearch1:{query}"

# ─── Query log ─────────────────────────────────────────────────────────────────
_QUERY_LOG = Path(__file__).parent.parent.parent / "query_log.jsonl"

def _log_query(query: str, result_title: str, result_url: str, source: str = "search"):
    try:
        entry = {
            "ts":     datetime.now().isoformat(timespec="seconds"),
            "query":  query,
            "result": result_title,
            "url":    result_url,
            "source": source,
        }
        with open(_QUERY_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[LOG] Error escribiendo query_log: {e}")


# ─── Búsqueda ──────────────────────────────────────────────────────────────────
async def yt_search(query: str, log: bool = True, fast: bool = False) -> dict:
    """
    Busca en YouTube Music (texto) o resuelve una URL directa.
    Itera los resultados para saltar videos no disponibles.
    Fallback a ytsearch si ytmsearch no da resultados.
    """
    search_query = _build_search_query(query, fast=fast)

    def _extract(q: str):
        info = ytdl.extract_info(q, download=False)
        if "entries" in info and info["entries"]:
            for entry in info["entries"]:
                if not entry:
                    continue
                availability = entry.get("availability", "")
                if availability in ("private", "premium_only", "subscriber_only"):
                    continue
                if entry.get("url") or entry.get("formats"):
                    return entry
            return info["entries"][0]   # fallback: primer resultado
        return info

    loop = asyncio.get_event_loop()

    def _is_music(entry: dict) -> bool:
        """Filtra resultados que claramente no son música (tutoriales, vlogs, etc.)"""
        duration = entry.get("duration") or 0
        # Descartar videos muy largos (>12 min = probablemente no es canción)
        if duration > 720:
            return False
        # Descartar videos muy cortos (<30s = snippet/ad)
        if 0 < duration < 30:
            return False
        categories = [c.lower() for c in (entry.get("categories") or [])]
        # Descartar categorías claramente no musicales
        bad_cats = {"howto & style", "education", "news & politics", "sports", "gaming", "science & technology"}
        if any(c in bad_cats for c in categories):
            return False
        return True

    try:
        info = await loop.run_in_executor(None, _extract, search_query)
    except Exception:
        # Fallback: agrega "song" para sesgar a música y reintenta con ytsearch1
        if not _URL_RE.match(query):
            fallback_q = f"{query} song"
            fallback   = f"ytsearch1:{fallback_q}"
        else:
            fallback = query
        print(f"[SEARCH] Búsqueda falló, reintentando con fallback: {query[:40]}")
        info = await loop.run_in_executor(None, _extract, fallback)

    track = {
        "url":          info["url"],
        "title":        info.get("title", "Unknown"),
        "webpage_url":  info.get("webpage_url", ""),
        "duration":     info.get("duration", 0),
        "_resolved_at": time.time(),   # timestamp para saber cuándo fue resuelto el URL
    }
    if log:
        _log_query(query, track["title"], track["webpage_url"])
    return track


def _parse_artist_from_query(query: str) -> tuple[str, str | None]:
    """
    Detecta patrones como "flaca de calamaro" o "flaca por calamaro"
    y devuelve (track_query, artist) para búsqueda más precisa en Spotify.
    """
    # Greedy .+ para tomar el ÚLTIMO separador: "ropa de bazar de kevin kaarl"
    # → track="ropa de bazar", artist="kevin kaarl"  (no "ropa" + "bazar de kevin kaarl")
    m = re.match(r"^(.+)\s+(?:de|del|por|from|y)\s+(.+)$", query, re.IGNORECASE)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return query, None


async def _spotify_refine(query: str) -> str | None:
    """
    Busca la query como texto en Spotify.
    Devuelve "Canción Artista" si encuentra match, None si falla.
    Mejora la precisión en YouTube evitando tutoriales y vlogs.
    Interpreta "X de Y" como track X + artista Y para mejor resultado.
    """
    if not sp:
        return None
    try:
        track_q, artist_q = _parse_artist_from_query(query)

        # Búsqueda con campo de artista si se detectó
        if artist_q:
            sp_query = f"track:{track_q} artist:{artist_q}"
        else:
            sp_query = query

        results = sp.search(sp_query, limit=1, type="track")
        items   = results["tracks"]["items"]

        # Si la búsqueda con campos no dio resultado, intenta sin campos
        if not items and artist_q:
            results = sp.search(f"{track_q} {artist_q}", limit=1, type="track")
            items   = results["tracks"]["items"]

        if not items:
            return None

        track  = items[0]
        name   = track["name"]
        artist = track["artists"][0]["name"]
        refined = f"{name} {artist}"
        print(f"[SPOTIFY] '{query}' → '{refined}'")
        return refined
    except Exception as e:
        print(f"[SPOTIFY] Error refinando query: {e}")
        return None


async def resolve_query(query: str, user_key: str = "owner") -> list:
    """Devuelve lista de tracks. Las URLs de Spotify pueden expandirse a varias canciones.
    Integra caché SQLite de nivel L1/L2/L3.
    """
    t_start = time.time()
    # Identificar si es URL directa de YouTube o Spotify
    is_url = bool(_URL_RE.match(query)) or bool(SPOTIFY_URL_RE.search(query))
    
    # ── L1 / L2 Cache Lookup (Solo para queries textuales) ─────────────────────
    if not is_url:
        norm_q = normalize_query(query)
        cached = get_best_cached_query(user_key, norm_q)
        if cached:
            now = int(time.time())
            final_conf    = cached.get("_final_confidence", 0.70)
            conf_is_low   = cached.get("_confidence_low", False)

            # Si stream_url válido (L1 Hit)
            if (cached.get("stream_url")
                    and cached.get("stream_expires_at")
                    and cached["stream_expires_at"] > now + 60
                    and not cached.get("stream_invalid")):

                latency = int((time.time() - t_start) * 1000)
                log_stat("CACHE_L1_HIT", query, "L1", latency)
                conf_tag = f" [conf={final_conf:.2f}{'  low' if conf_is_low else ''}]"
                print(f"[CACHE] L1 Hit '{query}' ({user_key}) → '{cached['title']}' {latency}ms{conf_tag}")
                track = {
                    "url":          cached["stream_url"],
                    "title":        cached["title"],
                    "webpage_url":  cached["webpage_url"],
                    "duration":     cached["duration"],
                    "_resolved_at": cached["last_stream_refresh"] or now,
                    "_confidence":  final_conf,
                }
                if not conf_is_low:
                    return [track]
                
                print(f"[CACHE CONF] Usando L1 low-confidence mientras se busca mejor candidato")
                # Fallthrough a búsqueda para intentar mejorar (conf_is_low=True)

            else:
                # stream_url expirado o inválido pero tenemos webpage_url (L2 Hit)
                print(f"[CACHE] L2 Hit '{query}' ({user_key}) → '{cached['title']}' (stream expirado)")
                try:
                    refreshed = await yt_search(cached["webpage_url"], log=False, fast=True)
                    expires = int(refreshed["_resolved_at"] + 4 * 3600)
                    refresh_stream_url(cached["track_key"], refreshed["url"], expires)
                    latency = int((time.time() - t_start) * 1000)
                    log_stat("CACHE_L2_HIT", query, "L2", latency)
                    refreshed["_confidence"] = final_conf
                    print(f"[CACHE] Stream refrescado '{cached['title']}' en {latency}ms [conf={final_conf:.2f}]")
                    if not conf_is_low:
                        return [refreshed]
                except Exception as e:
                    print(f"[CACHE] Error refrescando stream de '{cached['webpage_url']}': {e}. Fallback a búsqueda completa.")

    # ── Cache Miss / Búsqueda tradicional ────────────────────────────────────
    tracks = []
    if sp:
        # ── URL de Spotify ────────────────────────────────────────────────────
        m = SPOTIFY_URL_RE.search(query)
        if m:
            kind, sid = m.group(1), m.group(2)
            try:
                if kind == "track":
                    t = sp.track(sid)
                    q = f"{t['name']} {t['artists'][0]['name']}"
                    track = await yt_search(q, log=False)
                    track["_source_score"] = SOURCE_SCORES["spotify_url"]
                    _log_query(q, track["title"], track["webpage_url"], source="spotify")
                    tracks = [track]
                elif kind == "playlist":
                    items = sp.playlist_tracks(sid)["items"]
                    sem   = asyncio.Semaphore(5)

                    async def _fetch_pl(item, _sem=sem):
                        if not item.get("track"):
                            return None
                        tt = item["track"]
                        q  = f"{tt['name']} {tt['artists'][0]['name']}"
                        try:
                            async with _sem:
                                t2 = await yt_search(q, log=False)
                            t2["_source_score"] = SOURCE_SCORES["spotify_url"]
                            _log_query(q, t2["title"], t2["webpage_url"], source="spotify")
                            return t2
                        except Exception as e:
                            print(f"[SPOTIFY] Error buscando '{q}': {e}")
                            return None

                    results = await asyncio.gather(*[_fetch_pl(it) for it in items[:30]])
                    tracks = [t for t in results if t]

                elif kind == "album":
                    items = sp.album_tracks(sid)["items"]
                    sem   = asyncio.Semaphore(5)

                    async def _fetch_al(t, _sem=sem):
                        q = f"{t['name']} {t['artists'][0]['name']}"
                        try:
                            async with _sem:
                                t2 = await yt_search(q, log=False)
                            t2["_source_score"] = SOURCE_SCORES["spotify_url"]
                            _log_query(q, t2["title"], t2["webpage_url"], source="spotify")
                            return t2
                        except Exception as e:
                            print(f"[SPOTIFY] Error buscando '{q}': {e}")
                            return None

                    results = await asyncio.gather(*[_fetch_al(t) for t in items[:30]])
                    tracks = [t for t in results if t]
            except Exception as e:
                print(f"[SPOTIFY] Error resolviendo URL: {e}")

        # ── Texto libre → refinar con Spotify primero ─────────────────────────
        if not tracks and not _URL_RE.match(query):
            ts = time.time()
            refined = await _spotify_refine(query)
            print(f"[TIMING] Spotify refine: {time.time()-ts:.2f}s")
            if refined:
                ts2 = time.time()
                track = await yt_search(refined, log=False, fast=True)
                track["_source_score"] = SOURCE_SCORES["spotify_refine"]
                print(f"[TIMING] YouTube search: {time.time()-ts2:.2f}s")
                _log_query(query, track["title"], track["webpage_url"], source="spotify-refined")
                tracks = [track]

    if not tracks:
        t_yt = await yt_search(query)
        t_yt["_source_score"] = SOURCE_SCORES["fallback"]
        tracks = [t_yt]

    # Guardar en caché si fue búsqueda de texto exitosa
    if not is_url and tracks:
        try:
            track     = tracks[0]
            track_key = extract_track_key(track["webpage_url"])
            expires   = int(track["_resolved_at"] + 4 * 3600)

            # Determinar el source_score según qué fuente resolvió este track
            # _source_origin se setea más abajo en el flujo de búsqueda
            source_score = track.get("_source_score", SOURCE_SCORES["youtube_text"])

            # Guardar metadatos globales del track
            save_track(
                track_key=track_key,
                title=track["title"],
                artist=track.get("artist", ""),
                duration=track.get("duration", 0),
                webpage_url=track["webpage_url"],
                stream_url=track["url"],
                stream_expires_at=expires,
                source="youtube"
            )
            # Guardar la asociación usuario → track con source_score correcto
            save_query(user_key, norm_q, track_key, source_score=source_score)

            latency = int((time.time() - t_start) * 1000)
            log_stat("CACHE_MISS", query, "MISS", latency)
            print(f"[CACHE] Miss guardado '{query}' ({user_key}) → '{track['title']}' "
                  f"[src={source_score:.2f}] en {latency}ms")
        except Exception as e:
            print(f"[CACHE] Error al persistir en caché: {e}")

    return tracks


# ─── Lazy playlist streaming ───────────────────────────────────────────────────

async def resolve_playlist_lazy(
    url: str, shuffle: bool = False
) -> tuple[list[dict], list[str]]:
    """
    Para URLs de Spotify playlist/album: estrategia de streaming lazy.

    Devuelve (immediate_tracks, pending_queries):
      - immediate_tracks : primeras (PREFETCH_AHEAD + 1) canciones con URL de YouTube,
                           listas para empezar a reproducir de inmediato.
      - pending_queries  : resto de canciones como strings "Título Artista",
                           a resolver en background conforme se consumen.

    Si shuffle=True, la lista completa se baraja antes de tomar las primeras.
    """
    if not sp:
        return await resolve_query(url), []

    m = SPOTIFY_URL_RE.search(url)
    if not m or m.group(1) not in ("playlist", "album"):
        return await resolve_query(url), []

    kind, sid = m.group(1), m.group(2)
    try:
        if kind == "playlist":
            raw = sp.playlist_tracks(sid)["items"]
            all_queries = [
                f"{it['track']['name']} {it['track']['artists'][0]['name']}"
                for it in raw[:100] if it.get("track")
            ]
        else:
            raw = sp.album_tracks(sid)["items"]
            all_queries = [
                f"{t['name']} {t['artists'][0]['name']}"
                for t in raw[:100]
            ]
    except Exception as e:
        print(f"[SPOTIFY] Error obteniendo {kind}: {e}")
        return [], []

    if shuffle:
        import random
        random.shuffle(all_queries)

    n_immediate = PREFETCH_AHEAD + 1
    immediate_qs = all_queries[:n_immediate]
    pending_qs   = all_queries[n_immediate:]

    sem = asyncio.Semaphore(3)

    async def _fetch(q, _sem=sem):
        try:
            async with _sem:
                track = await yt_search(q, log=False, fast=True)
            _log_query(q, track["title"], track["webpage_url"], source="spotify-lazy")
            return track
        except Exception as e:
            print(f"[PREFETCH] Error en '{q}': {e}")
            return None

    results = await asyncio.gather(*[_fetch(q) for q in immediate_qs])
    return [t for t in results if t], pending_qs


# ─── Biblioteca personal del usuario (Spotify OAuth) ─────────────────────────

async def resolve_user_saved_tracks(
    user_token: str, shuffle: bool = False
) -> tuple[list[dict], list[str]]:
    """
    Obtiene las canciones guardadas del usuario de Spotify usando su token personal.
    Devuelve (immediate_tracks, pending_queries) para lazy streaming, igual que
    resolve_playlist_lazy, para que el player las maneje de la misma forma.

    Requiere scope 'user-library-read' en el token OAuth del usuario.
    """
    try:
        import aiohttp as _http
        async with _http.ClientSession() as session:
            async with session.get(
                "https://api.spotify.com/v1/me/tracks",
                headers={"Authorization": f"Bearer {user_token}"},
                params={"limit": 50},
            ) as resp:
                data = await resp.json()
                if resp.status != 200:
                    print(f"[SPOTIFY USER] Error obteniendo guardadas (HTTP {resp.status}): "
                          f"{data.get('error', {}).get('message', data)}")
                    return [], []
                items = data.get("items", [])
    except Exception as e:
        print(f"[SPOTIFY USER] Error en resolve_user_saved_tracks: {e}")
        return [], []

    all_queries = [
        f"{it['track']['name']} {it['track']['artists'][0]['name']}"
        for it in items if it.get("track")
    ]
    if not all_queries:
        return [], []

    if shuffle:
        import random
        random.shuffle(all_queries)

    n_immediate  = PREFETCH_AHEAD + 1
    immediate_qs = all_queries[:n_immediate]
    pending_qs   = all_queries[n_immediate:]

    sem = asyncio.Semaphore(3)

    async def _fetch(q, _sem=sem):
        try:
            async with _sem:
                track = await yt_search(q, log=False, fast=True)
            _log_query(q, track["title"], track["webpage_url"], source="user-saved")
            return track
        except Exception as e:
            print(f"[PREFETCH] Error en '{q}': {e}")
            return None

    results = await asyncio.gather(*[_fetch(q) for q in immediate_qs])
    return [t for t in results if t], pending_qs


# ─── Búsqueda por tipo de contenido ───────────────────────────────────────────

async def resolve_by_type(
    query: str, spotify_type: str, shuffle: bool = False
) -> tuple[list[dict], list[str]]:
    """
    Busca en Spotify por tipo ("album" | "playlist" | "artist") y devuelve
    (immediate_tracks, pending_queries) listo para el lazy streaming del player.

    Si Spotify no está disponible o no hay resultados, hace fallback a YouTube
    para que el usuario siempre escuche algo.

    Ejemplos de queries (ya normalizadas por el parser):
      "360"       + album   → álbum 360 en Spotify
      "bad bunny" + artist  → top 20 canciones de Bad Bunny
      "trap"      + playlist→ primera playlist pública de trap
    """
    if sp:
        try:
            if spotify_type == "album":
                r     = sp.search(query, limit=3, type="album")
                items = r["albums"]["items"]
                if not items:
                    raise ValueError("sin resultados")
                album  = items[0]
                print(f"[SPOTIFY] Álbum: '{album['name']}' — {album['artists'][0]['name']}")
                tracks, pending = await resolve_playlist_lazy(
                    f"https://open.spotify.com/album/{album['id']}", shuffle=shuffle
                )
                if not tracks and not pending:
                    # resolve_playlist_lazy se traga sus propios errores (ej. 401 de
                    # Spotify) y devuelve vacío en vez de tirar excepción — forzamos
                    # el fallback a YouTube de más abajo en vez de volver con nada.
                    raise ValueError(f"no se pudieron obtener canciones del álbum '{album['name']}'")
                return tracks, pending

            elif spotify_type == "playlist":
                r     = sp.search(query, limit=3, type="playlist")
                items = r["playlists"]["items"]
                if not items:
                    raise ValueError("sin resultados")
                pl = items[0]
                print(f"[SPOTIFY] Playlist: '{pl['name']}'")
                tracks, pending = await resolve_playlist_lazy(
                    f"https://open.spotify.com/playlist/{pl['id']}", shuffle=shuffle
                )
                if not tracks and not pending:
                    raise ValueError(f"no se pudieron obtener canciones de la playlist '{pl['name']}'")
                return tracks, pending

            elif spotify_type == "artist":
                r     = sp.search(query, limit=1, type="artist")
                items = r["artists"]["items"]
                if not items:
                    raise ValueError("sin resultados")
                artist = items[0]
                print(f"[SPOTIFY] Artista: '{artist['name']}'")
                # Top tracks localizadas a AR (mejor cobertura para español)
                top = sp.artist_top_tracks(artist["id"], country="AR")["tracks"]
                all_queries = [
                    f"{t['name']} {t['artists'][0]['name']}"
                    for t in top[:20]
                ]
                if shuffle:
                    import random
                    random.shuffle(all_queries)
                n_imm   = PREFETCH_AHEAD + 1
                imm_qs  = all_queries[:n_imm]
                pend_qs = all_queries[n_imm:]

                sem = asyncio.Semaphore(3)

                async def _fetch_at(q, _sem=sem):
                    try:
                        async with _sem:
                            t = await yt_search(q, log=False, fast=True)
                        _log_query(q, t["title"], t["webpage_url"], source="artist-top")
                        return t
                    except Exception as e:
                        print(f"[PREFETCH] Error en '{q}': {e}")
                        return None

                res = await asyncio.gather(*[_fetch_at(q) for q in imm_qs])
                return [t for t in res if t], pend_qs

        except Exception as e:
            print(f"[SPOTIFY] resolve_by_type({spotify_type}, '{query}') → {e}. Fallback YouTube.")

    # Fallback: sin Spotify o sin resultado → YouTube directo
    try:
        track = await yt_search(query)
        return [track], []
    except Exception as e:
        print(f"[SEARCH] Error YouTube fallback: {e}")
        return [], []
