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

PORT       = int(os.getenv("MUSIC_BOT_PORT", 5000))
API_TOKEN  = os.getenv("API_TOKEN", "")
NGROK_DOMAIN = os.getenv("NGROK_DOMAIN", "")   # dominio fijo en .env

print()
print("=" * 54)
print("    Rodo Bot  —  Lanzador local con ngrok")
print("=" * 54)
print()
print("[1/2] Abriendo tunel ngrok...")

def _connect_ngrok(retries=2):
    for attempt in range(retries + 1):
        try:
            if NGROK_DOMAIN:
                return ngrok.connect(PORT, "http", domain=NGROK_DOMAIN)
            else:
                return ngrok.connect(PORT, "http")
        except Exception as e:
            if "ERR_NGROK_334" in str(e) and attempt < retries:
                print(f"  Sesion anterior colgada, liberando y reintentando...")
                ngrok.kill()
                import time; time.sleep(3)
            else:
                print(f"ERROR abriendo ngrok: {e}")
                sys.exit(1)

tunnel     = _connect_ngrok()
public_url = tunnel.public_url

print()
print("=" * 54)
print("  DATOS PARA CONFIGURAR Rodo.exe")
print("-" * 54)
print(f"  URL del servidor : {public_url}")
print(f"  Contrasena       : {API_TOKEN}")
print("=" * 54)
print()
print("  Comparte estos datos con tus amigos.")
if NGROK_DOMAIN:
    print("  La URL es FIJA — no cambia al reiniciar.")
else:
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
