"""
bot.py — Punto de entrada principal de Rodolfo Bot.

Responsabilidades de este archivo:
  1. Crear el bot de Discord con los intents correctos.
  2. Cargar los módulos activos según el .env.
  3. Arrancar el servidor HTTP (API local / pública).
  4. Conectar a Discord.

Si un módulo falla al cargar, el bot sigue corriendo con los demás.
Agregar un nuevo módulo = crear modules/<nombre>/cog.py + agregarlo a MODULES.
"""

import os
import sys

# Forzar UTF-8 en Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

class Tee:
    def __init__(self, filename, stream):
        self.stream = stream
        self.filename = filename

    def write(self, data):
        self.stream.write(data)
        self.stream.flush()
        if data:
            try:
                with open(self.filename, "a", encoding="utf-8", errors="replace") as f:
                    f.write(data)
            except Exception:
                pass

    def flush(self):
        self.stream.flush()

log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rodo_log.txt")
try:
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(f"--- RODO BOT STARTUP: {os.getpid()} ---\n")
except Exception:
    pass

sys.stdout = Tee(log_path, sys.stdout)
sys.stderr = Tee(log_path, sys.stderr)

import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)
logging.getLogger("discord").setLevel(logging.WARNING)

import discord
from discord.ext import commands
from dotenv import load_dotenv

from api import start_http

load_dotenv()

# ─── Configuración ─────────────────────────────────────────────────────────────
BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")

# Módulos activos — ponlos en false en .env para desactivarlos
# Si un módulo falla al cargar, el bot sigue con los demás activos.
MODULES = {
    "modules.music": os.getenv("MODULE_MUSIC",     "true").lower() == "true",
    # Próximos módulos (crear modules/<nombre>/cog.py con función setup(bot)):
    # "modules.assistant": os.getenv("MODULE_ASSISTANT", "false").lower() == "true",
    # "modules.calendar":  os.getenv("MODULE_CALENDAR",  "false").lower() == "true",
}

# ─── Bot ───────────────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states    = True
intents.guilds          = True
intents.members         = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ─── Eventos ───────────────────────────────────────────────────────────────────
_http_started = False

@bot.event
async def on_ready():
    global _http_started
    print(f"[BOT] Conectado como {bot.user}")
    print(f"[BOT] Servidores: {[g.name for g in bot.guilds]}")

    if not _http_started:
        bot.loop.create_task(start_http(bot))
        _http_started = True

    print(f"[BOT] Módulos activos: {[k for k, v in MODULES.items() if v]}")


# ─── Carga de módulos ──────────────────────────────────────────────────────────
for module_path, enabled in MODULES.items():
    if not enabled:
        print(f"[MÓDULO] '{module_path}' desactivado en .env")
        continue
    try:
        bot.load_extension(f"{module_path}.cog")
        print(f"[MÓDULO] '{module_path}' cargado correctamente.")
    except Exception as e:
        # Un módulo caído NO mata al bot — solo registra el error
        print(f"[MÓDULO] ⚠️  '{module_path}' falló al cargar: {e}")
        print(f"[MÓDULO]    El bot sigue funcionando sin este módulo.")


# ─── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if not BOT_TOKEN:
        print("ERROR: Falta DISCORD_BOT_TOKEN en .env")
        print("Crea tu bot en https://discord.com/developers/applications")
        sys.exit(1)

    bot.run(BOT_TOKEN)
