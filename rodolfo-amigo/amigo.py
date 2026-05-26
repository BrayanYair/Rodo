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

# Cuando corre como .exe de PyInstaller, agregar la carpeta del bundle al path
# para que los módulos locales (overlay, config_manager, setup_gui) se encuentren.
if getattr(sys, "frozen", False):
    _bundle_dir = sys._MEIPASS                      # carpeta temporal del bundle
    sys.path.insert(0, _bundle_dir)
    os.chdir(_bundle_dir)

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
from config_manager import config_exists, load_config
from setup_gui      import run_setup, run_reconfigure

# Activadores de voz — "rodo" es el principal
ACTIVATOR_NAMES = ("rodo", "rodolfo", "asistente")

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

NOMBRE        = cfg.get("nombre",    "Amigo")
BOT_API_URL   = cfg.get("api_url",   "").rstrip("/")
BOT_API_TOKEN = cfg.get("api_token", "")


# ─── Envío al servidor ────────────────────────────────────────────────────────

def send_command(text: str) -> bool:
    """Envía el comando al servidor de Rodo via API."""
    try:
        r = requests.post(
            f"{BOT_API_URL}/command",
            json={"text": text, "user": NOMBRE},
            headers={"Authorization": f"Bearer {BOT_API_TOKEN}"},
            timeout=10,
        )
        if r.status_code == 200:
            return r.json().get("ok", False)
        if r.status_code == 401:
            print("[ERROR] Contrasena incorrecta — pide al dueno los datos actualizados")
        elif r.status_code == 0:
            print("[ERROR] Sin respuesta del servidor")
        return False
    except requests.ConnectionError:
        print(f"[ERROR] No se pudo conectar a {BOT_API_URL}")
        return False
    except Exception as e:
        print(f"[ERROR] {e}")
        return False


# ─── Detección del activador ──────────────────────────────────────────────────

def normalize(text: str) -> str:
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return text.lower().strip()


def has_activator(text: str) -> bool:
    norm = normalize(text)
    return any(name in norm for name in ACTIVATOR_NAMES)


# ─── Principal ────────────────────────────────────────────────────────────────

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

    last_activator_time = 0.0
    ACTIVATOR_TIMEOUT   = 6.0   # segundos de ventana tras decir solo "Rodo"

    while True:
        try:
            with mic as source:
                recognizer.adjust_for_ambient_noise(source, duration=0.2)
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
                print("(nada)")
                _ov("idle")
                continue
            except sr.RequestError as e:
                print(f"(error STT: {e})")
                _ov("error")
                time.sleep(1)
                continue

            print(text)

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
                    last_activator_time = time.time()
                    print(f"  -> [ACTIVADOR] Escuchando comando ({ACTIVATOR_TIMEOUT:.0f}s)...\n")
                    continue
                else:
                    last_activator_time = 0.0
            else:
                # Sin activador — ¿hay ventana activa?
                if time.time() - last_activator_time < ACTIVATOR_TIMEOUT:
                    text = f"Rodo {text}"
                    print(f"  -> [COMPLETADO] -> '{text}'")
                    last_activator_time = 0.0
                else:
                    print(f"  -> [IGNORADO] di 'Rodo' primero\n")
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

            # ── Enviar al servidor ────────────────────────────────────────────
            print(f"  -> [ENVIANDO]...", end=" ", flush=True)
            _ov("sending")
            if send_command(text):
                print("OK\n")
                _ov("ok")
            else:
                print("FALLO\n")
                _ov("error")

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
