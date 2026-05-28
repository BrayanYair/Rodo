"""Spotify OAuth and per-user Spotify status handlers."""

import base64
import logging
import os
import time

from aiohttp import web
from dotenv import load_dotenv

import tokens as token_mgr

load_dotenv()
logger = logging.getLogger("rodolfo.api.spotify")


def auth_user_key(request: web.Request) -> str:
    """Return the tokens.json key for this request."""
    return request.get("auth_user_key") or "owner"


async def get_valid_user_spotify_token(username: str) -> str | None:
    """
    Return a valid Spotify access token for a Rodo user.

    If the token is close to expiry, refresh it and update tokens.json.
    """
    import aiohttp as _http

    info = token_mgr.get_spotify_token_info(username)
    if not info:
        return None

    access_token = info.get("access_token", "")
    refresh_token = info.get("refresh_token", "")
    expires_at = info.get("expires_at", 0)

    if access_token and time.time() < expires_at - 300:
        return access_token

    if not refresh_token:
        return access_token or None

    sp_client_id = os.getenv("SPOTIFY_CLIENT_ID", "")
    sp_client_secret = os.getenv("SPOTIFY_CLIENT_SECRET", "")
    if not sp_client_id or not sp_client_secret:
        return access_token or None

    try:
        credentials = base64.b64encode(
            f"{sp_client_id}:{sp_client_secret}".encode()
        ).decode()
        async with _http.ClientSession() as session:
            async with session.post(
                "https://accounts.spotify.com/api/token",
                headers={
                    "Authorization": f"Basic {credentials}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
            ) as resp:
                data = await resp.json()
                if resp.status == 200:
                    new_access = data["access_token"]
                    new_refresh = data.get("refresh_token", refresh_token)
                    new_expiry = int(time.time()) + data.get("expires_in", 3600)
                    token_mgr.set_spotify_tokens(username, new_access, new_refresh, new_expiry)
                    logger.info("[SPOTIFY_OAUTH] Token refrescado para '%s'", username)
                    return new_access
                logger.warning("[SPOTIFY_OAUTH] Refresh fallo para '%s': %s", username, data)
                return access_token or None
    except Exception as e:
        logger.error("[SPOTIFY_OAUTH] Error refrescando token de '%s': %s", username, e)
        return access_token or None


async def http_spotify_status(request: web.Request) -> web.Response:
    """GET /me/spotify_status - report whether this user has linked Spotify."""
    user_key = auth_user_key(request)
    token = await get_valid_user_spotify_token(user_key)
    return web.json_response({
        "ok": True,
        "username": user_key,
        "linked": bool(token),
    })


async def http_spotify_oauth_url(request: web.Request) -> web.Response:
    sp_client_id = os.getenv("SPOTIFY_CLIENT_ID", "")
    sp_callback_port = os.getenv("SPOTIFY_CALLBACK_PORT", "8888")
    sp_callback_host = os.getenv("SPOTIFY_CALLBACK_HOST", "127.0.0.1")

    if not sp_client_id:
        return web.json_response(
            {"ok": False, "error": "Spotify no configurado en el bot (.env)"},
            status=500,
        )

    user_key = auth_user_key(request)
    redirect_uri = f"http://{sp_callback_host}:{sp_callback_port}/callback"

    import urllib.parse
    params = urllib.parse.urlencode({
        "client_id": sp_client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": "user-library-read playlist-read-private user-read-private",
        "state": user_key,
        "show_dialog": "false",
    })
    url = f"https://accounts.spotify.com/authorize?{params}"
    logger.info("[SPOTIFY_OAUTH] URL generada para '%s' (redirect=%s)", user_key, redirect_uri)
    return web.json_response({
        "ok": True,
        "url": url,
        "callback_port": int(sp_callback_port),
        "callback_host": sp_callback_host,
    })


async def http_spotify_user_auth(request: web.Request) -> web.Response:
    import aiohttp as _http

    try:
        data = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "JSON invalido"}, status=400)

    code = (data.get("code") or "").strip()
    state = (data.get("state") or "").strip()
    if not code:
        return web.json_response({"ok": False, "error": "missing code"}, status=400)

    sp_client_id = os.getenv("SPOTIFY_CLIENT_ID", "")
    sp_client_secret = os.getenv("SPOTIFY_CLIENT_SECRET", "")
    sp_callback_port = os.getenv("SPOTIFY_CALLBACK_PORT", "8888")
    sp_callback_host = os.getenv("SPOTIFY_CALLBACK_HOST", "127.0.0.1")

    if not sp_client_id or not sp_client_secret:
        return web.json_response(
            {"ok": False, "error": "Spotify no configurado en el bot (.env)"},
            status=500,
        )

    user_key = state or auth_user_key(request)
    redirect_uri = f"http://{sp_callback_host}:{sp_callback_port}/callback"

    try:
        credentials = base64.b64encode(
            f"{sp_client_id}:{sp_client_secret}".encode()
        ).decode()
        async with _http.ClientSession() as session:
            async with session.post(
                "https://accounts.spotify.com/api/token",
                headers={
                    "Authorization": f"Basic {credentials}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                },
            ) as resp:
                token_data = await resp.json()
                if resp.status != 200 or "access_token" not in token_data:
                    logger.error("[SPOTIFY_OAUTH] Exchange fallo: %s", token_data)
                    return web.json_response(
                        {"ok": False, "error": "token exchange failed", "detail": token_data},
                        status=400,
                    )

        access_token = token_data["access_token"]
        refresh_token = token_data.get("refresh_token", "")
        expires_at = int(time.time()) + token_data.get("expires_in", 3600)

        token_mgr.set_spotify_tokens(user_key, access_token, refresh_token, expires_at)
        logger.info("[SPOTIFY_OAUTH] Spotify vinculado para '%s'", user_key)
        return web.json_response({
            "ok": True,
            "username": user_key,
            "message": "Spotify vinculado correctamente",
        })

    except Exception as e:
        logger.error("[SPOTIFY_OAUTH] Error en http_spotify_user_auth: %s", e)
        return web.json_response({"ok": False, "error": str(e)}, status=500)

