"""Admin-only user token handlers."""

import logging

from aiohttp import web

import tokens as token_mgr

logger = logging.getLogger("rodolfo.api.admin")


async def http_admin_add_user(request: web.Request) -> web.Response:
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "JSON invalido"}, status=400)

    username = (data.get("username") or "").strip().lower()
    name = (data.get("name") or "").strip() or username.capitalize()
    if not username:
        return web.json_response({"error": "Falta 'username'"}, status=400)

    result = token_mgr.add_user(username, name)
    logger.info("[ADMIN] Usuario anadido: %s (%s)", username, name)
    return web.json_response({"ok": True, **result})


async def http_admin_revoke_user(request: web.Request) -> web.Response:
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "JSON invalido"}, status=400)

    username = (data.get("username") or "").strip().lower()
    if not username:
        return web.json_response({"error": "Falta 'username'"}, status=400)

    ok = token_mgr.revoke_user(username)
    if not ok:
        return web.json_response({"ok": False, "error": f"Usuario '{username}' no encontrado"}, status=404)
    logger.info("[ADMIN] Usuario revocado: %s", username)
    return web.json_response({"ok": True, "username": username, "status": "revocado"})


async def http_admin_reactivate_user(request: web.Request) -> web.Response:
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "JSON invalido"}, status=400)

    username = (data.get("username") or "").strip().lower()
    if not username:
        return web.json_response({"error": "Falta 'username'"}, status=400)

    ok = token_mgr.reactivate_user(username)
    if not ok:
        return web.json_response({"ok": False, "error": f"Usuario '{username}' no encontrado"}, status=404)
    return web.json_response({"ok": True, "username": username, "status": "activo"})


async def http_admin_list_users(request: web.Request) -> web.Response:
    users = token_mgr.list_users()
    return web.json_response({"ok": True, "count": len(users), "users": users})


async def http_admin_get_token(request: web.Request) -> web.Response:
    username = request.rel_url.query.get("username", "").strip().lower()
    if not username:
        return web.json_response({"error": "Falta query param 'username'"}, status=400)
    token = token_mgr.get_user_token(username)
    if token is None:
        return web.json_response({"error": f"Usuario '{username}' no encontrado o inactivo"}, status=404)
    return web.json_response({"ok": True, "username": username, "token": token})

