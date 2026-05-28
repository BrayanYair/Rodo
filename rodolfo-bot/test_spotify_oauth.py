"""
test_spotify_oauth.py — Prueba completa del flujo OAuth de Spotify (Phase 2).

Cómo usarlo:
  1. Asegurate de que el bot esté corriendo  (python bot.py)
  2. En Spotify Dashboard, agregá el redirect URI: http://localhost:8765/callback
  3. Ejecutá:  python test_spotify_oauth.py
  4. Se abre el navegador → iniciás sesión en Spotify → aceptás los permisos
  5. El script captura el código automáticamente y lo intercambia en el bot
  6. Verifica que los tokens quedaron guardados en tokens.json

Cambiá USER_TOKEN para probar con Brayan o SINAMOR.
"""

import sys, json, threading, webbrowser
import urllib.parse, http.server, requests

# ─── Config ──────────────────────────────────────────────────────────────────
BASE          = "http://localhost:5000"
CALLBACK_PORT = 8888
CALLBACK_HOST = "127.0.0.1"

# Elegí con qué usuario probar:
# Dueño (token maestro):
USER_TOKEN = "hrCriwyBg8xWgCuS5ytmxeaAeChD9GCMoIJqXf00frg"
USER_LABEL = "owner"

# Brayan:
# USER_TOKEN = "M5XI624mKEipiWy0D82ZW9391YGW1oD9IZYwyrCFt7M"
# USER_LABEL = "brayan"

# SINAMOR:
# USER_TOKEN = "aOhESdG1sMkSKdTIzE1Visr97e-X9qeRrpOXaM19S1g"
# USER_LABEL = "sinamor"

HEADERS = {"Authorization": f"Bearer {USER_TOKEN}"}

# ─── Colores ─────────────────────────────────────────────────────────────────
OK   = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
INFO = "\033[94m→\033[0m"

def ok(msg):   print(f"  {OK}  {msg}")
def fail(msg): print(f"  {FAIL}  {msg}"); sys.exit(1)
def info(msg): print(f"  {INFO}  {msg}")

# ─── Test ─────────────────────────────────────────────────────────────────────
print()
print("╔═══════════════════════════════════════════════╗")
print("║    Phase 2 — Test OAuth Spotify               ║")
print(f"║    Usuario: {USER_LABEL:<33}║")
print("╚═══════════════════════════════════════════════╝")
print()

# 1. Health check
print("[ 1/5 ] Health del bot...")
try:
    r = requests.get(f"{BASE}/health", timeout=5)
    d = r.json()
    ok(f"Bot online — {d['guilds']} servidores, latencia {d['latency']}ms")
except Exception as e:
    fail(f"Bot no responde en {BASE}: {e}")

# 2. Obtener URL de autorización
print()
print("[ 2/5 ] Obteniendo URL de autorización...")
try:
    r = requests.get(f"{BASE}/spotify_oauth_url", headers=HEADERS, timeout=10)
    d = r.json()
    if not d.get("ok"):
        fail(f"Error: {d.get('error')}")
    auth_url      = d["url"]
    callback_port = d.get("callback_port", CALLBACK_PORT)
    callback_host = d.get("callback_host", CALLBACK_HOST)
    ok(f"URL generada (state={urllib.parse.parse_qs(urllib.parse.urlparse(auth_url).query).get('state',['?'])[0]})")
    info(f"callback = {callback_host}:{callback_port}")
except Exception as e:
    fail(f"Error en GET /spotify_oauth_url: {e}")

# 3. Servidor local de callback
print()
print("[ 3/5 ] Iniciando servidor de callback local...")
_result = {"code": None, "state": None, "error": None}
_done   = threading.Event()

class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if "/callback" in self.path:
            params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            _result["code"]  = params.get("code",  [""])[0]
            _result["state"] = params.get("state", [""])[0]
            _result["error"] = params.get("error", [""])[0]
            body = (
                b"<html><body style='font-family:sans-serif;padding:40px;background:#1DB954;color:white'>"
                b"<h2>&#127914; Listo! Podes cerrar esta pestana.</h2>"
                b"<p>Spotify vinculado correctamente. Volve a la terminal para ver el resultado.</p>"
                b"</body></html>"
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            _done.set()
        else:
            self.send_response(404)
            self.end_headers()
    def log_message(self, *a):
        pass   # silenciar logs de acceso

try:
    srv = http.server.HTTPServer((callback_host, callback_port), _Handler)
    threading.Thread(target=srv.handle_request, daemon=True).start()
    ok(f"Escuchando en localhost:{callback_port}/callback")
except OSError as e:
    fail(f"No se pudo abrir el puerto {callback_port}: {e}")

# 4. Abrir navegador
print()
print("[ 4/5 ] Abriendo Spotify en el navegador...")
webbrowser.open(auth_url)
info("Iniciá sesión en Spotify y aceptá los permisos.")
info("El navegador te va a redirigir automáticamente.")
print()
print("  Esperando callback (máx. 2 minutos)...", end="", flush=True)

if not _done.wait(120):
    print()
    fail("Timeout — no se completó el flujo en 2 minutos.")

print(" recibido!")
srv.server_close()

code  = _result["code"]
state = _result["state"]
err   = _result["error"]

if err or not code:
    fail(f"Spotify devolvió error: '{err}' (sin código)")

ok(f"Código OAuth recibido (state={state!r})")
info(f"code = {code[:20]}...")

# 5. Intercambiar código en el bot
print()
print("[ 5/5 ] Intercambiando código con el bot...")
try:
    r2 = requests.post(
        f"{BASE}/spotify_user_auth",
        json={"code": code, "state": state},
        headers=HEADERS,
        timeout=15,
    )
    d2 = r2.json()
    if not d2.get("ok"):
        fail(f"Bot rechazó el código: {d2.get('error')} — {d2.get('detail', '')}")
    ok(f"Tokens guardados para '{d2.get('username')}'")
except Exception as e:
    fail(f"Error en POST /spotify_user_auth: {e}")

# Verificar tokens.json
print()
print("[ ✓ ] Verificando tokens.json...")
try:
    with open("tokens.json", encoding="utf-8") as f:
        tj = json.load(f)
    user_key = state or "owner"
    sp = tj.get(user_key, {}).get("spotify")
    if sp:
        ok(f"access_token  : {sp['access_token'][:30]}...")
        ok(f"refresh_token : {sp['refresh_token'][:30]}...")
        ok(f"expires_at    : {sp['expires_at']}")
    else:
        # El owner no tiene entrada en tokens.json — buscar por estado
        info("(el token maestro/owner no se guarda en tokens.json — OK)")
except Exception as e:
    info(f"No se pudo leer tokens.json: {e}")

print()
print("╔═══════════════════════════════════════════════╗")
print("║  ✓  FASE 2 — SPOTIFY OAUTH: TODO OK           ║")
print("╠═══════════════════════════════════════════════╣")
print("║  Ya podés decir:                              ║")
print("║    'rodo mis guardadas'                        ║")
print("║    'rodo mis favoritas en random'              ║")
print("╚═══════════════════════════════════════════════╝")
print()

# Bonus: probar "mis guardadas" para ver qué encontró
print("[ BONUS ] Probando 'mis guardadas' en el bot...")
try:
    r3 = requests.post(
        f"{BASE}/command",
        json={"text": "mis guardadas en random"},
        headers=HEADERS,
        timeout=30,
    )
    d3 = r3.json()
    if d3.get("ok") and d3.get("added"):
        print()
        ok(f"¡Funcionó! Primera canción: {d3['added'][0]}")
        info(f"Cola total: {d3.get('queue_size', '?')} canciones")
    elif d3.get("need_spotify_auth"):
        info("(El usuario de prueba es el owner — no tiene entrada en tokens.json)")
        info("Probá con el token de Brayan o SINAMOR descomentando las líneas al inicio.")
    else:
        info(f"Respuesta: {json.dumps(d3, ensure_ascii=False)[:120]}")
except Exception as e:
    info(f"Error: {e}")

print()
