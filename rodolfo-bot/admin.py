"""
admin.py -- Herramienta de administracion de usuarios de Rodo.

Uso:
  python admin.py add    <username> [nombre completo]
  python admin.py revoke <username>
  python admin.py reactivate <username>
  python admin.py list
  python admin.py token  <username>

Ejemplos:
  python admin.py add brayan Brayan
  python admin.py add camila Cami
  python admin.py revoke brayan
  python admin.py list
  python admin.py token brayan
"""

import sys
import io

# Forzar UTF-8 en Windows para la terminal
if sys.platform == "win32":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

from tokens import add_user, revoke_user, reactivate_user, list_users, get_user_token


def cmd_add(args):
    if not args:
        print("Uso: python admin.py add <username> [nombre]")
        sys.exit(1)
    username = args[0].strip().lower()
    name     = " ".join(args[1:]).strip() if len(args) > 1 else username.capitalize()
    result   = add_user(username, name)
    print()
    print("=" * 64)
    print("  [OK] Usuario anadido")
    print("=" * 64)
    print(f"  Nombre:    {result['name']}")
    print(f"  Username:  {result['username']}")
    print(f"  Creado:    {result['created'][:19]}")
    print("-" * 64)
    print("  TOKEN (enviar al usuario por WhatsApp/Discord):")
    print(f"  {result['token']}")
    print("=" * 64)
    print()
    print("El usuario necesita:")
    print(f"  Direccion del servidor:  <tu URL de ngrok o IP>")
    print(f"  Contrasena de acceso:    {result['token']}")
    print()


def cmd_revoke(args):
    if not args:
        print("Uso: python admin.py revoke <username>")
        sys.exit(1)
    username = args[0].strip().lower()
    ok = revoke_user(username)
    if ok:
        print(f"[OK] Usuario '{username}' revocado. Ya no puede conectarse.")
    else:
        print(f"[X]  Usuario '{username}' no encontrado en tokens.json")


def cmd_reactivate(args):
    if not args:
        print("Uso: python admin.py reactivate <username>")
        sys.exit(1)
    username = args[0].strip().lower()
    ok = reactivate_user(username)
    if ok:
        print(f"[OK] Usuario '{username}' reactivado.")
    else:
        print(f"[X]  Usuario '{username}' no encontrado en tokens.json")


def cmd_list(_args):
    users = list_users()
    if not users:
        print("No hay usuarios registrados. Usa: python admin.py add <username>")
        return
    print()
    print(f"{'Usuario':<15} {'Nombre':<20} {'Activo':<8} {'Token':<20} {'Creado'}")
    print("-" * 80)
    for u in users:
        activo  = "[si]" if u["active"] else "[no]"
        created = u["created"][:10] if u["created"] else "---"
        print(f"{u['username']:<15} {u['name']:<20} {activo:<8} {u['token_preview']:<20} {created}")
    print()


def cmd_token(args):
    if not args:
        print("Uso: python admin.py token <username>")
        sys.exit(1)
    username = args[0].strip().lower()
    token    = get_user_token(username)
    if token:
        print(f"\nToken de '{username}':\n  {token}\n")
    else:
        print(f"[X] Usuario '{username}' no encontrado o inactivo.")


COMMANDS = {
    "add":        cmd_add,
    "revoke":     cmd_revoke,
    "reactivate": cmd_reactivate,
    "list":       cmd_list,
    "token":      cmd_token,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        sys.exit(0)
    COMMANDS[sys.argv[1]](sys.argv[2:])
