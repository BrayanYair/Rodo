"""Discord context, movement, and Discord OAuth handlers."""

import logging
import os

from aiohttp import web

from modules.music.cog import get_target_guild, find_member_by_name
from modules.music.player import get_player
from .music import get_active_guild

logger = logging.getLogger("rodolfo.api.context")


def find_channel_by_name(guild, name: str):
    """Find a voice channel by exact, prefix, or partial normalized name."""
    if not guild or not name:
        return None
    clean = name.lower().strip()
    for channel in guild.voice_channels:
        cname = channel.name.lower()
        if cname == clean:
            return channel
    for channel in guild.voice_channels:
        cname = channel.name.lower()
        if cname.startswith(clean) or clean in cname:
            return channel
    return None


def find_member_voice_channel(bot, discord_id: str):
    """Return (guild, channel, member) for a Discord user id currently in voice."""
    if not discord_id:
        return None, None, None
    try:
        did = int(discord_id)
    except (TypeError, ValueError):
        return None, None, None
    for guild in bot.guilds:
        member = guild.get_member(did)
        if member and member.voice and member.voice.channel:
            return guild, member.voice.channel, member
    return None, None, None


async def http_move(request: web.Request, bot) -> web.Response:
    data = await request.json()
    target = data.get("target", "bot")
    channel_name = data.get("channel_name", "").strip()
    member_name = data.get("member_name", "").strip()
    discord_id = data.get("discord_id", "").strip()

    guild = get_active_guild(bot)
    if not guild:
        return web.json_response({"ok": False, "error": "no guild"}, status=500)

    channel = None
    if channel_name:
        channel = find_channel_by_name(guild, channel_name)
        if not channel:
            target_g = get_target_guild(bot)
            all_guilds = [target_g] + [g for g in bot.guilds if g != target_g] if target_g else list(bot.guilds)
            for g in all_guilds:
                ch = find_channel_by_name(g, channel_name)
                if ch:
                    channel = ch
                    guild = g
                    break
        if not channel:
            return web.json_response({"ok": False, "error": f"Canal '{channel_name}' no encontrado"}, status=404)

    moved = []
    errors = []
    player = get_player(guild.id)

    if target in ("bot", "both"):
        if player.voice_client and player.voice_client.is_connected():
            try:
                await player.voice_client.move_to(channel)
                moved.append("bot")
            except Exception as e:
                errors.append(f"bot: {e}")
        else:
            try:
                await player.connect(channel)
                moved.append("bot")
            except Exception as e:
                errors.append(f"bot connect: {e}")

    if target in ("member", "both"):
        member = None
        member_guild, _, direct_member = find_member_voice_channel(bot, discord_id)
        if direct_member:
            guild = member_guild
            member = direct_member
        if not member:
            member = find_member_by_name(guild, member_name)
        if not member and not channel:
            voice_humans = [
                m for g in ([guild] + [g2 for g2 in bot.guilds if g2 != guild])
                for vc in g.voice_channels
                for m in vc.members if not m.bot
            ]
            if len(voice_humans) == 1:
                member = voice_humans[0]
                logger.info("[MOVE] Auto-detectado usuario en voz: %s", member.display_name)

        if member:
            try:
                await member.move_to(channel if channel else None)
                moved.append("member")
            except Exception as e:
                errors.append(f"member: {e}")
        else:
            errors.append(f"miembro '{member_name}' no encontrado en Discord")

    return web.json_response({
        "ok": len(moved) > 0,
        "moved": moved,
        "channel": channel.name if channel else None,
        "errors": errors,
    })


async def http_context(request: web.Request, bot) -> web.Response:
    """
    GET /context?discord_id=...

    If discord_id is present, return that user's voice context. Otherwise keep
    the legacy behavior and return the first human voice channel found.
    """
    discord_id = request.rel_url.query.get("discord_id", "").strip()
    guild, channel, member = find_member_voice_channel(bot, discord_id)
    if guild and channel:
        humans = [m for m in channel.members if not m.bot]
        return web.json_response({
            "in_discord": True,
            "channel": channel.name,
            "guild": guild.name,
            "members": [m.display_name for m in humans],
            "user": member.display_name if member else None,
            "scoped": True,
        })
    if discord_id:
        return web.json_response({
            "in_discord": False,
            "channel": None,
            "guild": None,
            "members": [],
            "user": None,
            "scoped": True,
        })

    target = get_target_guild(bot)
    guilds = [target] if target else []
    guilds += [g for g in bot.guilds if g != target]
    for guild in guilds:
        for vc in guild.voice_channels:
            humans = [m for m in vc.members if not m.bot]
            if humans:
                return web.json_response({
                    "in_discord": True,
                    "channel": vc.name,
                    "guild": guild.name,
                    "members": [m.display_name for m in humans],
                    "user": None,
                    "scoped": False,
                })

    return web.json_response({
        "in_discord": False,
        "channel": None,
        "guild": None,
        "members": [],
        "user": None,
        "scoped": bool(discord_id),
    })


async def http_discord_auth(request: web.Request) -> web.Response:
    """Exchange a Discord RPC authorization code for user identity."""
    import aiohttp as _http
    import time as _time

    try:
        data = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "JSON invalido"}, status=400)

    code = (data.get("code") or "").strip()
    if not code:
        return web.json_response({"ok": False, "error": "missing code"}, status=400)

    client_id = os.getenv("DISCORD_CLIENT_ID", "").strip()
    client_secret = os.getenv("DISCORD_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        return web.json_response({"ok": False, "error": "Discord OAuth no configurado"}, status=500)

    try:
        async with _http.ClientSession() as session:
            async with session.post(
                "https://discord.com/api/oauth2/token",
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": "http://localhost",
                },
            ) as resp:
                token_data = await resp.json()
                if resp.status != 200 or "access_token" not in token_data:
                    logger.error("[DISCORD_AUTH] Token exchange fallo: %s", token_data)
                    return web.json_response(
                        {"ok": False, "error": "token exchange failed", "detail": token_data},
                        status=400,
                    )
                access_token = token_data["access_token"]

            async with session.get(
                "https://discord.com/api/users/@me",
                headers={"Authorization": f"Bearer {access_token}"},
            ) as resp:
                user_data = await resp.json()

        expires_at = int(_time.time()) + token_data.get("expires_in", 604800)
        logger.info("[DISCORD_AUTH] Usuario autenticado: %s (%s)",
                    user_data.get("username"), user_data.get("id"))
        return web.json_response({
            "ok": True,
            "user_id": user_data.get("id"),
            "username": user_data.get("username"),
            "display_name": user_data.get("global_name") or user_data.get("username"),
            "access_token": access_token,
            "refresh_token": token_data.get("refresh_token", ""),
            "expires_at": expires_at,
        })
    except Exception as e:
        logger.error("[DISCORD_AUTH] Error: %s", e)
        return web.json_response({"ok": False, "error": str(e)}, status=500)


async def http_discord_refresh(request: web.Request) -> web.Response:
    """Refresh a stored Discord OAuth access token."""
    import aiohttp as _http
    import time as _time

    try:
        data = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "JSON invalido"}, status=400)

    refresh_token = (data.get("refresh_token") or "").strip()
    if not refresh_token:
        return web.json_response({"ok": False, "error": "missing refresh_token"}, status=400)

    client_id = os.getenv("DISCORD_CLIENT_ID", "").strip()
    client_secret = os.getenv("DISCORD_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        return web.json_response({"ok": False, "error": "Discord OAuth no configurado"}, status=500)

    try:
        async with _http.ClientSession() as session:
            async with session.post(
                "https://discord.com/api/oauth2/token",
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
            ) as resp:
                token_data = await resp.json()
                if resp.status != 200 or "access_token" not in token_data:
                    return web.json_response(
                        {"ok": False, "error": "refresh failed", "detail": token_data},
                        status=400,
                    )

        expires_at = int(_time.time()) + token_data.get("expires_in", 604800)
        return web.json_response({
            "ok": True,
            "access_token": token_data["access_token"],
            "refresh_token": token_data.get("refresh_token", refresh_token),
            "expires_at": expires_at,
        })
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)
