"""Music, TTS, status, and health HTTP handlers."""

from aiohttp import web

from modules.music.cog import get_target_guild, find_voice_channel
from modules.music.player import get_player


async def http_play(request: web.Request, bot) -> web.Response:
    data = await request.json()
    query = data.get("query", "").strip()
    if not query:
        return web.json_response({"error": "missing query"}, status=400)

    guild = get_target_guild(bot)
    if not guild:
        return web.json_response({"error": "bot no esta en ningun servidor"}, status=500)

    channel = await find_voice_channel(guild)
    if not channel:
        return web.json_response({"error": "no encontre canal de voz"}, status=400)

    player = get_player(guild.id)
    try:
        await player.connect(channel)
        tracks, started_now = await player.add(query)
        return web.json_response({
            "ok": True,
            "added": [t["title"] for t in tracks],
            "started_now": started_now,
            "queue_size": len(player.queue),
        })
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


def get_active_guild(bot):
    """Return the guild with an active player, or the configured target guild."""
    target = get_target_guild(bot)
    all_guilds = [target] + [g for g in bot.guilds if g != target] if target else list(bot.guilds)
    for guild in all_guilds:
        from modules.music.player import _players
        player = _players.get(guild.id)
        if player and player.voice_client and player.voice_client.is_connected():
            return guild
    return target


async def http_skip(request: web.Request, bot) -> web.Response:
    guild = get_active_guild(bot)
    if not guild:
        return web.json_response({"error": "no guild"}, status=500)
    get_player(guild.id).skip()
    return web.json_response({"ok": True})


async def http_stop(request: web.Request, bot) -> web.Response:
    guild = get_active_guild(bot)
    if not guild:
        return web.json_response({"error": "no guild"}, status=500)
    get_player(guild.id).stop()
    return web.json_response({"ok": True})


async def http_pause(request: web.Request, bot) -> web.Response:
    guild = get_active_guild(bot)
    if not guild:
        return web.json_response({"error": "no guild"}, status=500)
    ok = get_player(guild.id).pause()
    return web.json_response({"ok": ok})


async def http_resume(request: web.Request, bot) -> web.Response:
    guild = get_active_guild(bot)
    if not guild:
        return web.json_response({"error": "no guild"}, status=500)
    ok = get_player(guild.id).resume()
    return web.json_response({"ok": ok})


async def http_disconnect(request: web.Request, bot) -> web.Response:
    guild = get_active_guild(bot)
    if not guild:
        return web.json_response({"error": "no guild"}, status=500)
    await get_player(guild.id).disconnect()
    return web.json_response({"ok": True})


async def http_volume(request: web.Request, bot) -> web.Response:
    data = await request.json()
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
        return web.json_response({"ok": False, "error": "cola vacia"})
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
        "playing": player.is_playing(),
        "paused": player.is_paused(),
        "current": player.current["title"] if player.current else None,
        "queue": [t["title"] for t in player.queue],
        "volume": player.volume,
    })


async def http_health(request: web.Request, bot) -> web.Response:
    return web.json_response({
        "status": "ok",
        "guilds": len(bot.guilds),
        "latency": round(bot.latency * 1000, 1),
    })

