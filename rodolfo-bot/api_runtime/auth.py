"""Authentication helpers and middleware for the Rodo HTTP API."""

import logging
import os
import secrets

from aiohttp import web
from dotenv import load_dotenv

import tokens as token_mgr

load_dotenv()

API_TOKEN = os.getenv("API_TOKEN", "").strip()
logger = logging.getLogger("rodolfo.api.auth")


def master_token() -> str:
    """Return the configured master token, creating a temporary one if needed."""
    global API_TOKEN
    if not API_TOKEN:
        API_TOKEN = secrets.token_urlsafe(32)
        print("=" * 60)
        print("API_TOKEN no configurado en .env")
        print(f"Token temporal para esta sesion: {API_TOKEN}")
        print("Agrega esto a tu .env para usarlo siempre:")
        print(f"API_TOKEN={API_TOKEN}")
        print("=" * 60)
    return API_TOKEN


def resolve_auth(auth_header: str) -> tuple[bool, str | None, str | None]:
    """
    Validate an Authorization header.

    Returns (valid, display_name, username_key). Master token users get
    (True, None, None); regular users get their display name and tokens.json key.
    """
    if not auth_header.startswith("Bearer "):
        return False, None, None
    token = auth_header[7:].strip()
    if token == master_token():
        return True, None, None
    display_name, username_key = token_mgr.check_user_token_full(token)
    if display_name:
        return True, display_name, username_key
    return False, None, None


@web.middleware
async def auth_middleware(request: web.Request, handler):
    """Validate API tokens for all routes except /health."""
    if request.path == "/health":
        return await handler(request)

    auth = request.headers.get("Authorization", "")
    valid, user_name, user_key = resolve_auth(auth)

    if not valid:
        client_ip = request.remote or "desconocida"
        token_preview = "<missing>" if not auth else auth[:16] + "..."
        logger.warning(
            "[AUTH] Acceso rechazado - IP: %s | path: %s | token: %s",
            client_ip,
            request.path,
            token_preview,
        )
        return web.json_response(
            {
                "error": "unauthorized",
                "hint": "Falta o es incorrecto el header Authorization: Bearer <token>",
            },
            status=401,
        )

    if request.path.startswith("/admin/") and user_name is not None:
        return web.json_response(
            {"error": "forbidden", "hint": "Esta ruta requiere el token maestro"},
            status=403,
        )

    request["auth_user"] = user_name
    request["auth_user_key"] = user_key
    return await handler(request)

