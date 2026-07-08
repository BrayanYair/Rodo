"""HTTP server composition for the Rodo bot API."""

import os

from aiohttp import web
from dotenv import load_dotenv

import tokens as token_mgr
from .admin import (
    http_admin_add_user,
    http_admin_get_token,
    http_admin_list_users,
    http_admin_reactivate_user,
    http_admin_revoke_user,
)
from .auth import auth_middleware, master_token
from .command import http_command
from .context import http_context, http_discord_auth, http_discord_refresh, http_move
from .music import (
    http_clear_queue,
    http_disconnect,
    http_health,
    http_pause,
    http_play,
    http_remove_last,
    http_resume,
    http_say,
    http_skip,
    http_status,
    http_stop,
    http_volume,
)
from .spotify import (
    http_spotify_oauth_url,
    http_spotify_status,
    http_spotify_user_auth,
    http_spotify_pause,
    http_spotify_resume,
)
from .dashboard import (
    http_dashboard,
    http_dashboard_stats,
    http_dashboard_logs,
    http_dashboard_cleanup,
    http_dashboard_cache_list,
    http_dashboard_cache_delete,
    http_dashboard_cache_refresh,
    http_client_log,
)

load_dotenv()

HTTP_HOST = os.getenv("MUSIC_BOT_HOST", "127.0.0.1")
HTTP_PORT = int(os.getenv("MUSIC_BOT_PORT", "5000") or 5000)


def _bind_bot(handler, bot):
    async def _wrapped(request):
        return await handler(request, bot)
    return _wrapped


async def start_http(bot):
    """Start the aiohttp API server once from bot.on_ready."""
    app = web.Application(middlewares=[auth_middleware])

    app.router.add_post("/play", _bind_bot(http_play, bot))
    app.router.add_post("/skip", _bind_bot(http_skip, bot))
    app.router.add_post("/stop", _bind_bot(http_stop, bot))
    app.router.add_post("/pause", _bind_bot(http_pause, bot))
    app.router.add_post("/resume", _bind_bot(http_resume, bot))
    app.router.add_post("/disconnect", _bind_bot(http_disconnect, bot))
    app.router.add_post("/volume", _bind_bot(http_volume, bot))
    app.router.add_post("/clear_queue", _bind_bot(http_clear_queue, bot))
    app.router.add_post("/remove_last", _bind_bot(http_remove_last, bot))
    app.router.add_post("/say", _bind_bot(http_say, bot))
    app.router.add_post("/command", _bind_bot(http_command, bot))
    app.router.add_get("/status", _bind_bot(http_status, bot))
    app.router.add_post("/move", _bind_bot(http_move, bot))
    app.router.add_get("/context", _bind_bot(http_context, bot))
    app.router.add_get("/health", _bind_bot(http_health, bot))

    app.router.add_post("/discord_auth", http_discord_auth)
    app.router.add_post("/discord_refresh", http_discord_refresh)

    app.router.add_get("/spotify_oauth_url", http_spotify_oauth_url)
    app.router.add_post("/spotify_user_auth", http_spotify_user_auth)
    app.router.add_get("/me/spotify_status", http_spotify_status)
    app.router.add_post("/api/spotify/pause", http_spotify_pause)
    app.router.add_post("/api/spotify/resume", http_spotify_resume)

    # ── Panel de Control (Dashboard) ──────────────────────────────────────────
    app.router.add_get("/dashboard", _bind_bot(http_dashboard, bot))
    app.router.add_get("/dashboard/", _bind_bot(http_dashboard, bot))
    app.router.add_get("/api/dashboard/stats", _bind_bot(http_dashboard_stats, bot))
    app.router.add_get("/api/dashboard/logs", _bind_bot(http_dashboard_logs, bot))
    app.router.add_post("/api/dashboard/cleanup", _bind_bot(http_dashboard_cleanup, bot))
    app.router.add_get("/api/dashboard/cache", _bind_bot(http_dashboard_cache_list, bot))
    app.router.add_post("/api/dashboard/cache/delete", _bind_bot(http_dashboard_cache_delete, bot))
    app.router.add_post("/api/dashboard/cache/refresh", _bind_bot(http_dashboard_cache_refresh, bot))
    app.router.add_post("/api/client_log", _bind_bot(http_client_log, bot))

    app.router.add_post("/admin/add_user", http_admin_add_user)
    app.router.add_post("/admin/revoke_user", http_admin_revoke_user)
    app.router.add_post("/admin/reactivate_user", http_admin_reactivate_user)
    app.router.add_get("/admin/users", http_admin_list_users)
    app.router.add_get("/admin/get_token", http_admin_get_token)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, HTTP_HOST, HTTP_PORT)
    await site.start()

    token = master_token()
    local = HTTP_HOST in ("127.0.0.1", "localhost")
    scope = "solo local" if local else "PUBLICO - expuesto a internet"
    print(f"[HTTP] API en {HTTP_HOST}:{HTTP_PORT} ({scope})")
    print(f"[HTTP] Token maestro: Bearer {token[:8]}...{token[-4:]}")
    print(f"[HTTP] Usuarios registrados: {len(token_mgr.list_users())}")
    if not local:
        print("[HTTP] ADVERTENCIA: si vas a exponer esto, usa nginx + SSL")

