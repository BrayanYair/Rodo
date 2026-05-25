"""
amigo_rodolfo.py — Companion de voz para amigos de Rodolfo
==========================================================
Captura tu micrófono, escucha comandos como "Rodolfo pon despacito",
y los envía al bot de Discord para que reproduzca música.

NO necesitas Whisper ni nada pesado — usa Google STT (gratis y rápido).
Solo necesitas internet y un micrófono.
"""

import os
import sys
import time
import re
import unicodedata
import socket

# Forzar UTF-8
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

# Overlay visual de estado (opcional)
try:
    from overlay import StatusOverlay as _OverlayClass
    _overlay = _OverlayClass()
    _overlay.start()
except Exception:
    _overlay = None

def _ov(state: str):
    """Actualiza el overlay sin lanzar excepciones."""
    if _overlay:
        try:
            _overlay.set_state(state)
        except Exception:
            pass

# ─── Configuración ────────────────────────────────────────────────────────────
# Intentar cargar .env si existe dotenv
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # Si no hay dotenv, leer de os.environ directamente

WEBHOOK_URL   = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
BOT_API_URL   = os.getenv("BOT_API_URL",   "").strip().rstrip("/")
BOT_API_TOKEN = os.getenv("BOT_API_TOKEN", "").strip()
NOMBRE        = os.getenv("NOMBRE", "").strip()
ACTIVATOR_NAMES = ("rodolfo", "jarvis", "asistente", "bot")

# Modo de envío: "api" = directo al servidor | "webhook" = via Discord
MODE = "api" if (BOT_API_URL and BOT_API_TOKEN) else "webhook"

# Si no hay nombre configurado, preguntar
if not NOMBRE:
    NOMBRE = input("¿Cómo te llamas? (aparecerá en Discord): ").strip() or "Amigo"

# Si no hay ningún método de envío, pedir webhook (modo clásico)
if MODE == "webhook" and not WEBHOOK_URL:
    print()
    print("╔══════════════════════════════════════════════════╗")
    print("║  Necesitas el enlace del webhook de Discord.     ║")
    print("║  Pídele a tu amigo (el dueño del bot) que te     ║")
    print("║  comparta la URL del webhook.                    ║")
    print("╚══════════════════════════════════════════════════╝")
    print()
    WEBHOOK_URL = input("Pega aquí la URL del webhook: ").strip()
    if not WEBHOOK_URL:
        print("Sin webhook no puedo enviar comandos. ¡Hasta luego!")
        input("Presiona Enter para cerrar...")
        sys.exit(1)
    # Guardar para la próxima vez
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    with open(env_path, "w", encoding="utf-8") as f:
        f.write(f'DISCORD_WEBHOOK_URL={WEBHOOK_URL}\n')
        f.write(f'NOMBRE={NOMBRE}\n')
    print(f"✅ Guardado en .env — no te lo pedirá de nuevo.\n")


# ─── Funciones ────────────────────────────────────────────────────────────────
def normalize(text):
    """Lowercase, sin acentos."""
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return text.lower().strip()


def has_activator(text):
    """¿El texto contiene 'Rodolfo' o similar?"""
    norm = normalize(text)
    return any(name in norm for name in ACTIVATOR_NAMES)


def send_to_discord(text: str) -> bool:
    """Envía el comando a Discord via webhook (modo clásico)."""
    try:
        r = requests.post(WEBHOOK_URL, json={
            "content":  text,
            "username": f"🎤 {NOMBRE}",
        }, timeout=10)
        return r.status_code in (200, 204)
    except requests.ConnectionError:
        print("[ERROR] Sin conexión a Discord.")
        return False
    except Exception as e:
        print(f"[ERROR] {e}")
        return False


def send_to_api(text: str) -> bool:
    """Envía el comando directamente al bot via API REST (modo servidor)."""
    try:
        r = requests.post(
            f"{BOT_API_URL}/command",
            json={"text": text, "user": NOMBRE},
            headers={"Authorization": f"Bearer {BOT_API_TOKEN}"},
            timeout=10,
        )
        if r.status_code == 200:
            resp = r.json()
            return resp.get("ok", False)
        if r.status_code == 401:
            print("[ERROR] Token inválido — revisa BOT_API_TOKEN en .env")
        return False
    except requests.ConnectionError:
        print(f"[ERROR] No se pudo conectar a {BOT_API_URL}")
        return False
    except Exception as e:
        print(f"[ERROR] {e}")
        return False


def _send(text: str) -> bool:
    """Selecciona el método de envío según el modo configurado."""
    return send_to_api(text) if MODE == "api" else send_to_discord(text)


# ─── Principal ────────────────────────────────────────────────────────────────
def main():
    modo_str = "API directa 🚀" if MODE == "api" else "Discord webhook"
    print()
    print("╔══════════════════════════════════════════════════╗")
    print("║        🎤 Amigo de Rodolfo — Companion          ║")
    print("╠══════════════════════════════════════════════════╣")
    print(f"║  Nombre: {NOMBRE:<39s} ║")
    print(f"║  Modo:   {modo_str:<39s} ║")
    print("║  Di 'Rodolfo pon [canción]' para poner música   ║")
    print("║  Ctrl+C para salir                              ║")
    print("╚══════════════════════════════════════════════════╝")
    print()

    recognizer = sr.Recognizer()

    # Detectar micrófono
    try:
        mic = sr.Microphone()
    except (OSError, AttributeError):
        print("ERROR: No se detectó micrófono.")
        print("Asegúrate de tener un mic conectado y permisos activados.")
        input("Presiona Enter para cerrar...")
        return

    print("[INIT] Calibrando micrófono...")
    with mic as source:
        recognizer.adjust_for_ambient_noise(source, duration=1.5)
    print("[INIT] ¡Listo! Empieza a hablar.\n")

    print("Comandos que puedes decir:")
    print("  • Rodolfo pon despacito")
    print("  • Rodolfo siguiente / pásala")
    print("  • Rodolfo pausa / sigue")
    print("  • Rodolfo qué está sonando")
    print("  • Rodolfo para la música")
    print()

    last_activator_time = 0.0
    ACTIVATOR_TIMEOUT = 6.0

    while True:
        try:
            with mic as source:
                # Re-calibrar brevemente cada ciclo para adaptarse al ruido
                recognizer.adjust_for_ambient_noise(source, duration=0.2)
                _ov("listening")
                print("[ESCUCHO] ", end="", flush=True)
                audio = recognizer.listen(
                    source,
                    timeout=10,
                    phrase_time_limit=7,
                )

            # Transcribir con Google STT (rápido y gratis)
            _ov("processing")
            try:
                old_timeout = socket.getdefaulttimeout()
                socket.setdefaulttimeout(3.0)
                try:
                    text = recognizer.recognize_google(audio, language="es-ES")
                    text = text.strip()
                finally:
                    socket.setdefaulttimeout(old_timeout)
            except sr.UnknownValueError:
                print("(nada)")
                _ov("idle")
                continue
            except sr.RequestError as e:
                print(f"(error Google STT o lento: {e})")
                _ov("error")
                time.sleep(1)
                continue

            print(f"{text}")

            # ¿Tiene el activador "Rodolfo"?
            contains_act = has_activator(text)

            if contains_act:
                # Ver si solo dijo el activador o tiene contenido adicional
                norm_text = normalize(text)
                clean_norm = norm_text
                for name in ACTIVATOR_NAMES:
                    clean_norm = re.sub(rf"\b{name}\b", "", clean_norm)
                clean_norm = clean_norm.strip()

                has_content = len(clean_norm) > 0

                if not has_content:
                    # Dijo solo el activador (ej: "Rodolfo")
                    last_activator_time = time.time()
                    print(f"  └─ [ACTIVADOR] Esperando comando (ventana de {ACTIVATOR_TIMEOUT}s)...\n")
                    continue
                else:
                    # Dijo activador con comando (ej: "Rodolfo pon despacito")
                    last_activator_time = 0.0  # resetear ventana
            else:
                # No contiene activador, ver si la ventana de memoria está activa
                if time.time() - last_activator_time < ACTIVATOR_TIMEOUT:
                    # Ventana activa: autocompletar con "Rodolfo"
                    text = f"Rodolfo {text}"
                    print(f"  └─ [COMPLETADO] → '{text}'")
                    last_activator_time = 0.0  # usar y resetear
                else:
                    # Ignorar y resetear ventana
                    print(f"  └─ [IGNORADO] sin 'Rodolfo'\n")
                    last_activator_time = 0.0
                    continue

            # ¡Comando detectado! Enviar (Discord o API directa según el modo)
            destino = "API" if MODE == "api" else "Discord"
            print(f"  └─ [ENVIANDO] → {destino}...", end=" ", flush=True)
            _ov("sending")
            if _send(text):
                print("✅\n")
                _ov("ok")
            else:
                print("❌\n")
                _ov("error")

        except sr.WaitTimeoutError:
            print("(silencio)")
            _ov("idle")
            continue
        except KeyboardInterrupt:
            print("\n\n¡Hasta luego! 👋")
            break
        except Exception as e:
            print(f"\n[ERROR] {e}")
            _ov("error")
            time.sleep(1)


if __name__ == "__main__":
    main()
