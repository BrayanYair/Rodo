"""Universal /command handler and local playback resolver."""

import asyncio
import difflib
import logging

from aiohttp import web

from command_parser import full_parse
from modules.music.cog import get_target_guild, find_voice_channel
from modules.music.player import get_player
from .context import find_member_voice_channel
from .spotify import get_valid_user_spotify_token

logger = logging.getLogger("rodolfo.api.command")


def _ordered_guilds(bot):
    target = get_target_guild(bot)
    return [target] + [g for g in bot.guilds if g != target] if target else list(bot.guilds)


async def _find_best_voice_channel(bot, discord_id: str = ""):
    """Prefer the authenticated user's voice channel, then legacy discovery."""
    guild, channel, _member = find_member_voice_channel(bot, discord_id)
    if guild and channel:
        return guild, channel
    for guild in _ordered_guilds(bot):
        channel = await find_voice_channel(guild)
        if channel:
            return guild, channel
    return None, None


def _name_score(query: str, name: str) -> float:
    n = name.lower()
    q = query.lower()
    if n == q:
        return 4.0
    if q in n:
        return 2.0 + difflib.SequenceMatcher(None, q, n).ratio()
    if n.startswith(q):
        return 1.5 + difflib.SequenceMatcher(None, q, n).ratio()
    if n in q:
        return 1.0 + difflib.SequenceMatcher(None, q, n).ratio()
    return difflib.SequenceMatcher(None, q, n).ratio()


async def _resolve_personal_uri(query: str, spotify_type: str | None, user_key: str):
    """Search private playlists/albums for a user and return a Spotify URI result."""
    if spotify_type not in (None, "playlist", "album"):
        return None
    token = await get_valid_user_spotify_token(user_key)
    if not token:
        return None

    try:
        import spotipy
        user_sp = spotipy.Spotify(auth=token)
        candidates = []

        playlists = user_sp.current_user_playlists(limit=50)
        for playlist in playlists.get("items") or []:
            if playlist:
                candidates.append((
                    _name_score(query, playlist["name"]),
                    playlist["uri"],
                    playlist["name"],
                    "playlist",
                ))

        if spotify_type in (None, "album"):
            albums = user_sp.current_user_saved_albums(limit=50)
            for item in albums.get("items") or []:
                album = (item or {}).get("album", {})
                if album:
                    artist = album["artists"][0]["name"] if album.get("artists") else ""
                    title = f"{album['name']} - {artist}" if artist else album["name"]
                    candidates.append((
                        _name_score(query, album["name"]),
                        album["uri"],
                        title,
                        "album",
                    ))
    except Exception as e:
        print(f"[LOCAL] Error biblioteca personal: {e}")
        return None

    if not candidates:
        return None
    best = max(candidates, key=lambda c: c[0])
    if best[0] < 0.5:
        return None
    print(f"[LOCAL] Biblioteca personal ({user_key}): '{query}' -> '{best[2]}' score={best[0]:.2f}")
    return {
        "ok": True,
        "local": True,
        "mode": "spotify",
        "title": best[2],
        "spotify_uri": best[1],
        "content_type": best[3],
    }


async def _resolve_public_local(query: str, spotify_type: str | None):
    """Resolve a local playback request to a Spotify URI or YouTube URL."""
    import time
    ts = time.time()
    from modules.music.search import sp

    spotify_uri = None
    spotify_title = None
    stype = spotify_type

    if sp:
        try:
            if stype in ("album", "playlist"):
                result = sp.search(query, limit=5, type="album,playlist")
                candidates = []
                for obj in (result.get("albums", {}).get("items", []) or []):
                    if obj:
                        subtitle = obj["artists"][0]["name"] if obj.get("artists") else ""
                        candidates.append((obj["name"], obj["uri"], subtitle))
                for obj in (result.get("playlists", {}).get("items", []) or []):
                    if obj:
                        candidates.append((obj["name"], obj["uri"], ""))
                if candidates:
                    best = max(candidates, key=lambda c: _name_score(query, c[0]))
                    spotify_uri = best[1]
                    spotify_title = f"{best[0]} - {best[2]}" if best[2] else best[0]
            elif stype == "artist":
                result = sp.search(query, limit=1, type="artist")
                items = result["artists"]["items"]
                if items:
                    obj = items[0]
                    spotify_uri = obj["uri"]
                    spotify_title = obj["name"]
            else:
                from modules.music.search import _parse_artist_from_query
                track_q, artist_q = _parse_artist_from_query(query)
                sp_query = f"track:{track_q} artist:{artist_q}" if artist_q else query
                result = sp.search(sp_query, limit=1, type="track")
                items = result["tracks"]["items"]
                if not items and artist_q:
                    result = sp.search(f"{track_q} {artist_q}", limit=1, type="track")
                    items = result["tracks"]["items"]
                if items:
                    track = items[0]
                    spotify_uri = track["uri"]
                    spotify_title = f"{track['name']} - {track['artists'][0]['name']}"
        except Exception as e:
            print(f"[LOCAL] Spotify search fallo: {e}")

    if spotify_uri:
        print(f"[LOCAL] Spotify '{query[:40]}' ({stype or 'track'}) -> '{spotify_title}' en {time.time()-ts:.2f}s")
        return {
            "ok": True,
            "local": True,
            "mode": "spotify",
            "title": spotify_title,
            "spotify_uri": spotify_uri,
        }

    from modules.music.search import resolve_query
    tracks = await resolve_query(query)
    if not tracks:
        return {"ok": False, "error": "no se encontro nada"}
    track = tracks[0]
    print(f"[LOCAL] YouTube '{query[:40]}' -> '{track['title'][:40]}' en {time.time()-ts:.2f}s")
    return {
        "ok": True,
        "local": True,
        "mode": "youtube",
        "title": track["title"],
        "webpage_url": track["webpage_url"],
        "duration": track.get("duration", 0),
    }


async def _handle_local_playback(query: str, spotify_type: str | None, user_key: str):
    personal = await _resolve_personal_uri(query, spotify_type, user_key)
    if personal:
        return web.json_response(personal)
    try:
        public = await _resolve_public_local(query, spotify_type)
        return web.json_response(public, status=200 if public.get("ok") else 500)
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)


async def http_command(request: web.Request, bot) -> web.Response:
    data = await request.json()
    text = (data.get("text") or "").strip()
    auth_user = request.get("auth_user")
    auth_user_key = request.get("auth_user_key")
    user_key = auth_user_key or "owner"
    user_name = auth_user or (data.get("user") or "Amigo").strip()
    discord_id = (data.get("discord_id") or "").strip()

    logger.info("[CMD] %s -> '%s'", user_name, text[:60])
    print(f"[CMD] {user_name} -> '{text[:60]}'", flush=True)

    if not text:
        return web.json_response({"error": "missing text"}, status=400)

    parsed = full_parse(text, require_activator=False)
    action = parsed.get("action", "unknown")
    print(f"[ACTION] {user_name} -> {action} query='{parsed.get('query','')}'", flush=True)

    if action in ("unknown", "ignored", "greet"):
        return web.json_response({"ok": False, "action": action})

    if action == "link_spotify":
        return web.json_response({
            "ok": True,
            "action": "link_spotify",
            "need_spotify_auth": True,
            "hint": "Llama GET /spotify_oauth_url y luego POST /spotify_user_auth.",
        })

    guild = next(
        (g for g in _ordered_guilds(bot) if any(
            any(not m.bot for m in vc.members) for vc in g.voice_channels
        )),
        get_target_guild(bot),
    )
    if not guild:
        return web.json_response({"error": "no guild"}, status=500)
    player = get_player(guild.id)

    if action in ("play_music", "queue_music"):
        query = parsed.get("query", "").strip()
        spotify_type = parsed.get("spotify_type")

        if not query and spotify_type != "saved_tracks":
            return web.json_response({"error": "sin query para reproducir"}, status=400)

        if data.get("local"):
            if spotify_type == "saved_tracks":
                token = await get_valid_user_spotify_token(user_key)
                if not token:
                    return web.json_response({
                        "ok": False,
                        "action": action,
                        "need_spotify_auth": True,
                        "error": "Primero tenes que vincular tu cuenta de Spotify.",
                    })
                # Local saved_tracks cannot map to one URI reliably; ask Spotify app
                # through public fallback would be misleading, so return auth state.
                return web.json_response({
                    "ok": False,
                    "action": action,
                    "error": "Tus canciones guardadas solo se reproducen en Discord por ahora.",
                })
            return await _handle_local_playback(query, spotify_type, user_key)

        user_token = await get_valid_user_spotify_token(user_key)
        if spotify_type == "saved_tracks" and not user_token:
            return web.json_response({
                "ok": False,
                "action": action,
                "need_spotify_auth": True,
                "error": (
                    f"Hola {user_name}. Primero tenes que vincular tu cuenta de Spotify. "
                    "Di 'Oye Rodo, vincula mi Spotify'."
                ),
            })

        guild, channel = await _find_best_voice_channel(bot, discord_id)
        if not channel or not guild:
            return web.json_response({"error": "no hay canal de voz activo en ningun servidor"}, status=400)

        player = get_player(guild.id)
        try:
            was_connected = (
                player.voice_client is not None
                and player.voice_client.is_connected()
            )
            await player.connect(channel)
            if not was_connected:
                asyncio.ensure_future(player.say(
                    f"Hola {user_name}, acabo de conectarme. "
                    "No escuche bien tu cancion, podrias repetirla?"
                ))
                return web.json_response({
                    "ok": True,
                    "action": action,
                    "added": [],
                    "note": "bot recien conectado - pide repetir",
                })

            async def _add_tracks_bg():
                try:
                    tracks, started_now = await player.add(
                        query,
                        shuffle=parsed.get("shuffle", False),
                        spotify_type=spotify_type,
                        user_token=user_token,
                        user_key=user_key,
                    )
                    if tracks:
                        title = tracks[0]["title"]
                        if spotify_type == "saved_tracks":
                            label = "guardadas" if not parsed.get("shuffle") else "guardadas en modo aleatorio"
                            asyncio.ensure_future(player.say(
                                f"Poniendo tus canciones {label}. Empezando con {title}"
                            ))
                        elif started_now:
                            asyncio.ensure_future(player.say(f"Poniendo {title}"))
                        else:
                            asyncio.ensure_future(player.say(f"Agregado a la cola: {title}"))
                except Exception as bg_e:
                    print(f"[COMMAND_BG] Error agregando musica: {bg_e}")
                    asyncio.ensure_future(player.say("No pude encontrar esa musica."))

            asyncio.create_task(_add_tracks_bg())
            return web.json_response({
                "ok": True,
                "action": action,
                "accepted": True,
                "added": [],
                "started_now": False,
                "queue_size": len(player.queue),
            })
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    if action == "skip_music":
        player.skip()
        return web.json_response({"ok": True, "action": action})
    if action == "stop_music":
        player.stop()
        return web.json_response({"ok": True, "action": action})
    if action == "pause_music":
        return web.json_response({"ok": player.pause(), "action": action})
    if action == "resume_music":
        return web.json_response({"ok": player.resume(), "action": action})
    if action == "disconnect_music":
        await player.disconnect()
        return web.json_response({"ok": True, "action": action})
    if action == "clear_queue":
        n = player.clear_queue()
        return web.json_response({"ok": True, "action": action, "cleared": n})
    if action == "remove_last":
        removed = player.remove_last()
        if removed is None:
            return web.json_response({"ok": False, "action": action, "error": "cola vacia"})
        return web.json_response({"ok": True, "action": action, "removed": removed})
    if action == "music_status":
        return web.json_response({
            "ok": True,
            "action": action,
            "playing": player.is_playing(),
            "paused": player.is_paused(),
            "current": player.current["title"] if player.current else None,
            "queue": [t["title"] for t in player.queue],
            "volume": player.volume,
        })
    if action == "help":
        return web.json_response({
            "ok": True,
            "action": action,
            "commands": [
                "pon [cancion]",
                "siguiente / salta / skip",
                "pausa",
                "sigue / resume",
                "para la musica / stop",
                "que esta sonando",
                "limpia la cola",
                "elimina la ultima",
            ],
        })

    return web.json_response({"ok": False, "action": action, "error": "accion no reconocida"})
