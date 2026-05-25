"""
config_manager.py — Gestión de configuración para rodolfo-amigo.

Guarda la config en AppData del usuario (nunca en la carpeta de la app).
El usuario nunca necesita tocar ningún archivo manualmente.

Ubicación:
  Windows : C:\\Users\\<user>\\AppData\\Local\\RodolfoAmigo\\config.json
  macOS   : ~/Library/Application Support/RodolfoAmigo/config.json
  Linux   : ~/.config/rodolfo-amigo/config.json
"""

import json
import sys
from pathlib import Path

# ─── Ruta del archivo de config ───────────────────────────────────────────────

def _config_dir() -> Path:
    if sys.platform == "win32":
        base = Path.home() / "AppData" / "Local"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path.home() / ".config"
    return base / "RodolfoAmigo"


CONFIG_DIR  = _config_dir()
CONFIG_FILE = CONFIG_DIR / "config.json"


# ─── Estructura por defecto ───────────────────────────────────────────────────

DEFAULT_CONFIG = {
    "nombre":      "",
    "mode":        "webhook",   # "webhook" | "api"
    "webhook_url": "",
    "api_url":     "",
    "api_token":   "",
}


# ─── API pública ──────────────────────────────────────────────────────────────

def config_exists() -> bool:
    """¿Ya existe un config guardado?"""
    if not CONFIG_FILE.exists():
        return False
    cfg = load_config()
    # Consideramos que existe si tiene nombre y al menos un método de conexión
    return bool(cfg.get("nombre")) and (
        bool(cfg.get("webhook_url")) or
        (bool(cfg.get("api_url")) and bool(cfg.get("api_token")))
    )


def load_config() -> dict:
    """
    Carga la config. Prioridad:
      1. config.json en AppData (usuario normal)
      2. Variables de entorno / .env (desarrollador / dueño)
    """
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            # Merge con defaults para no romper si hay claves nuevas
            cfg = {**DEFAULT_CONFIG, **data}
            return cfg
        except Exception:
            pass

    # Fallback: variables de entorno (para el dueño que usa .env)
    import os
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    api_url     = os.getenv("BOT_API_URL",   "").strip().rstrip("/")
    api_token   = os.getenv("BOT_API_TOKEN", "").strip()

    mode = "api" if (api_url and api_token) else "webhook"

    return {
        **DEFAULT_CONFIG,
        "nombre":      os.getenv("NOMBRE", "").strip(),
        "mode":        mode,
        "webhook_url": webhook_url,
        "api_url":     api_url,
        "api_token":   api_token,
    }


def save_config(cfg: dict) -> None:
    """Guarda la config en AppData."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(
        json.dumps(cfg, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def reset_config() -> None:
    """Borra la config guardada (útil para 'Reconfigurar' desde el menú)."""
    if CONFIG_FILE.exists():
        CONFIG_FILE.unlink()
