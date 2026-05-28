"""
config_manager.py — Gestión de configuración para Rodo.

Guarda la config en la carpeta del sistema del usuario.
Nunca en la carpeta de la app, nunca en un archivo que el usuario deba tocar.

Ubicación:
  Windows : C:\\Users\\<user>\\AppData\\Local\\Rodo\\config.json
  macOS   : ~/Library/Application Support/Rodo/config.json
  Linux   : ~/.config/rodo/config.json
"""

import json
import sys
from pathlib import Path


def _config_dir() -> Path:
    # Cuando corre como .exe de PyInstaller, guardar junto al exe
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    # En desarrollo: AppData/Local/Rodo
    if sys.platform == "win32":
        base = Path.home() / "AppData" / "Local"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path.home() / ".config"
    return base / "Rodo"


CONFIG_DIR  = _config_dir()
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_CONFIG = {
    "nombre":                "",
    "mode":                  "api",
    "api_url":               "",
    "api_token":             "",
    "discord_id":            "",   # Discord user ID — detectado automáticamente
    "discord_access_token":  "",   # OAuth2 access token (expira en 7 días)
    "discord_refresh_token": "",   # Refresh token (long-lived)
    "discord_token_expiry":  0,    # Unix timestamp de expiración del access token
    "spotify_linked":        False, # True si el usuario vinculó su cuenta de Spotify
}


def config_exists() -> bool:
    """¿Ya hay una config válida guardada?"""
    if not CONFIG_FILE.exists():
        return False
    cfg = load_config()
    return (
        bool(cfg.get("nombre")) and
        bool(cfg.get("api_url")) and
        bool(cfg.get("api_token"))
    )


def _normalize_api_url(url: str) -> str:
    """
    Reemplaza 'localhost' por '127.0.0.1' en la URL del bot.
    En Windows, 'localhost' fuerza un intento IPv6 con ~2s de timeout antes
    de caer a IPv4. Con '127.0.0.1' la conexión es directa: 14ms en lugar de 2,050ms.
    Ahorro real: ~4,100ms por comando de música (2 requests × 2,050ms).
    """
    if url.startswith("http://localhost"):
        return url.replace("http://localhost", "http://127.0.0.1", 1)
    return url


def load_config() -> dict:
    """
    Carga la config guardada. Si no existe, devuelve defaults.
    Prioridad:
      1. config.json en AppData (usuario normal)
      2. Variables de entorno / .env (desarrollador)
    """
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            cfg  = {**DEFAULT_CONFIG, **data}
            cfg["api_url"] = _normalize_api_url(cfg.get("api_url", ""))
            return cfg
        except Exception:
            pass

    # Fallback para el dueño/desarrollador que usa .env
    import os
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    return {
        **DEFAULT_CONFIG,
        "nombre":    os.getenv("NOMBRE",        "").strip(),
        "api_url":   os.getenv("BOT_API_URL",   "").strip().rstrip("/"),
        "api_token": os.getenv("BOT_API_TOKEN", "").strip(),
    }


def save_config(cfg: dict) -> None:
    """Guarda la config en la carpeta del sistema."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(
        json.dumps(cfg, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def reset_config() -> None:
    """Borra la config guardada (para reconfigurar desde cero)."""
    if CONFIG_FILE.exists():
        CONFIG_FILE.unlink()
