"""
tokens.py — Sistema de tokens por usuario para rodolfo-bot.

Permite que cada amigo tenga su propio token único.
El dueño puede agregar o revocar acceso sin tocar el .env.

tokens.json (junto al bot):
{
  "brayan": {
    "token": "abc...",
    "name":  "Brayan",
    "created": "2025-05-25T20:00:00",
    "active": true
  }
}

Flujo típico:
  1. Dueño llama POST /admin/add_user  {"username": "brayan", "name": "Brayan"}
  2. El endpoint devuelve el token generado
  3. Dueño lo manda por WhatsApp a Brayan
  4. Brayan lo pega en su Rodo.exe al configurar
  5. Para revocar: POST /admin/revoke_user {"username": "brayan"}
"""

import json
import secrets
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("rodolfo.tokens")

_TOKENS_FILE = Path(__file__).parent / "tokens.json"


# ─── I/O ──────────────────────────────────────────────────────────────────────

def _load() -> dict:
    """Carga tokens.json. Si no existe o está corrupto, retorna vacío."""
    try:
        return json.loads(_TOKENS_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception as e:
        logger.error(f"[TOKENS] Error leyendo tokens.json: {e}")
        return {}


def _save(data: dict) -> None:
    """Guarda tokens.json con indentación legible."""
    try:
        _TOKENS_FILE.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as e:
        logger.error(f"[TOKENS] Error guardando tokens.json: {e}")


# ─── Validación ───────────────────────────────────────────────────────────────

def check_user_token(token: str) -> str | None:
    """
    Verifica si el token corresponde a un usuario activo.
    Retorna el nombre del usuario si es válido, None si no.
    """
    data = _load()
    for username, info in data.items():
        if info.get("active", False) and info.get("token") == token:
            return info.get("name", username)
    return None


# ─── Gestión ──────────────────────────────────────────────────────────────────

def add_user(username: str, name: str) -> dict:
    """
    Crea un nuevo usuario con token único.
    Si el usuario ya existe y está activo, regenera su token.
    Retorna {"username", "name", "token", "created"}.
    """
    data    = _load()
    token   = secrets.token_urlsafe(32)
    created = datetime.now(timezone.utc).isoformat()

    data[username.lower()] = {
        "token":   token,
        "name":    name,
        "created": created,
        "active":  True,
    }
    _save(data)
    logger.info(f"[TOKENS] Usuario añadido: {username} ({name})")
    return {"username": username.lower(), "name": name, "token": token, "created": created}


def revoke_user(username: str) -> bool:
    """
    Desactiva el token del usuario (sin borrarlo, para historial).
    Retorna True si existía, False si no.
    """
    data = _load()
    key  = username.lower()
    if key not in data:
        return False
    data[key]["active"] = False
    _save(data)
    logger.info(f"[TOKENS] Usuario revocado: {username}")
    return True


def reactivate_user(username: str) -> bool:
    """Reactiva un usuario revocado sin cambiar su token."""
    data = _load()
    key  = username.lower()
    if key not in data:
        return False
    data[key]["active"] = True
    _save(data)
    logger.info(f"[TOKENS] Usuario reactivado: {username}")
    return True


def list_users() -> list[dict]:
    """Retorna todos los usuarios (sin tokens completos por seguridad)."""
    data = _load()
    result = []
    for username, info in data.items():
        token = info.get("token", "")
        result.append({
            "username": username,
            "name":     info.get("name", username),
            "created":  info.get("created", ""),
            "active":   info.get("active", False),
            "token_preview": f"{token[:6]}...{token[-4:]}" if len(token) > 10 else "???",
        })
    return result


def get_user_token(username: str) -> str | None:
    """Retorna el token completo de un usuario (para mostrárselo al dueño)."""
    data = _load()
    info = data.get(username.lower())
    if info and info.get("active"):
        return info.get("token")
    return None
