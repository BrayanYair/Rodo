"""
api.py — API HTTP del bot (aiohttp).

Recibe comandos de rodolfo-host (PC del dueño) y de cualquier cliente autorizado.
Seguridad: todos los endpoints requieren Authorization: Bearer <token>.
El endpoint /health es público (para monitoreo).

Tokens:
  - API_TOKEN en .env → token único compartido (modo local / un solo usuario)
  - Futuro: tokens por usuario en tokens.json
"""

import os
import secrets
import logging
from pathlib import Path

from aiohttp import web
from dotenv import load_dotenv

from modules.music.player import get_player
from modules.music.cog    import get_target_guild, find_voice_channel

load_dotenv()

HTTP_HOST  = os.getenv("MUSIC_BOT_HOST", "127.0.0.1")  # 127.0.0.1 = solo local
HTTP_PORT  = int(os.getenv("MUSIC_BOT_PORT", "5000") or 5000)
API_TOKEN  = os.getenv("API_TOKEN", "").strip()

logger = logging.getLogger("rodolfo.api")


# ─── Seguridad ────────────────────────────────────────────────────────────────

def _check_token() -> str:
    """Devuelve el token activo. Si no hay uno configurado, genera uno temporal."""
    global API_TOKEN
    if not API_TOKEN:
        API_TOKEN = secrets.token_urlsafe(32)
        print("=" * 60)
        print("⚠️  API_TOKEN no configurado en .env")
        print(f"   Token temporal para esta sesión: {API_TOKEN}")
        print(f"   Agrega esto a tu .env para usarlo siempre:")
        print(f"   API_TOKEN={API_TOKEN}")
        print("=" * 60)
    return API_TOKEN


@web.middleware
async def auth_middleware(request: web.Request, handler):
    """
    Valida el token en TODOS los endpoints excepto /health.
    Registra los intentos fallidos para detectar accesos no autorizados.
    """
    if request.path == "/health":
        return await handler(request)

    token    = _check_token()
    auth     = request.headers.get("Authorization", "")
    expected = f"Bearer {token}"

    if auth != expected:
        client_ip = request.remote or "desconocida"
        logger.warning(
            f"[AUTH] Acceso rechazado — IP: {client_ip} | "
            f"path: {request.path} | "
            f"token recibido: '{auth[:30]}...'" if len(auth) > 30 else
            f"[AUTH] Acceso rechazado — IP: {client_ip} | path: {request.path}"
        )
        return web.json_response(
            {"error": "unauthorized", "hint": "Falta o es incorrecto el header Authorization: Bearer <token>"},
            status=401,
        )
    return await handler(request)


# ─── Endpoints ────────────────────────────────────────────────────────────────

async def http_play(request: web.Request, bot) -> web.Response:
    data  = await request.json()
    query = data.get("query", "").strip()
    if not query:
        return web.json_response({"error": "missing query"}, status=400)

    guild = get_target_guild(bot)
    if not guild:
        return web.json_response({"error": "bot no está en ningún servidor"}, status=500)

    channel = await find_voice_channel(guild)
    if not channel:
        return web.json_response({"error": "no encontré canal de voz"}, status=400)

    player = get_player(guild.id)
    try:
        await player.connect(channel)
        tracks, started_now = await player.add(query)
        return web.json_response({
            "ok":          True,
            "added":       [t["title"] for t in tracks],
            "started_now": started_now,
            "queue_size":  len(player.queue),
        })
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def http_skip(request: web.Request, bot) -> web.Response:
    guild = get_target_guild(bot)
    if not guild:
        return web.json_response({"error": "no guild"}, status=500)
    get_player(guild.id).skip()
    return web.json_response({"ok": True})


async def http_stop(request: web.Request, bot) -> web.Response:
    guild = get_target_guild(bot)
    if not guild:
        return web.json_response({"error": "no guild"}, status=500)
    get_player(guild.id).stop()
    return web.json_response({"ok": True})


async def http_pause(request: web.Request, bot) -> web.Response:
    guild = get_target_guild(bot)
    if not guild:
        return web.json_response({"error": "no guild"}, status=500)
    ok = get_player(guild.id).pause()
    return web.json_response({"ok": ok})


async def http_resume(request: web.Request, bot) -> web.Response:
    guild = get_target_guild(bot)
    if not guild:
        return web.json_response({"error": "no guild"}, status=500)
    ok = get_player(guild.id).resume()
    return web.json_response({"ok": ok})


async def http_disconnect(request: web.Request, bot) -> web.Response:
    guild = get_target_guild(bot)
    if not guild:
        return web.json_response({"error": "no guild"}, status=500)
    await get_player(guild.id).disconnect()
    return web.json_response({"ok": True})


async def http_volume(request: web.Request, bot) -> web.Response:
    data  = await request.json()
    level = float(data.get("level", 0.7))
    guild = get_target_guild(bot)
    if not guild:
        return web.json_response({"error": "no guild"}, status=500)
    get_player(guild.id).set_volume(level)
    return web.json_response({"ok": True, "volume": level})


async def http_clear_queue(request: web.Request, bot) -> web.Response:
    guild = get_target_guild(bot)
    if not guild:
        return web.json_response({"error": "no guild"}, status=500)
    n = get_player(guild.id).clear_queue()
    return web.json_response({"ok": True, "cleared": n})


async def http_remove_last(request: web.Request, bot) -> web.Response:
    guild = get_target_guild(bot)
    if not guild:
        return web.json_response({"error": "no guild"}, status=500)
    removed = get_player(guild.id).remove_last()
    if removed is None:
        return web.json_response({"ok": False, "error": "cola vacía"})
    return web.json_response({"ok": True, "removed": removed})


async def http_say(request: web.Request, bot) -> web.Response:
    data = await request.json()
    text = (data.get("text") or "").strip()
    if not text:
        return web.json_response({"error": "missing text"}, status=400)

    guild = get_target_guild(bot)
    if not guild:
        return web.json_response({"error": "no guild"}, status=500)

    channel = await find_voice_channel(guild)
    if not channel:
        return web.json_response({"error": "no voice channel"}, status=400)

    player = get_player(guild.id)
    try:
        await player.connect(channel)
        ok = await player.say(text)
        return web.json_response({"ok": ok})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def http_status(request: web.Request, bot) -> web.Response:
    guild = get_target_guild(bot)
    if not guild:
        return web.json_response({"error": "no guild"}, status=500)
    player = get_player(guild.id)
    return web.json_response({
        "playing":  player.is_playing(),
        "paused":   player.is_paused(),
        "current":  player.current["title"] if player.current else None,
        "queue":    [t["title"] for t in player.queue],
        "volume":   player.volume,
    })


async def http_command(request: web.Request, bot) -> web.Response:
    """
    Endpoint universal — acepta texto crudo, lo parsea y ejecuta la acción.

    Body: {"text": "pon despacito", "user": "Juan"}
    Usado por rodolfo-amigo en modo API directa (sin Discord de intermediario).
    Compatible con el activador quitado — no requiere "Rodolfo" en el texto.
    """
    data      = await request.json()
    text      = (data.get("text") or "").strip()
    user_name = (data.get("user") or "Amigo").strip()  # noqa: F841  (para futuros logs)

    if not text:
        return web.json_response({"error": "missing text"}, status=400)

    from command_parser import full_parse
    parsed = full_parse(text, require_activator=False)
    action = parsed.get("action", "unknown")

    if action in ("unknown", "ignored", "greet"):
        return web.json_response({"ok": False, "action": action})

    guild = get_target_guild(bot)
    if not guild:
        return web.json_response({"error": "no guild"}, status=500)

    player = get_player(guild.id)

    # ─── Acciones que necesitan canal de voz ──────────────────────────────────
    if action in ("play_music", "queue_music"):
        query = parsed.get("query", "").strip()
        if not query:
            return web.json_response({"error": "sin query para reproducir"}, status=400)
        channel = await find_voice_channel(guild)
        if not channel:
            return web.json_response({"error": "no hay canal de voz activo"}, status=400)
        try:
            await player.connect(channel)
            tracks, started_now = await player.add(query)
            return web.json_response({
                "ok":          True,
                "action":      action,
                "added":       [t["title"] for t in tracks],
                "started_now": started_now,
                "queue_size":  len(player.queue),
            })
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    # ─── Acciones de control ──────────────────────────────────────────────────
    if action == "skip_music":
        player.skip()
        return web.json_response({"ok": True, "action": action})

    if action == "stop_music":
        player.stop()
        return web.json_response({"ok": True, "action": action})

    if action == "pause_music":
        ok = player.pause()
        return web.json_response({"ok": ok, "action": action})

    if action == "resume_music":
        ok = player.resume()
        return web.json_response({"ok": ok, "action": action})

    if action == "disconnect_music":
        await player.disconnect()
        return web.json_response({"ok": True, "action": action})

    if action == "clear_queue":
        n = player.clear_queue()
        return web.json_response({"ok": True, "action": action, "cleared": n})

    if action == "remove_last":
        removed = player.remove_last()
        if removed is None:
            return web.json_response({"ok": False, "action": action, "error": "cola vacía"})
        return web.json_response({"ok": True, "action": action, "removed": removed})

    if action == "music_status":
        return web.json_response({
            "ok":      True,
            "action":  action,
            "playing": player.is_playing(),
            "paused":  player.is_paused(),
            "current": player.current["title"] if player.current else None,
            "queue":   [t["title"] for t in player.queue],
            "volume":  player.volume,
        })

    if action == "help":
        return web.json_response({
            "ok":      True,
            "action":  action,
            "commands": [
                "pon [canción]",
                "siguiente / salta / skip",
                "pausa",
                "sigue / resume",
                "para la música / stop",
                "qué está sonando",
                "limpia la cola",
                "elimina la última",
            ],
        })

    return web.json_response({"ok": False, "action": action, "error": "acción no reconocida"})


async def http_health(request: web.Request, bot) -> web.Response:
    """Endpoint público — para monitoreo y healthcheck."""
    return web.json_response({
        "status":  "ok",
        "guilds":  len(bot.guilds),
        "latency": round(bot.latency * 1000, 1),
    })


# ─── Arranque del servidor HTTP ───────────────────────────────────────────────

async def start_http(bot):
    """Inicia el servidor HTTP. Llama esto una sola vez desde on_ready."""

    # Crear handlers como closures que capturan 'bot'
    async def _play(r):        return await http_play(r, bot)
    async def _skip(r):        return await http_skip(r, bot)
    async def _stop(r):        return await http_stop(r, bot)
    async def _pause(r):       return await http_pause(r, bot)
    async def _resume(r):      return await http_resume(r, bot)
    async def _disconnect(r):  return await http_disconnect(r, bot)
    async def _volume(r):      return await http_volume(r, bot)
    async def _clear_queue(r): return await http_clear_queue(r, bot)
    async def _remove_last(r): return await http_remove_last(r, bot)
    async def _say(r):         return await http_say(r, bot)
    async def _status(r):      return await http_status(r, bot)
    async def _command(r):     return await http_command(r, bot)
    async def _health(r):      return await http_health(r, bot)

    app = web.Application(middlewares=[auth_middleware])
    app.router.add_post("/play",        _play)
    app.router.add_post("/skip",        _skip)
    app.router.add_post("/stop",        _stop)
    app.router.add_post("/pause",       _pause)
    app.router.add_post("/resume",      _resume)
    app.router.add_post("/disconnect",  _disconnect)
    app.router.add_post("/volume",      _volume)
    app.router.add_post("/clear_queue", _clear_queue)
    app.router.add_post("/remove_last", _remove_last)
    app.router.add_post("/say",         _say)
    app.router.add_post("/command",     _command)   # ← modo API directa (amigos)
    app.router.add_get( "/status",      _status)
    app.router.add_get( "/health",      _health)   # público, sin auth

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, HTTP_HOST, HTTP_PORT)
    await site.start()

    token  = _check_token()
    local  = HTTP_HOST in ("127.0.0.1", "localhost")
    scope  = "solo local" if local else "⚠️  PÚBLICO — expuesto a internet"
    print(f"[HTTP] API en {HTTP_HOST}:{HTTP_PORT} ({scope})")
    print(f"[HTTP] Auth: Bearer {token[:8]}...{token[-4:]}")
    if not local:
        print(f"[HTTP] ADVERTENCIA: si vas a exponer esto, usa nginx + SSL")
