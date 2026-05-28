"""
amigo.py — Cliente de voz para Rodo
=====================================
Escucha tu micrófono, detecta el activador "Rodo",
y manda el comando directamente al servidor de Rodo.

NO necesitas Whisper ni nada pesado — Google STT (gratis, sin instalar nada).
Solo necesitas internet y un micrófono.
"""

import os
import sys
import time
import re
import unicodedata
import socket
import subprocess
import threading

# ─── Orquestador central ──────────────────────────────────────────────────────
# Importar DESPUÉS de sys.path manipulation (PyInstaller), pero ANTES del resto.
# Se define más abajo (post frozen-block) para que _bundle_dir ya esté en path.
_orch = None   # se asigna después del bloque frozen

# Cuando corre como .exe de PyInstaller, agregar la carpeta del bundle al path
# para que los módulos locales (overlay, config_manager, setup_gui) se encuentren.
if getattr(sys, "frozen", False):
    _bundle_dir = sys._MEIPASS                      # carpeta temporal del bundle
    sys.path.insert(0, _bundle_dir)
    os.chdir(_bundle_dir)

# ─── Instancia única (evita dos Rodo corriendo a la vez) ──────────────────────
if sys.platform == "win32":
    import ctypes as _ctypes
    _MUTEX_NAME = "Global\\RodoVoiceAssistant_SingleInstance"
    _mutex = _ctypes.windll.kernel32.CreateMutexW(None, True, _MUTEX_NAME)
    if _ctypes.windll.kernel32.GetLastError() == 183:   # ERROR_ALREADY_EXISTS
        # Ya hay una instancia corriendo → notificar amigablemente y salir
        import ctypes as _ct
        _ct.windll.user32.MessageBoxW(
            0,
            "¡Rodo ya está escuchando!\n\nSi no ves el ícono, buscalo en la bandeja del sistema (esquina inferior derecha).",
            "Rodo — ya activo",
            0x40,  # MB_ICONINFORMATION  (ícono ℹ️, no parece error)
        )
        sys.exit(0)

# ─── Orquestador (se importa aquí, después de que sys.path ya está listo) ─────
from orchestrator import orchestrator as _orch   # singleton global

# Forzar UTF-8 en Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

try:
    import requests
except ImportError:
    print("ERROR: Falta 'requests'. Ejecuta instalar.bat primero.")
    input("Presiona Enter para cerrar...")
    sys.exit(1)

try:
    import speech_recognition as sr
except ImportError:
    print("ERROR: Falta 'SpeechRecognition'. Ejecuta instalar.bat primero.")
    input("Presiona Enter para cerrar...")
    sys.exit(1)

# ─── Actualizaciones ─────────────────────────────────────────────────────────
# Verificar antes de todo — si hay update, el usuario elige y el exe se reemplaza.
try:
    from updater import check_and_show_update
    check_and_show_update()
except Exception:
    pass   # sin internet o cualquier error → continuar normal

# ─── Configuración ────────────────────────────────────────────────────────────
from config_manager import config_exists, load_config, save_config
from setup_gui      import run_setup, run_reconfigure

# Activadores de voz — "rodo" es el principal
ACTIVATOR_NAMES = ("rodo",)

# Primera vez: setup visual automático (SIN overlay activo aún — evita conflicto tkinter)
if not config_exists():
    cfg = run_setup()
    if cfg is None:
        print("Configuracion cancelada. Hasta luego!")
        sys.exit(0)
else:
    cfg = load_config()

# ─── Acceso directo en el escritorio ─────────────────────────────────────────
def _create_desktop_shortcut():
    """Crea acceso directo de Rodo en el escritorio (solo la primera vez)."""
    try:
        if sys.platform != "win32" or not getattr(sys, "frozen", False):
            return  # Solo aplica al exe en Windows
        import subprocess
        exe_path = sys.executable.replace("'", "''")
        work_dir = os.path.dirname(sys.executable).replace("'", "''")
        ps = f"""
$Desktop = [Environment]::GetFolderPath('Desktop')
$Link    = "$Desktop\\Rodo.lnk"
if (-not (Test-Path $Link)) {{
    $ws = New-Object -ComObject WScript.Shell
    $sc = $ws.CreateShortcut($Link)
    $sc.TargetPath       = '{exe_path}'
    $sc.WorkingDirectory = '{work_dir}'
    $sc.IconLocation     = '{exe_path},0'
    $sc.Description      = 'Rodo - Asistente de voz'
    $sc.Save()
    ie4uinit.exe -show
}}
"""
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", ps],
            capture_output=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,  # Sin terminal visible
        )
    except Exception:
        pass  # No es crítico — sigue aunque falle

def _cleanup_stale_meipass():
    """Elimina carpetas _MEI* viejas de PyInstaller en %TEMP% para evitar conflictos."""
    if not getattr(sys, "frozen", False):
        return
    try:
        import glob
        import shutil
        current   = os.path.abspath(sys._MEIPASS)
        temp_base = os.path.dirname(current)
        for folder in glob.glob(os.path.join(temp_base, "_MEI*")):
            if os.path.abspath(folder) != current:
                shutil.rmtree(folder, ignore_errors=True)
    except Exception:
        pass

_cleanup_stale_meipass()
_create_desktop_shortcut()

# Overlay visual de estado — se inicia DESPUÉS del setup para no interferir con tkinter
_overlay = None
def _ov(state: str):
    if _overlay:
        try: _overlay.set_state(state)
        except Exception: pass

try:
    from overlay import StatusOverlay as _OverlayClass
    _overlay = _OverlayClass()
    _overlay.start()
except Exception:
    pass

# Ícono en la bandeja del sistema
try:
    from tray import start_tray
    start_tray(overlay=_overlay)
except Exception:
    pass

NOMBRE               = cfg.get("nombre",                "Amigo")
BOT_API_URL          = cfg.get("api_url",               "").rstrip("/")
BOT_API_TOKEN        = cfg.get("api_token",             "")
DISCORD_ID           = cfg.get("discord_id",            "")
DISCORD_ACCESS_TOKEN = cfg.get("discord_access_token",  "")
DISCORD_REFRESH_TOKEN= cfg.get("discord_refresh_token", "")
DISCORD_TOKEN_EXPIRY = cfg.get("discord_token_expiry",  0)
SPOTIFY_LINKED       = cfg.get("spotify_linked",        False)

# ─── Log de voz ──────────────────────────────────────────────────────────────
import logging
from datetime import datetime

_LOG_DIR  = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Rodo")
_LOG_FILE = os.path.join(_LOG_DIR, "rodo_voice.log")
os.makedirs(_LOG_DIR, exist_ok=True)

logging.basicConfig(
    filename=_LOG_FILE,
    level=logging.DEBUG,
    format="%(asctime)s %(message)s",
    datefmt="%H:%M:%S",
    encoding="utf-8",
)
_vlog = logging.getLogger("rodo.voice")

def vlog(msg: str):
    """Log de voz — va al archivo y a la consola."""
    print(msg)
    _vlog.info(msg)


# ─── Chime de activación ─────────────────────────────────────────────────────

def _chime():
    """
    Tono breve al detectar el activador — feedback inmediato para el usuario.
    Dos notas ascendentes: 660 Hz (60 ms) → 990 Hz (100 ms).
    Corre en hilo daemon → no bloquea el loop de escucha.
    Solo disponible en Windows (winsound); en otros SO, no hace nada.
    """
    try:
        import winsound
        winsound.Beep(660,  60)
        winsound.Beep(990, 100)
    except Exception:
        pass   # winsound no disponible (macOS/Linux) → silencio, sin crash


def _chime_bg():
    """Fire-and-forget: chime en hilo daemon."""
    threading.Thread(target=_chime, daemon=True).start()


# ─── Control multimedia local (teclas de media Windows) ──────────────────────
# Funciona con Spotify app, YouTube en Chrome/Firefox, y cualquier media player.
# ctypes es built-in → sin dependencias extra ni cambios en el spec de PyInstaller.

_VK_MEDIA_NEXT  = 0xB0   # Siguiente pista
_VK_MEDIA_PREV  = 0xB1   # Pista anterior
_VK_MEDIA_STOP  = 0xB2   # Detener
_VK_MEDIA_PLAY  = 0xB3   # Play / Pause (toggle)
_VK_VOL_MUTE    = 0xAD   # Silenciar
_VK_VOL_DOWN    = 0xAE   # Bajar volumen
_VK_VOL_UP      = 0xAF   # Subir volumen

def _send_media_key(vk: int, times: int = 1):
    """
    Simula una tecla multimedia de Windows via keybd_event (sin instalar nada).
    Funciona con Spotify, Chrome/Firefox (YouTube), VLC, etc.
    """
    try:
        import ctypes
        _EXT  = 0x0001   # KEYEVENTF_EXTENDEDKEY
        _UP   = 0x0002   # KEYEVENTF_KEYUP
        kbd   = ctypes.windll.user32.keybd_event
        for _ in range(times):
            kbd(vk, 0, _EXT, 0)       # key down
            kbd(vk, 0, _EXT | _UP, 0) # key up
    except Exception as e:
        vlog(f"[MEDIA KEY] Error: {e}")

def _media_beep(tone: str = "ok"):
    """
    Feedback sonoro discreto para controles multimedia — sin hablar.
    No interrumpe juegos ni conversaciones.
      ok   → 880 Hz breve (acción ejecutada)
      skip → dos tonos rápidos (siguiente/anterior)
      stop → tono descendente (detener)
    """
    try:
        import winsound
        if tone == "skip":
            winsound.Beep(880, 60)
            winsound.Beep(1100, 60)
        elif tone == "stop":
            winsound.Beep(660, 80)
            winsound.Beep(440, 80)
        else:
            winsound.Beep(880, 80)
    except Exception:
        pass

def _local_control(norm_words: set) -> bool:
    """
    Ejecuta el control multimedia local según las palabras del comando.
    Usa beeps cortos como feedback — no habla para no molestar durante juegos.
    Retorna True si se procesó alguna acción, False si no aplica.
    """
    if norm_words & {"siguiente", "salta", "saltar", "skip", "next", "pasa"}:
        _send_media_key(_VK_MEDIA_NEXT)
        threading.Thread(target=_media_beep, args=("skip",), daemon=True).start()
        return True
    if norm_words & {"anterior", "atras", "volver", "previa", "prev"}:
        _send_media_key(_VK_MEDIA_PREV)
        threading.Thread(target=_media_beep, args=("skip",), daemon=True).start()
        return True
    if norm_words & {"pausa", "pausar"}:
        _send_media_key(_VK_MEDIA_PLAY)
        threading.Thread(target=_media_beep, daemon=True).start()
        return True
    if norm_words & {"sigue", "resume", "continua", "continuar", "reanuda", "play"}:
        _send_media_key(_VK_MEDIA_PLAY)
        threading.Thread(target=_media_beep, daemon=True).start()
        return True
    if norm_words & {"para", "stop", "detener", "detiene"}:
        _send_media_key(_VK_MEDIA_STOP)
        threading.Thread(target=_media_beep, args=("stop",), daemon=True).start()
        return True
    if norm_words & {"silencia", "mute", "silencio", "mudo"}:
        _send_media_key(_VK_VOL_MUTE)
        threading.Thread(target=_media_beep, args=("stop",), daemon=True).start()
        return True
    if norm_words & {"sube", "subir", "aumenta"}:
        _send_media_key(_VK_VOL_UP, times=5)
        threading.Thread(target=_media_beep, daemon=True).start()
        return True
    if norm_words & {"baja", "bajar", "menos"}:
        _send_media_key(_VK_VOL_DOWN, times=5)
        threading.Thread(target=_media_beep, daemon=True).start()
        return True
    return False


# ─── TTS local (Windows SAPI — sin dependencias extra) ───────────────────────

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

def _speak_local(text: str):
    """Reproduce texto por los parlantes del usuario vía Windows TTS (bloqueante)."""
    try:
        safe = text.replace("'", "").replace('"', "")
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
             "-Command",
             f"Add-Type -AssemblyName System.Speech; "
             f"$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
             f"$s.Rate = 1; $s.Speak('{safe}')"],
            timeout=15,
            creationflags=_NO_WINDOW,
        )
    except Exception as e:
        vlog(f"[TTS LOCAL] Error: {e}")


def _speak_local_bg(text: str):
    """Fire-and-forget: TTS en hilo daemon — no bloquea el loop de escucha."""
    threading.Thread(target=_speak_local, args=(text,), daemon=True).start()


# ─── Detección de comandos de música ─────────────────────────────────────────

_MUSIC_VERBS = {
    "pon", "pone", "ponme", "ponle", "ponele",
    "reproduce", "reproduceme", "play",
    "coloca", "colocame", "echa", "echame",
    "tira", "tirame", "dame", "escucha", "escuchemos",
}

def _is_music_command(text: str) -> bool:
    """Detecta si el texto parece un comando de música (pon X, reproduce X, etc.)."""
    norm = normalize(text)
    for name in ACTIVATOR_NAMES:
        norm = re.sub(rf"\b{name}\b", "", norm).strip()
    words = set(norm.split())
    return bool(words & _MUSIC_VERBS)


# ─── Contexto Discord ─────────────────────────────────────────────────────────

def _check_context() -> dict:
    """
    Pregunta al bot si hay humanos en canales de voz.
    Rápido: <50ms en red local, <300ms via ngrok.
    """
    try:
        r = requests.get(
            f"{BOT_API_URL}/context",
            params={"discord_id": DISCORD_ID} if DISCORD_ID else None,
            headers={"Authorization": f"Bearer {BOT_API_TOKEN}"},
            timeout=3,
        )
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        vlog(f"[CONTEXT] Error: {e}")
    return {"in_discord": False, "channel": None, "members": []}


def _listen_yesno(recognizer, mic, timeout: float = 8.0) -> bool | None:
    """
    Escucha una respuesta sí/no del usuario.
    Retorna: True=sí, False=no, None=sin respuesta/timeout.
    """
    try:
        with mic as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.2)
            audio = recognizer.listen(source, timeout=timeout, phrase_time_limit=5)
        answer = recognizer.recognize_google(audio, language="es-ES").lower().strip()
        vlog(f"[YESNO] Respuesta: '{answer}'")
        if any(w in answer for w in ["sí", "si", "yes", "claro", "dale", "ok",
                                      "bueno", "obvio", "anda", "venga", "úne", "adelante"]):
            return True
        if any(w in answer for w in ["no", "nope", "nel", "nah", "negativo", "tampoco"]):
            return False
    except sr.WaitTimeoutError:
        vlog("[YESNO] Timeout — sin respuesta")
    except sr.UnknownValueError:
        vlog("[YESNO] No se entendió la respuesta")
    except Exception as e:
        vlog(f"[YESNO] Error: {e}")
    return None


def _get_status() -> dict:
    """Consulta el estado actual del reproductor en Discord."""
    try:
        r = requests.get(
            f"{BOT_API_URL}/status",
            headers={"Authorization": f"Bearer {BOT_API_TOKEN}"},
            timeout=3,
        )
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        vlog(f"[STATUS] Error: {e}")
    return {}


def _refresh_spotify_status() -> bool:
    """Consulta al bot si este usuario tiene Spotify vinculado."""
    global SPOTIFY_LINKED
    try:
        r = requests.get(
            f"{BOT_API_URL}/me/spotify_status",
            headers={"Authorization": f"Bearer {BOT_API_TOKEN}"},
            timeout=5,
        )
        if r.status_code == 200:
            data = r.json()
            linked = bool(data.get("linked"))
            SPOTIFY_LINKED = linked
            cfg["spotify_linked"] = linked
            save_config(cfg)
            _orch.set_spotify_linked(linked)
            return linked
    except Exception as e:
        vlog(f"[SPOTIFY_STATUS] Error: {e}")
    _orch.set_spotify_linked(bool(SPOTIFY_LINKED))
    return bool(SPOTIFY_LINKED)


def _stop_discord():
    """Para la música en Discord sin desconectar el bot."""
    try:
        requests.post(
            f"{BOT_API_URL}/stop",
            headers={"Authorization": f"Bearer {BOT_API_TOKEN}"},
            timeout=5,
        )
    except Exception:
        pass


def _disconnect_discord():
    """Desconecta el bot del canal de voz."""
    try:
        requests.post(
            f"{BOT_API_URL}/disconnect",
            headers={"Authorization": f"Bearer {BOT_API_TOKEN}"},
            timeout=5,
        )
    except Exception:
        pass


_DISCORD_APP_ID = "1436538353309978786"


def _detect_discord_identity() -> dict | None:
    """
    Primera vez: muestra popup en Discord para vincular la cuenta.
    Pide scopes 'identify' + 'rpc' (rpc permite consultar canal de voz en tiempo real).
    Si Discord no soporta rpc para esta app, reintenta solo con 'identify'.
    Guarda access_token + refresh_token + user_id en config.
    """
    try:
        from pypresence import Client as _RpcClient
    except ImportError:
        vlog("[DISCORD RPC] pypresence no instalado — saltando detección")
        return None

    for scopes in (["identify", "rpc"], ["identify"]):
        try:
            vlog(f"[DISCORD RPC] Conectando (scopes={scopes})...")
            rpc = _RpcClient(client_id=_DISCORD_APP_ID)
            rpc.start()
            auth = rpc.authorize(client_id=_DISCORD_APP_ID, scopes=scopes)
            code = auth["data"]["code"]
            rpc.close()

            r = requests.post(
                f"{BOT_API_URL}/discord_auth",
                json={"code": code},
                headers={"Authorization": f"Bearer {BOT_API_TOKEN}"},
                timeout=15,
            )
            if r.status_code == 200:
                data = r.json()
                if data.get("ok"):
                    data["rpc_scope"] = "rpc" in scopes
                    vlog(f"[DISCORD RPC] ✓ {data.get('display_name')} (ID {data.get('user_id')}) "
                         f"| rpc={'rpc' in scopes}")
                    return data
                vlog(f"[DISCORD RPC] Error del bot: {data.get('error')}")
            else:
                vlog(f"[DISCORD RPC] HTTP {r.status_code}: {r.text[:120]}")
            break   # Si el code ya fue consumido, no reintentar
        except Exception as e:
            vlog(f"[DISCORD RPC] Error con scopes={scopes}: {e}")
            if "rpc" not in scopes:
                break  # Ya probamos el fallback, rendirse
    return None


def _get_valid_discord_token() -> str:
    """
    Devuelve un access_token válido.
    Si está por vencer, lo renueva automáticamente via /discord_refresh del bot.
    """
    global DISCORD_ACCESS_TOKEN, DISCORD_REFRESH_TOKEN, DISCORD_TOKEN_EXPIRY
    if not DISCORD_ACCESS_TOKEN:
        return ""
    # Refrescar si faltan menos de 5 minutos para que expire
    if time.time() < DISCORD_TOKEN_EXPIRY - 300:
        return DISCORD_ACCESS_TOKEN
    if not DISCORD_REFRESH_TOKEN:
        return ""
    try:
        vlog("[TOKEN] Access token por vencer — renovando...")
        r = requests.post(
            f"{BOT_API_URL}/discord_refresh",
            json={"refresh_token": DISCORD_REFRESH_TOKEN},
            headers={"Authorization": f"Bearer {BOT_API_TOKEN}"},
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            if data.get("ok"):
                DISCORD_ACCESS_TOKEN  = data["access_token"]
                DISCORD_REFRESH_TOKEN = data["refresh_token"]
                DISCORD_TOKEN_EXPIRY  = data["expires_at"]
                cfg["discord_access_token"]  = DISCORD_ACCESS_TOKEN
                cfg["discord_refresh_token"] = DISCORD_REFRESH_TOKEN
                cfg["discord_token_expiry"]  = DISCORD_TOKEN_EXPIRY
                save_config(cfg)
                vlog("[TOKEN] ✓ Token renovado")
                return DISCORD_ACCESS_TOKEN
    except Exception as e:
        vlog(f"[TOKEN] Error renovando: {e}")
    return DISCORD_ACCESS_TOKEN   # Usar el viejo, puede que aún funcione


def _spotify_oauth_flow() -> bool:
    """
    Inicia el flujo OAuth de Spotify en el navegador del usuario y captura el callback.

    Flujo:
      1. Pide al bot la URL de autorización (GET /spotify_oauth_url).
      2. Abre el navegador con esa URL.
      3. Levanta un servidor HTTP mínimo en localhost:<callback_port>/callback.
      4. Espera el código (timeout 120 s) — el usuario acepta en el navegador.
      5. Envía el código al bot (POST /spotify_user_auth).
      6. Si ok → guarda spotify_linked=True en config.

    Retorna True si el vinculo fue exitoso, False en cualquier error.
    """
    global SPOTIFY_LINKED

    if not BOT_API_URL:
        vlog("[SPOTIFY_OAUTH] Sin API URL configurada — no se puede iniciar")
        return False

    # 1. Obtener la URL de autorización y el puerto del callback
    try:
        r = requests.get(
            f"{BOT_API_URL}/spotify_oauth_url",
            headers={"Authorization": f"Bearer {BOT_API_TOKEN}"},
            timeout=10,
        )
        data = r.json()
        if not data.get("ok"):
            vlog(f"[SPOTIFY_OAUTH] Error obteniendo URL: {data.get('error')}")
            _speak_local_bg("No pude conectarme a Spotify. Revisá la configuración del bot.")
            return False
        auth_url      = data["url"]
        callback_port = data.get("callback_port", 8888)
        callback_host = data.get("callback_host", "127.0.0.1")
    except Exception as e:
        vlog(f"[SPOTIFY_OAUTH] Error en GET /spotify_oauth_url: {e}")
        _speak_local_bg("No pude conectarme al servidor. Intentá más tarde.")
        return False

    # 2. Abrir el navegador
    import webbrowser
    vlog(f"[SPOTIFY_OAUTH] Abriendo navegador → {auth_url[:80]}...")
    _speak_local_bg(
        "Abrí el navegador para que inicies sesión en Spotify. "
        "Aceptá los permisos y volvé acá."
    )
    try:
        webbrowser.open(auth_url)
    except Exception as e:
        vlog(f"[SPOTIFY_OAUTH] No pude abrir el navegador: {e}")

    # 3. Servidor local para capturar el callback
    import http.server
    import urllib.parse
    import threading as _threading

    _result = {"code": None, "state": None, "error": None}
    _done   = _threading.Event()

    class _CallbackHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == "/callback":
                params = urllib.parse.parse_qs(parsed.query)
                _result["code"]  = (params.get("code",  [""])[0])
                _result["state"] = (params.get("state", [""])[0])
                _result["error"] = (params.get("error", [""])[0])
                body = b"<html><body><h2>Listo! Podes cerrar esta pestana.</h2></body></html>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                _done.set()
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, *args):
            pass   # silenciar logs de acceso del servidor

    try:
        server = http.server.HTTPServer((callback_host, callback_port), _CallbackHandler)
    except OSError as e:
        vlog(f"[SPOTIFY_OAUTH] No pude abrir puerto {callback_port}: {e}")
        _speak_local_bg(f"El puerto {callback_port} ya está en uso. Cerrá otras aplicaciones e intentá de nuevo.")
        return False

    def _serve():
        server.handle_request()   # Un solo request — el callback de Spotify

    _threading.Thread(target=_serve, daemon=True).start()

    # 4. Esperar el callback (máx. 120 s)
    vlog(f"[SPOTIFY_OAUTH] Esperando callback en {callback_host}:{callback_port}/callback ...")
    if not _done.wait(timeout=120):
        server.server_close()
        vlog("[SPOTIFY_OAUTH] Timeout — el usuario no completó el flujo en 2 min")
        _speak_local_bg("Se agotó el tiempo. Si querés vincular Spotify, decí 'Rodo vincula mi Spotify'.")
        return False

    server.server_close()

    code  = _result.get("code",  "")
    state = _result.get("state", "")
    err   = _result.get("error", "")

    if err or not code:
        vlog(f"[SPOTIFY_OAUTH] Callback con error: '{err}' — sin código")
        _speak_local_bg("Hubo un error al vincular Spotify. Intentá de nuevo.")
        return False

    vlog(f"[SPOTIFY_OAUTH] Código recibido (state={state}) — enviando al bot...")

    # 5. Intercambiar el código en el bot
    try:
        r2 = requests.post(
            f"{BOT_API_URL}/spotify_user_auth",
            json={"code": code, "state": state},
            headers={"Authorization": f"Bearer {BOT_API_TOKEN}"},
            timeout=15,
        )
        data2 = r2.json()
        if not data2.get("ok"):
            vlog(f"[SPOTIFY_OAUTH] Bot rechazó el código: {data2.get('error')}")
            _speak_local_bg("Spotify rechazó el código. Intentá vincular de nuevo.")
            return False
    except Exception as e:
        vlog(f"[SPOTIFY_OAUTH] Error en POST /spotify_user_auth: {e}")
        _speak_local_bg("No pude comunicarme con el servidor al vincular Spotify.")
        return False

    # 6. Guardar en config local
    SPOTIFY_LINKED      = True
    cfg["spotify_linked"] = True
    save_config(cfg)
    _orch.set_spotify_linked(True)
    _refresh_spotify_status()
    vlog("[SPOTIFY_OAUTH] ✓ Spotify vinculado correctamente")
    _speak_local_bg("¡Listo! Tu Spotify quedó vinculado. Ya podés pedir tus canciones guardadas.")
    return True


def _is_discord_running() -> bool:
    """
    Detecta si Discord está abierto intentando conectarse a su IPC local.
    pypresence usa el pipe de Discord (~1ms si está abierto, falla al instante si no).
    No muestra ningún popup — solo verifica la conexión.
    """
    try:
        from pypresence import Client as _RpcClient
        rpc = _RpcClient(client_id=_DISCORD_APP_ID)
        rpc.start()
        rpc.close()
        return True
    except Exception:
        return False


def _is_spotify_installed() -> bool:
    """
    Detecta si Spotify está instalado en Windows.
    Revisa las rutas comunes del exe:
    - %APPDATA%\\Spotify          → instalación clásica (usuario)
    - %LOCALAPPDATA%\\Microsoft\\WindowsApps  → Microsoft Store (stub .exe)
    - Program Files               → instalación global
    Fallbacks: registro de Windows + proceso corriendo.
    """
    import os
    paths = [
        os.path.join(os.environ.get("APPDATA",      ""), "Spotify", "Spotify.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WindowsApps", "Spotify.exe"),
        r"C:\Program Files\Spotify\Spotify.exe",
        r"C:\Program Files (x86)\Spotify\Spotify.exe",
    ]
    if any(os.path.exists(p) for p in paths):
        return True
    # Fallback 1: clave clásica de instalador Spotify
    try:
        import winreg
        winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Spotify")
        return True
    except Exception:
        pass
    # Fallback 2: handler spotify:// URI registrado por la Store
    try:
        import winreg
        winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\spotify")
        return True
    except Exception:
        pass
    # Fallback 3: proceso corriendo en este momento
    try:
        out = subprocess.check_output(
            ["tasklist", "/FI", "IMAGENAME eq Spotify.exe", "/NH"],
            creationflags=_NO_WINDOW,
            timeout=3,
        ).decode(errors="ignore")
        if "Spotify.exe" in out:
            return True
    except Exception:
        pass
    return False


def _build_rpc_client():
    """
    Crea un cliente RPC autenticado con el token almacenado.
    Retorna el cliente listo para usar, o None si no se puede.
    """
    try:
        from pypresence import Client as _RpcClient
    except ImportError:
        return None

    token = _get_valid_discord_token()
    if not token:
        return None
    try:
        rpc = _RpcClient(client_id=_DISCORD_APP_ID)
        rpc.start()
        rpc.authenticate(token)
        vlog("[DISCORD RPC] Cliente autenticado via token guardado")
        return rpc
    except Exception as e:
        vlog(f"[DISCORD RPC] Error autenticando: {e}")
        return None


def _disconnect_me_from_discord() -> bool:
    """
    Desconecta al usuario actual del canal de voz de Discord.
    Usa /move con channel_name vacío → member.move_to(None).
    Si DISCORD_ID está guardado, el lookup es directo y 100% confiable.
    Requiere permiso Move Members en el bot.
    """
    try:
        r = requests.post(
            f"{BOT_API_URL}/move",
            json={
                "target":       "member",
                "channel_name": "",
                "member_name":  NOMBRE,
                "discord_id":   DISCORD_ID,   # lookup directo si está disponible
            },
            headers={"Authorization": f"Bearer {BOT_API_TOKEN}"},
            timeout=5,
        )
        data = r.json()
        ok   = data.get("ok", False)
        if not ok:
            vlog(f"[KICK] No se pudo desconectar: {data.get('errors', data)}")
        return ok
    except Exception as e:
        vlog(f"[KICK] Error: {e}")
    return False


def _move_discord(target: str, channel_name: str) -> dict:
    """Mueve bot, miembro o ambos a un canal de voz."""
    try:
        r = requests.post(
            f"{BOT_API_URL}/move",
            json={
                "target":       target,
                "channel_name": channel_name,
                "member_name":  NOMBRE,
                "discord_id":   DISCORD_ID,   # lookup directo si está disponible
            },
            headers={"Authorization": f"Bearer {BOT_API_TOKEN}"},
            timeout=5,
        )
        data = r.json()
        if r.status_code != 200:
            vlog(f"[MOVE] HTTP {r.status_code}: {data.get('error', data)}")
        return data
    except Exception as e:
        vlog(f"[MOVE] Error: {e}")
    return {"ok": False, "errors": []}


def _extract_channel_name(norm_cmd: str, keywords: list = None) -> str:
    """
    Extrae el nombre del canal de comandos como:
      "muévete al General"      → "general"
      "vamos al canal de juegos" → "canal de juegos"
      "llévame a estudio"        → "estudio"
    Busca el patrón "al/a/hacia [nombre]" en el texto.
    """
    m = re.search(r"\b(?:al|a\s+el?|hacia\s+(?:el?|la)?)\s+(.+)$", norm_cmd)
    if m:
        return m.group(1).strip()
    return ""


def _ask_discord_preference(recognizer, mic, channel: str = "el canal") -> bool | None:
    """
    Pregunta por voz si el usuario quiere unirse a Discord.
    Retorna: True=Discord, False=local, None=sin respuesta (asumir Discord).
    """
    _speak_local(f"Te veo en Discord en {channel}. ¿Quieres que me una al canal?")
    return _listen_yesno(recognizer, mic)


# ─── Envío al servidor ────────────────────────────────────────────────────────

def _send_command_full(text: str) -> dict:
    """
    Envía el comando al servidor y devuelve el JSON completo de la respuesta.
    Retorna {"ok": False} en caso de error de red o HTTP.
    """
    try:
        r = requests.post(
            f"{BOT_API_URL}/command",
            json={"text": text, "user": NOMBRE, "discord_id": DISCORD_ID},
            headers={"Authorization": f"Bearer {BOT_API_TOKEN}"},
            timeout=10,
        )
        if r.status_code == 200:
            return r.json()
        if r.status_code == 401:
            print("[ERROR] Contrasena incorrecta — pide al dueno los datos actualizados")
            return {"ok": False, "status_code": 401, "error": "unauthorized"}
        # Intentar parsear el cuerpo del error para mensajes útiles
        try:
            err_body = r.json()
        except Exception:
            err_body = {}
        return {"ok": False, "status_code": r.status_code, **err_body}
    except requests.ConnectionError:
        print(f"[ERROR] No se pudo conectar a {BOT_API_URL}")
        return {"ok": False, "error": "connection_error"}
    except Exception as e:
        print(f"[ERROR] {e}")
        return {"ok": False, "error": str(e)}


def send_command(text: str) -> bool:
    """Envía el comando al servidor de Rodo via API. Wrapper de compatibilidad."""
    return _send_command_full(text).get("ok", False)


# ─── Detección del activador ──────────────────────────────────────────────────

def _open_local_playback(text: str, prefix: str = "Abriendo") -> bool:
    """Pide al bot resolver Spotify/YouTube y abre el resultado en esta PC."""
    import webbrowser as _wb

    try:
        lr = requests.post(
            f"{BOT_API_URL}/command",
            json={
                "text": text,
                "user": NOMBRE,
                "discord_id": DISCORD_ID,
                "local": True,
            },
            headers={"Authorization": f"Bearer {BOT_API_TOKEN}"},
            timeout=15,
        )
        result = lr.json() if lr.status_code == 200 else {}
    except Exception as exc:
        vlog(f"  -> [LOCAL] Error de red: {exc}")
        result = {}

    if result.get("need_spotify_auth"):
        threading.Thread(target=_spotify_oauth_flow, daemon=True).start()
        return False

    if result.get("ok"):
        title = result.get("title", "la canciÃ³n")
        mode = result.get("mode", "youtube")
        if mode == "spotify":
            _wb.open(result["spotify_uri"])
            vlog(f"  -> [LOCAL] Spotify abierto: '{title}'\n")
            _speak_local_bg(f"{prefix} {title} en Spotify.")
        else:
            _wb.open(result["webpage_url"])
            vlog(f"  -> [LOCAL] YouTube abierto: '{title}'\n")
            _speak_local_bg(f"{prefix} {title} en YouTube.")
        _ov("ok")
        return True

    vlog(f"  -> [LOCAL] Sin resultado: {result}\n")
    _speak_local_bg("No encontrÃ© esa canciÃ³n. IntentÃ¡ de nuevo.")
    _ov("error")
    return False


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return text.lower().strip()


def has_activator(text: str) -> bool:
    norm = normalize(text)
    # Usar word boundary para no detectar "rodo" dentro de "rodolfo"
    return any(re.search(rf"\b{name}\b", norm) for name in ACTIVATOR_NAMES)


# ─── Principal ────────────────────────────────────────────────────────────────

def _start_voice_monitor(orch, poll_interval: float = 5.0):
    """
    Hilo de fondo — monitorea si el usuario sigue en Discord.

    Intenta usar Discord RPC local (instantáneo via eventos).
    Si no está disponible (amigos sin scope rpc), cae a polling del bot cada N segundos.

    Delega la lógica de estado al orquestador (orch.on_enter_voice / on_exit_voice).
    """
    def _on_exit():
        """Llamado cuando el usuario sale de un canal de voz."""
        should_announce = orch.on_exit_voice()
        if should_announce:
            vlog("[MONITOR] Saliste del canal de voz → modo local")
            _speak_local_bg("Saliste de Discord. Cambié a modo local.")

    def _on_enter(channel: str = None):
        """Llamado cuando el usuario entra a un canal de voz."""
        should_announce = orch.on_enter_voice(channel)
        if should_announce:
            vlog("[MONITOR] Entraste a Discord desde modo local → modo reseteado")

    def _rpc_loop():
        """Usa eventos RPC — instantáneo, sin polling."""
        rpc = _build_rpc_client()
        if not rpc:
            return False   # Señal: usar fallback

        try:
            rpc.subscribe("VOICE_CHANNEL_SELECT")
            vlog("[MONITOR] ✓ Subscrito a VOICE_CHANNEL_SELECT via RPC local")
        except Exception as e:
            vlog(f"[MONITOR] RPC error al subscribir: {e}")
            return True   # Era RPC pero falló al subscribir → fallback

        while True:
            try:
                msg = rpc.read()
                if not msg:
                    continue
                if msg.get("evt") == "VOICE_CHANNEL_SELECT":
                    _data      = msg.get("data") or {}
                    channel_id = _data.get("channel_id")
                    if channel_id:
                        _on_enter(_data.get("channel_name"))
                    else:
                        _on_exit()
            except Exception as e:
                err_str = str(e).lower()
                # "No response was received from the pipe in time" — timeout normal
                # cuando no llegan eventos. No es un error real, seguir esperando.
                if "no response" in err_str or "timed out" in err_str:
                    continue
                # Error real: Discord cerrado ("Broken pipe", "connection reset", etc.)
                vlog(f"[MONITOR] RPC desconectado: {e}")
                break

        return True   # Señal: era RPC pero se cayó → fallback a polling

    def _polling_loop():
        """Fallback para usuarios sin scope rpc — pregunta al bot cada N segundos."""
        vlog(f"[MONITOR] Usando polling cada {poll_interval}s (sin RPC scope)")
        while True:
            time.sleep(poll_interval)
            try:
                mode = orch.state.discord_mode
                if mode is None:
                    continue  # Aún sin decidir — nada que monitorear
                ctx = _check_context()
                if ctx.get("in_discord"):
                    _on_enter(ctx.get("channel"))
                else:
                    _on_exit()
            except Exception as e:
                vlog(f"[MONITOR] Error polling: {e}")

    def _run():
        # Intentar RPC primero; si falla, usar polling
        if DISCORD_ACCESS_TOKEN:
            _rpc_loop()   # Bloquea hasta que se desconecte
        _polling_loop()   # Fallback permanente

    t = threading.Thread(target=_run, daemon=True, name="voice-monitor")
    t.start()
    return t


def main():
    print()
    print("╔════════════════════════════════════════════╗")
    print("║           🎤  Rodo  — Companion            ║")
    print("╠════════════════════════════════════════════╣")
    print(f"║  Hola, {NOMBRE:<35s} ║")
    print("║  Di 'Rodo pon [cancion]' para empezar      ║")
    print("║  Ctrl+C para salir                         ║")
    print("╚════════════════════════════════════════════╝")
    print()

    recognizer = sr.Recognizer()

    try:
        mic = sr.Microphone()
    except (OSError, AttributeError):
        print("ERROR: No se detecto microfono.")
        print("Conecta un microfono y vuelve a abrir Rodo.")
        input("Presiona Enter para cerrar...")
        return

    print("[INIT] Calibrando microfono...")
    with mic as source:
        recognizer.adjust_for_ambient_noise(source, duration=1.5)
    print("[INIT] Listo! Empieza a hablar.\n")

    print("Ejemplos de comandos:")
    print("  Rodo pon despacito")
    print("  Rodo siguiente")
    print("  Rodo pausa / sigue")
    print("  Rodo que esta sonando")
    print("  Rodo para la musica")
    print()

    # ── Bienvenida para usuarios nuevos (flujo secuencial, paso a paso) ─────────
    #
    # Se ejecuta UNA SOLA VEZ si falta discord_rpc_tried O spotify_offered.
    # Orden: Discord primero → Spotify → listo.
    # Cada paso es bloqueante y tiene su propio sí/no para que el usuario
    # no reciba dos preguntas al mismo tiempo.
    #
    global DISCORD_ID, DISCORD_ACCESS_TOKEN, DISCORD_REFRESH_TOKEN, DISCORD_TOKEN_EXPIRY

    is_first_time = (
        not cfg.get("discord_rpc_tried", False) or
        not cfg.get("spotify_offered",   False)
    )

    if is_first_time and BOT_API_URL:
        _onb_rec = sr.Recognizer()
        _onb_mic = sr.Microphone()
        with _onb_mic as _src:
            _onb_rec.adjust_for_ambient_noise(_src, duration=0.5)

        # ── PASO 1: Discord (detección automática, sin preguntar) ───────────
        if not cfg.get("discord_rpc_tried", False):
            cfg["discord_rpc_tried"] = True
            save_config(cfg)

            vlog("[ONBOARDING] Detectando si Discord está abierto...")
            _speak_local(f"Hola {NOMBRE}! Soy Rodo. Hacemos una configuración rápida.")

            if _is_discord_running():
                vlog("[ONBOARDING] Discord detectado — vinculando...")
                _speak_local("Detecté que tenés Discord abierto. Voy a conectar tu cuenta. Aceptá el popup que aparece.")
                _identity = _detect_discord_identity()
                if _identity:
                    DISCORD_ID            = _identity.get("user_id",        "")
                    DISCORD_ACCESS_TOKEN  = _identity.get("access_token",   "")
                    DISCORD_REFRESH_TOKEN = _identity.get("refresh_token",  "")
                    DISCORD_TOKEN_EXPIRY  = _identity.get("expires_at",     0)
                    cfg["discord_id"]             = DISCORD_ID
                    cfg["discord_access_token"]   = DISCORD_ACCESS_TOKEN
                    cfg["discord_refresh_token"]  = DISCORD_REFRESH_TOKEN
                    cfg["discord_token_expiry"]   = DISCORD_TOKEN_EXPIRY
                    save_config(cfg)
                    _speak_local(f"Listo, te reconocí como {_identity.get('display_name', NOMBRE)}.")
                    vlog(f"[ONBOARDING] Discord vinculado: {_identity.get('display_name')} ({DISCORD_ID})")
                else:
                    _speak_local("No pude conectarme. Decí Rodo vincula mi Discord cuando quieras.")
                    vlog("[ONBOARDING] Discord abierto pero falló el vínculo")
            else:
                vlog("[ONBOARDING] Discord no detectado — saltando")
                _speak_local("No detecté Discord abierto. Si lo usás, abrilo y decí Rodo vincula mi Discord.")

        # ── PASO 2: Spotify (detectar instalación, preguntar Premium) ────────
        if not cfg.get("spotify_offered", False):
            cfg["spotify_offered"] = True
            save_config(cfg)

            vlog("[ONBOARDING] Detectando si Spotify está instalado...")

            if _is_spotify_installed():
                vlog("[ONBOARDING] Spotify instalado — preguntando Premium...")
                _speak_local("Detecté que tenés Spotify instalado. ¿Sos usuario Premium? Di sí o no.")
                _ans_premium = _listen_yesno(_onb_rec, _onb_mic, timeout=10)

                if _ans_premium is True:
                    _speak_local(
                        "Excelente. Voy a abrir el navegador para conectar tu cuenta de Spotify. "
                        "Iniciá sesión y aceptá los permisos."
                    )
                    vlog("[ONBOARDING] Usuario Premium — iniciando OAuth Spotify")
                    _spotify_oauth_flow()
                else:
                    _speak_local(
                        "Sin problema. Cuando pidas música voy a abrir Spotify en tu pantalla. "
                        "También tengo YouTube como alternativa."
                    )
                    vlog("[ONBOARDING] Usuario Free — Spotify app + YouTube fallback")
            else:
                vlog("[ONBOARDING] Spotify no instalado — usando YouTube")
                _speak_local("No detecté Spotify instalado. Voy a usar YouTube para reproducir música.")

        # ── FIN del onboarding ───────────────────────────────────────────────
        _speak_local(
            "¡Todo listo! Ya podés usarme. Decí Rodo, pon una canción para empezar."
        )
        vlog("[ONBOARDING] Configuración inicial completada")

    last_activator_time = 0.0
    ACTIVATOR_TIMEOUT   = 6.0   # segundos de ventana tras decir solo "Rodo"

    # Estado centralizado en el orquestador
    # discord_mode: None = sin decidir, True = Discord, False = local
    # _session apunta a _orch.state que soporta acceso tipo dict
    # para compatibilidad con todo el código existente.
    _session = _orch.state
    _orch.set_spotify_linked(bool(SPOTIFY_LINKED))
    if BOT_API_URL:
        _refresh_spotify_status()
        _start_voice_monitor(_orch, poll_interval=5.0)
        vlog("[MONITOR] Hilo de monitoreo de voz activo (cada 5s)")

    while True:
        try:
            with mic as source:
                recognizer.adjust_for_ambient_noise(source, duration=0.2)
                # Si hay ruido de fondo (música de Discord, TV, etc.) el umbral sube
                # tanto que Rodo deja de detectar la voz del usuario.
                # Lo capeamos en 3 500 — suficiente para ignorar silencio de fondo,
                # sin que una canción en los parlantes apague el micrófono.
                if recognizer.energy_threshold > 3500:
                    recognizer.energy_threshold = 3500
                _ov("listening")
                print("[ESCUCHO] ", end="", flush=True)
                audio = recognizer.listen(source, timeout=10, phrase_time_limit=7)

            # Transcribir con Google STT
            _ov("processing")
            try:
                old_timeout = socket.getdefaulttimeout()
                socket.setdefaulttimeout(3.0)
                try:
                    text = recognizer.recognize_google(audio, language="es-ES").strip()
                finally:
                    socket.setdefaulttimeout(old_timeout)
            except sr.UnknownValueError:
                vlog("(nada — STT no entendió)")
                _ov("idle")
                continue
            except sr.RequestError as e:
                vlog(f"(error STT: {e})")
                _ov("error")
                time.sleep(1)
                continue

            # Corregir errores frecuentes del STT antes de cualquier procesamiento
            # "Rodolfo" es la transcripción más común cuando se dice "Rodo"
            text = re.sub(r"\bRodolfo\b", "Rodo", text, flags=re.IGNORECASE)
            # "rodo" con tilde ("rodó") también ocurre — normalize() lo limpia,
            # pero lo corregimos aquí para que vlog muestre el texto ya limpio
            text = re.sub(r"\brod[oó]\b", "Rodo", text, flags=re.IGNORECASE)

            vlog(f"[ESCUCHÉ] '{text}'")

            # ¿Contiene el activador?
            contains_act = has_activator(text)

            if contains_act:
                # Quitar el activador para ver qué queda
                norm_text  = normalize(text)
                clean_norm = norm_text
                for name in ACTIVATOR_NAMES:
                    clean_norm = re.sub(rf"\b{name}\b", "", clean_norm)
                clean_norm = clean_norm.strip()

                if not clean_norm:
                    # Solo dijo "Rodo" — abrir ventana de 6s para el siguiente comando
                    # "dime" le indica al usuario que Rodo está esperando el comando
                    _speak_local_bg("dime")
                    last_activator_time = time.time()
                    vlog(f"  -> [ACTIVADOR] Escuchando comando ({ACTIVATOR_TIMEOUT:.0f}s)...")
                    continue
                else:
                    last_activator_time = 0.0
            else:
                # Sin activador — ¿hay ventana activa?
                if time.time() - last_activator_time < ACTIVATOR_TIMEOUT:
                    text = f"Rodo {text}"
                    vlog(f"  -> [VENTANA] completado → '{text}'")
                    last_activator_time = 0.0
                else:
                    vlog(f"  -> [IGNORADO] sin activador (STT escuchó pero no dijo 'rodo')")
                    last_activator_time = 0.0
                    continue

            # ── Comandos locales (no van al servidor) ────────────────────────
            norm_cmd = normalize(text)
            # Quitar activador para revisar el comando limpio
            for name in ACTIVATOR_NAMES:
                norm_cmd = re.sub(rf"\b{name}\b", "", norm_cmd).strip()

            if any(w in norm_cmd for w in [
                "ocultate", "oculta", "escondete", "esconde",
                "sal de mi pantalla", "sal de la pantalla",
                "quitate de la pantalla", "quitate", "desaparece",
                "vete de la pantalla",
            ]):
                print("  -> [LOCAL] Ocultando overlay\n")
                if _overlay: _overlay.hide()
                _ov("idle")
                continue

            if any(w in norm_cmd for w in [
                "muestrate", "muestra", "aparece", "donde estas",
                "donde te fuiste", "vuelve a aparecer",
                "aparece en pantalla",
            ]):
                print("  -> [LOCAL] Mostrando overlay\n")
                if _overlay: _overlay.show()
                _ov("ok")
                continue

            # ── Modo Discord explícito ────────────────────────────────────────
            # Detección flexible por palabras clave (aguanta variaciones de STT)
            _norm_words = set(norm_cmd.split())
            _discord_enter = {"entra", "entro", "entrar", "une", "unete", "conecta",
                              "conectate", "conecto", "junta", "activa", "activate"}
            # "sal de Discord" → el BOT sale (vos seguís en Discord si querés)
            _discord_bot_exit = {"sal", "sale", "salte", "sali", "salir",
                                 "desconecta", "desconectate", "desconecto",
                                 "fuera", "salgamos", "vete", "alejate"}
            # "sácame de Discord" → el USUARIO sale (el bot puede quedarse)
            _discord_user_exit = {"sacame", "saca", "quitame", "quita",
                                  "botame", "bota", "sacanos", "saquenos",
                                  "desconectame", "desconectarme"}

            # "disco" = STT mal transcribiendo "discord" (ej: "sácame de disco")
            # Solo aplica cuando hay palabras de comando, para evitar falsos positivos
            _all_discord_words = _discord_bot_exit | _discord_user_exit | _discord_enter
            _is_discord_ref = (
                "discord" in norm_cmd or "discor" in norm_cmd
                or ("disco" in norm_cmd and bool(_norm_words & _all_discord_words))
            )

            if _is_discord_ref and \
               (_norm_words & _discord_enter):
                _session["discord_mode"] = True
                vlog("  -> [MODO] Discord activado explícitamente\n")
                _speak_local_bg("Modo Discord activado.")
                _ov("ok")
                continue

            # BOT sale de Discord
            if _is_discord_ref and (_norm_words & _discord_bot_exit):
                _stop_discord()
                _disconnect_discord()
                _session["discord_mode"] = False
                vlog("  -> [MODO] Bot desconectado de Discord\n")
                _speak_local_bg("Salí de Discord. La música se detuvo.")
                _ov("ok")
                continue

            # USUARIO sale de Discord (bot puede quedarse si hay más gente)
            if _is_discord_ref and (_norm_words & _discord_user_exit):
                ctx  = _check_context()
                solo = len(ctx.get("members", [])) <= 1
                _disconnect_me_from_discord()
                if solo:
                    # Eras el único → el bot también se va y para la música
                    _stop_discord()
                    _disconnect_discord()
                    vlog("  -> [MODO] Usuario solo → música detenida, bot y usuario desconectados\n")
                    _speak_local_bg("Listo, te saqué del canal.")
                else:
                    # Hay más gente → solo te saca a vos, música sigue
                    vlog("  -> [MODO] Hay más gente → usuario desconectado, música sigue\n")
                    _speak_local_bg("Te saqué del canal. La música sigue para los demás.")
                _session["discord_mode"] = False
                _ov("ok")
                continue

            # ── Pasemos a mi PC (transferir música de Discord a local) ─────────
            # Detección por palabras clave: verbo de transferencia + destino local
            # Esto aguanta variaciones del STT ("vámonos", "vamos", "pasa", etc.)
            _xfer_verbs = {
                "pasemos", "pasa", "pasalo", "pasala", "pasame",
                "vamos", "vamonos", "mueve", "manda", "mandame",
                "cambia", "trae", "reproduce", "ponla", "ponlo",
            }
            # Frases largas → substring ok. Palabras cortas → word boundary
            # (evita que "aca" matchee dentro de "flaca", "vaca", etc.)
            _xfer_dest_phrases = ["mi pc", "a la pc", "al pc", "a local", "al local",
                                  "mis parlantes", "mis altavoces"]
            _xfer_dest_words   = {"aqui", "aca"}
            _is_transfer = (
                bool(_norm_words & _xfer_verbs)
                and (
                    any(d in norm_cmd for d in _xfer_dest_phrases)
                    or bool(_norm_words & _xfer_dest_words)
                )
            )
            if _is_transfer:
                status  = _get_status()
                current = status.get("current")
                vlog(f"  -> [TRANSFER] Canción actual: '{current}'")
                _speak_local("¿Quieres que salga de Discord también?")
                answer = _listen_yesno(recognizer, mic)
                _stop_discord()
                if answer is True:
                    _disconnect_discord()          # desconectar el bot
                    _disconnect_me_from_discord()  # desconectar al usuario
                    msg = f"Listo. {'Continuando con ' + current + ' en tu PC.' if current else 'Salí de Discord.'}"
                else:
                    msg = f"Detuve la música en Discord. {'Continúo con ' + current + ' en tu PC.' if current else ''}"
                _session["discord_mode"] = False
                _speak_local_bg(msg)
                vlog(f"  -> [TRANSFER] {'Bot y usuario desconectados' if answer else 'Bot en canal, modo local'}\n")
                _ov("ok")
                continue

            # ── Mover bot a canal ─────────────────────────────────────────────
            # Requiere "canal" o "discord" para no chocar con "vete de la pantalla"
            _move_bot_kws = ["muevete", "muevate", "pasate", "cambia de canal", "mueve al canal"]
            _is_move_bot  = (any(w in norm_cmd for w in _move_bot_kws) or
                             ("vete" in norm_cmd and "canal" in norm_cmd))
            if _is_move_bot and (ch := _extract_channel_name(norm_cmd, _move_bot_kws)):
                res = _move_discord("bot", ch)
                if res.get("ok"):
                    _speak_local_bg(f"Me moví al canal {res.get('channel', ch)}.")
                    vlog(f"  -> [MOVE] Bot → '{ch}'\n")
                else:
                    _speak_local_bg(f"No encontré el canal {ch}.")
                    vlog(f"  -> [MOVE] Canal '{ch}' no encontrado\n")
                _ov("ok")
                continue

            # ── Mover al usuario ──────────────────────────────────────────────
            _move_me_kws = ["llevame", "mandame", "pasame", "mueveme"]
            if any(w in norm_cmd for w in _move_me_kws) and \
               (ch := _extract_channel_name(norm_cmd, _move_me_kws)):
                res  = _move_discord("member", ch)
                if res.get("ok"):
                    _speak_local_bg(f"Te moví al canal {res.get('channel', ch)}.")
                    vlog(f"  -> [MOVE] Miembro → '{ch}'\n")
                else:
                    errs = res.get("errors", [])
                    msg  = "No tengo permiso para moverte." if any("permission" in e.lower() for e in errs) \
                           else f"No encontré el canal {ch}."
                    _speak_local_bg(msg)
                    vlog(f"  -> [MOVE] Error: {errs}\n")
                _ov("ok")
                continue

            # ── Mover ambos ───────────────────────────────────────────────────
            # "vamos" solo aplica si hay un canal mencionado (evitar falsos positivos)
            _move_both_kws = ["vamanos", "nos vamos", "vamos juntos", "vamos al canal"]
            _is_move_both  = (any(w in norm_cmd for w in _move_both_kws) or
                              ("vamos" in norm_cmd and "canal" in norm_cmd))
            if _is_move_both and \
               (ch := _extract_channel_name(norm_cmd, _move_both_kws)):
                res = _move_discord("both", ch)
                if res.get("ok"):
                    _speak_local_bg(f"Nos movimos al canal {res.get('channel', ch)}.")
                    vlog(f"  -> [MOVE] Ambos → '{ch}' (movidos: {res.get('moved', [])})\n")
                else:
                    _speak_local_bg(f"No encontré el canal {ch}.")
                    vlog(f"  -> [MOVE] Error: {res.get('errors', [])}\n")
                _ov("ok")
                continue

            from command_parser import full_parse as _fp
            _parsed_route = _fp(text, require_activator=False)
            _route = _orch.decide(
                norm_cmd=norm_cmd,
                norm_words=_norm_words,
                raw_text=text,
                parsed_intent=_parsed_route.get("action"),
            )

            if _route.handler == "ask" and not _session["asking"]:
                _session["asking"] = True
                try:
                    ctx = _check_context()
                    if ctx.get("in_discord"):
                        channel_name = ctx.get("channel", "el canal")
                        guild_name = ctx.get("guild", "")
                        members = ctx.get("members", [])
                        location = f"{channel_name} en {guild_name}" if guild_name else channel_name
                        vlog(f"  -> [CONTEXTO] En Discord: '{channel_name}' ({guild_name}) con {members}")
                        _ov("processing")
                        answer = _ask_discord_preference(recognizer, mic, location)
                        if answer is False:
                            _session["discord_mode"] = False
                            vlog("  -> [MODO] Usuario eligio local")
                        else:
                            _session["discord_mode"] = True
                            vlog("  -> [MODO] Usuario eligio Discord" if answer else
                                 "  -> [MODO] Sin respuesta, asumiendo Discord")
                    else:
                        _session["discord_mode"] = False
                        vlog("  -> [MODO] Sin canal de Discord del usuario, usando local")
                finally:
                    _session["asking"] = False
                _route = _orch.decide(norm_cmd, _norm_words, text, _parsed_route.get("action"))

            if _route.handler == "oauth":
                vlog("  -> [SPOTIFY_OAUTH] Vinculando Spotify por comando de voz\n")
                _ov("processing")
                threading.Thread(target=_spotify_oauth_flow, daemon=True).start()
                _ov("ok")
                continue

            if _route.handler == "local_media":
                vlog(f"  -> [LOCAL CTRL] {_route.words or _norm_words}\n")
                _local_control(_route.words or _norm_words)
                _ov("ok")
                continue

            if _route.handler == "local":
                vlog(f"  -> [LOCAL] Buscando en Spotify/YouTube: '{text}'")
                _ov("processing")
                _open_local_playback(text)
                continue

            if _route.handler == "discord":
                vlog(f"  -> [ENVIANDO] '{text}'")
                _ov("sending")
                result = _send_command_full(text)
                if result.get("ok"):
                    vlog("  -> [OK] comando enviado\n")
                    _ov("ok")
                    _speak_local_bg("lo tengo")   # confirmación de envío al bot
                    if result.get("need_spotify_auth"):
                        vlog("  -> [SPOTIFY_OAUTH] Servidor indica que falta Spotify - iniciando flujo\n")
                        threading.Thread(target=_spotify_oauth_flow, daemon=True).start()
                else:
                    err_msg = result.get("error", "")
                    err_code = result.get("status_code", 0)
                    if err_code == 400 and "canal de voz" in err_msg and _is_music_command(text):
                        vlog("  -> [FALLBACK LOCAL] Sin canal de voz - reproduciendo local\n")
                        _session["discord_mode"] = False
                        _open_local_playback(text, prefix="No hay nadie en Discord, abriendo")
                    elif result.get("action") in ("unknown", "ignored"):
                        vlog("  -> [IGNORADO] Comando no reconocido por el servidor\n")
                        _ov("idle")
                    else:
                        vlog(f"  -> [FALLO] no se pudo enviar (codigo={err_code} error='{err_msg}')\n")
                        _ov("error")
                continue

            if _route.handler == "ignore":
                vlog("  -> [IGNORADO] Orquestador ignoro el comando\n")
                _ov("idle")

        except sr.WaitTimeoutError:
            print("(silencio)")
            _ov("idle")
            continue

        except KeyboardInterrupt:
            print("\n\nHasta luego!")
            break

        except Exception as e:
            print(f"\n[ERROR] {e}")
            _ov("error")
            time.sleep(1)


if __name__ == "__main__":
    main()
