"""
lanzar.py — Levanta el bot de Rodo + tunel ngrok para pruebas locales.
Ejecutar con:  python lanzar.py
"""

import sys
import os
import subprocess

# ─── ngrok ───────────────────────────────────────────────────────────────────
try:
    from pyngrok import ngrok
except ImportError:
    print("ERROR: Falta pyngrok. Ejecuta:  pip install pyngrok")
    sys.exit(1)

from dotenv import load_dotenv
load_dotenv()

PORT      = int(os.getenv("MUSIC_BOT_PORT", 5000))
API_TOKEN = os.getenv("API_TOKEN", "")

print()
print("=" * 54)
print("    Rodo Bot  —  Lanzador local con ngrok")
print("=" * 54)
print()
print("[1/2] Abriendo tunel ngrok...")

try:
    tunnel     = ngrok.connect(PORT, "http")
    public_url = tunnel.public_url
except Exception as e:
    print(f"ERROR abriendo ngrok: {e}")
    sys.exit(1)

print()
print("=" * 54)
print("  DATOS PARA CONFIGURAR Rodo.exe")
print("-" * 54)
print(f"  URL del servidor : {public_url}")
print(f"  Contrasena       : {API_TOKEN}")
print("=" * 54)
print()
print("  Comparte estos datos con tus amigos.")
print("  La URL cambia cada vez que reinicias esto.")
print()
print("[2/2] Iniciando bot de Discord...")
print("      Ctrl+C para detener todo")
print()

# ─── Bot ─────────────────────────────────────────────────────────────────────
bot_dir = os.path.dirname(os.path.abspath(__file__))

try:
    proc = subprocess.Popen(
        [sys.executable, "bot.py"],
        cwd=bot_dir,
    )
    proc.wait()
except KeyboardInterrupt:
    print("\nDeteniendo bot...")
    proc.terminate()
finally:
    print("Cerrando tunel ngrok...")
    ngrok.kill()
    print("Hasta luego!")
