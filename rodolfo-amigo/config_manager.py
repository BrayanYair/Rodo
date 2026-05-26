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
    "nombre":    "",
    "mode":      "api",
    "api_url":   "",
    "api_token": "",
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
            return {**DEFAULT_CONFIG, **data}
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
