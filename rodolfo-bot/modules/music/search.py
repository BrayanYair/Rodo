"""
search.py — Búsqueda de audio en YouTube y resolución de URLs de Spotify.
Incluye logging de queries para análisis (query_log.jsonl).
"""

import os
import re
import json
import asyncio
from datetime import datetime
from pathlib import Path

import yt_dlp
from dotenv import load_dotenv

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

def _build_search_query(query: str) -> str:
    """
    URLs directas → sin cambios.
    Texto → busca en YouTube Music (solo canciones, sin vlogs ni noticias).
    Fallback: si ytmsearch falla, retorna ytsearch5 para el reintento.
    """
    if _URL_RE.match(query):
        return query                      # URL de YouTube / Spotify / etc.
    return f"ytmsearch5:{query}"          # YouTube Music — solo música

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
async def yt_search(query: str, log: bool = True) -> dict:
    """
    Busca en YouTube Music (texto) o resuelve una URL directa.
    Itera los resultados para saltar videos no disponibles.
    Fallback a ytsearch si ytmsearch no da resultados.
    """
    search_query = _build_search_query(query)

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

    try:
        info = await loop.run_in_executor(None, _extract, search_query)
    except Exception:
        # Si YouTube Music falla, reintenta con YouTube normal
        fallback = f"ytsearch5:{query}" if not _URL_RE.match(query) else query
        print(f"[SEARCH] ytmsearch falló, reintentando con ytsearch: {query[:40]}")
        info = await loop.run_in_executor(None, _extract, fallback)

    track = {
        "url":         info["url"],
        "title":       info.get("title", "Unknown"),
        "webpage_url": info.get("webpage_url", ""),
        "duration":    info.get("duration", 0),
    }
    if log:
        _log_query(query, track["title"], track["webpage_url"])
    return track


async def resolve_query(query: str) -> list:
    """Devuelve lista de tracks. Las URLs de Spotify pueden expandirse a varias canciones."""
    if sp:
        m = SPOTIFY_URL_RE.search(query)
        if m:
            kind, sid = m.group(1), m.group(2)
            try:
                if kind == "track":
                    t = sp.track(sid)
                    q = f"{t['name']} {t['artists'][0]['name']}"
                    track = await yt_search(q, log=False)
                    _log_query(q, track["title"], track["webpage_url"], source="spotify")
                    return [track]
                elif kind == "playlist":
                    items = sp.playlist_tracks(sid)["items"]
                    tracks = []
                    for it in items[:30]:
                        if it.get("track"):
                            tt = it["track"]
                            q = f"{tt['name']} {tt['artists'][0]['name']}"
                            t2 = await yt_search(q, log=False)
                            _log_query(q, t2["title"], t2["webpage_url"], source="spotify")
                            tracks.append(t2)
                    return tracks
                elif kind == "album":
                    items = sp.album_tracks(sid)["items"]
                    results = []
                    for t in items[:30]:
                        q = f"{t['name']} {t['artists'][0]['name']}"
                        t2 = await yt_search(q, log=False)
                        _log_query(q, t2["title"], t2["webpage_url"], source="spotify")
                        results.append(t2)
                    return results
            except Exception as e:
                print(f"[SPOTIFY] Error resolviendo URL: {e}")
    return [await yt_search(query)]
