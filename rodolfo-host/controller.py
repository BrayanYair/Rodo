import os
import sys
import json
import asyncio
import subprocess
import threading
import time
import re
import unicodedata
import tempfile
import socket
import queue
from datetime import datetime

# Forzar UTF-8 en la salida estándar para evitar errores con acentos / flechas
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

import numpy as np
import requests
import pygame

from pathlib import Path
from dotenv import load_dotenv
from fuzzywuzzy import fuzz
import edge_tts
import whisper
import speech_recognition as sr

# Respuestas naturales con variantes (en vez de frases robóticas fijas)
import responses as R

# Overlay visual de estado (opcional — falla silenciosamente si no está disponible)
try:
    from overlay import StatusOverlay
    _OVERLAY_OK = True
except Exception:
    _OVERLAY_OK = False

load_dotenv()

BASE_DIR = Path(__file__).parent

# ─── Performance log ──────────────────────────────────────────────────────────
# Registra latencia STT + tiempo hasta primer speak() de cada comando.
# Úsalo para encontrar cuellos de botella y comparar mejoras en el tiempo.
_PERF_LOG = BASE_DIR / "performance_log.jsonl"

def _log_perf(raw: str, action: str, stt_ms: int, first_response_ms, query: str = ""):
    """Una línea JSON por comando: qué se dijo, qué entendió, cuánto tardó."""
    try:
        entry = {
            "ts":                datetime.now().isoformat(timespec="seconds"),
            "raw":               raw,
            "action":            action,
            "query":             query,
            "stt_ms":            stt_ms,            # latencia Google STT
            "first_response_ms": first_response_ms, # ms desde STT hasta primer speak()
        }
        with open(_PERF_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[PERF] Error al guardar: {e}")


class VoiceAudioController:
    VOICE                 = os.getenv("TTS_VOICE", "es-ES-ElviraNeural")
    DISCORD_WEBHOOK_URL   = os.getenv("DISCORD_WEBHOOK_URL", "")
    MUSIC_BOT_URL         = os.getenv("MUSIC_BOT_URL", "http://127.0.0.1:5000")
    API_TOKEN             = os.getenv("API_TOKEN", "")
    WAKE_WORD_ENABLED     = os.getenv("WAKE_WORD_ENABLED", "true").lower() == "true"
    ACTIVATOR_REQUIRED    = os.getenv("ACTIVATOR_REQUIRED", "true").lower() == "true"
    ACTIVATOR_NAMES       = ("oye rodolfo", "rodolfo")
    # Dónde habla Rodolfo:
    #   "discord" → solo por el canal de voz (tú estás en el canal, no hay eco)  ✅ default
    #   "local"   → solo por tu PC (privado, amigos no oyen)
    #   "both"    → ambos (genera eco si estás en el canal)
    TTS_OUTPUT            = os.getenv("TTS_OUTPUT", "discord").lower()

    # Sonidos suaves cuando ejecuta acciones (success/error). Desactívalos si molestan.
    CHIMES_ENABLED        = os.getenv("CHIMES_ENABLED", "false").lower() == "true"
    # Whisper como fallback cuando Google STT está offline.
    # Por defecto DESACTIVADO porque alucina con ruido/cortes de red.
    # Si tu internet es inestable, ponlo en "true".
    WHISPER_FALLBACK      = os.getenv("WHISPER_FALLBACK", "false").lower() == "true"

    def __init__(self):
        self.config = {
            "listen_timeout":     8,
            "phrase_time_limit":  8,
            "whisper_model":      os.getenv("WHISPER_MODEL", "small"),
            "wake_word_threshold": float(os.getenv("WAKE_WORD_THRESHOLD", "0.5")),
        }

        self.is_speaking            = False
        self.interrupt_speech       = False
        self._lock                  = threading.Lock()

        # Playlists nombradas desde .env (PLAYLIST_XXX=https://...)
        self.playlists = {
            key.replace("PLAYLIST_", "").lower(): val
            for key, val in os.environ.items()
            if key.startswith("PLAYLIST_") and val.strip()
        }
        if self.playlists:
            print(f"[INIT] Playlists guardadas: {list(self.playlists.keys())}")

        self._initialize_components()
        self.last_activator_time = 0.0
        self.ACTIVATOR_TIMEOUT   = 6.0
        self._debounce           = {}
        self._debounce_secs      = 2.0
        self._last_audio_ts      = time.time()  # última vez que el queue recibió audio real
        # Overlay visual de estado
        self._overlay = None
        if _OVERLAY_OK:
            try:
                self._overlay = StatusOverlay()
                self._overlay.start()
                print("[OVERLAY] Indicador de estado activo.")
            except Exception as e:
                print(f"[OVERLAY] No se pudo iniciar: {e}")
        # Timing de rendimiento — se actualizan en listen_command() y speak()
        self._t_listen_start     = 0.0   # cuando el audio sale del queue (usuario dejó de hablar)
        self._t_stt_done         = 0.0   # cuando Google STT devolvió el texto
        self._t_first_speak      = None  # cuando se llamó speak() por primera vez en este ciclo

    # ─────────────────────────────────────────────────────────────────────────
    # Inicialización
    # ─────────────────────────────────────────────────────────────────────────

    def _initialize_components(self):
        pygame.mixer.init()
        self._init_chimes()

        if self.WHISPER_FALLBACK:
            print(f"[INIT] Cargando Whisper ({self.config['whisper_model']}) como fallback offline...")
            self.whisper_model = whisper.load_model(self.config["whisper_model"])
            print("[INIT] Whisper listo.")
        else:
            self.whisper_model = None
            print("[INIT] Whisper desactivado — usando solo Google STT (más rápido, sin alucinaciones).")

        self.recognizer = sr.Recognizer()
        # Bajamos pause_threshold para responder más rápido cuando el usuario
        # termina de hablar (default 0.8s → 0.5s reduce la latencia notablemente)
        self.recognizer.pause_threshold = 0.5
        self.recognizer.non_speaking_duration = 0.4
        self.microphone = sr.Microphone()
        print("[INIT] Calibrando micrófono...")
        with self.microphone as source:
            self.recognizer.adjust_for_ambient_noise(source, duration=1)
        print("[INIT] Micrófono calibrado.")

        # Background listener: siempre escuchando, sin gaps ni timeouts
        self.audio_queue = queue.Queue()
        self._stop_background_listener = None
        self._start_background_listening()

        self.wake_model = None
        if self.WAKE_WORD_ENABLED:
            self._load_wake_word_model()

    def _ov(self, state: str):
        """Actualiza el overlay de estado (nunca lanza excepciones)."""
        if self._overlay:
            try:
                self._overlay.set_state(state)
            except Exception:
                pass

    def _start_background_listening(self):
        """Background listener: el mic está siempre activo en un hilo aparte.
        Las frases detectadas se ponen en self.audio_queue. Sin gaps ni timeouts."""
        def callback(recognizer, audio):
            # Si estoy hablando localmente, descarto para evitar feedback
            if self.is_speaking and self.TTS_OUTPUT in ("local", "both"):
                return
            try:
                self.audio_queue.put(audio, block=False)
            except queue.Full:
                pass

        self._stop_background_listener = self.recognizer.listen_in_background(
            self.microphone,
            callback,
            phrase_time_limit=self.config["phrase_time_limit"],
        )
        print("[ESCUCHANDO] Mic siempre activo (background).")

    def _restart_background_listener(self):
        """Reinicia el background listener si el watchdog detecta que se trabó."""
        print("[WATCHDOG] Deteniendo listener anterior...")
        try:
            if self._stop_background_listener:
                self._stop_background_listener(wait_for_stop=False)
                self._stop_background_listener = None
        except Exception as e:
            print(f"[WATCHDOG] Error al detener: {e}")

        # Vaciar la cola por si quedaron frames corruptos
        while not self.audio_queue.empty():
            try:
                self.audio_queue.get_nowait()
            except Exception:
                break

        time.sleep(0.8)
        try:
            # No recalibramos aquí para no entrar en conflicto con el micrófono.
            # La calibración inicial al arrancar es suficiente.
            self._start_background_listening()
            print("[WATCHDOG] Listener reiniciado correctamente.")
        except Exception as e:
            print(f"[WATCHDOG] No se pudo reiniciar el listener: {e}")

    def _init_chimes(self):
        self.chimes = {}
        sample_rate = 44100

        def create_beep_sound(frequencies, duration_ms, volume=0.1, fade_out=True):
            if not isinstance(frequencies, list):
                frequencies = [frequencies]
            
            total_samples = int(sample_rate * (duration_ms / 1000.0))
            n_tones = len(frequencies)
            samples_per_tone = total_samples // n_tones
            
            wave_parts = []
            for freq in frequencies:
                t = np.linspace(0, samples_per_tone / sample_rate, samples_per_tone, False)
                tone = np.sin(2 * np.pi * freq * t)
                wave_parts.append(tone)
                
            wave = np.concatenate(wave_parts)
            
            if fade_out:
                fade_len = int(len(wave) * 0.15)
                fade_window = np.ones(len(wave))
                fade_window[-fade_len:] = np.linspace(1.0, 0.0, fade_len)
                wave = wave * fade_window

            audio = (wave * 32767 * volume).astype(np.int16)
            stereo_audio = np.ascontiguousarray(np.column_stack((audio, audio)))
            try:
                return pygame.sndarray.make_sound(stereo_audio)
            except Exception as e:
                print(f"[CHIME INIT ERROR] {e}")
                return None

        # 1. Listening (Ascending arpeggio C5 -> E5)
        self.chimes["listening"] = create_beep_sound([523.25, 659.25], 200, 0.12)
        # 2. Thinking (Single soft high note A5)
        self.chimes["thinking"] = create_beep_sound(880.0, 100, 0.08)
        # 3. Success (Bright double chime E5 -> A5)
        self.chimes["success"] = create_beep_sound([659.25, 880.0], 250, 0.12)
        # 4. Error (Low warning tone 180Hz -> 150Hz)
        self.chimes["error"] = create_beep_sound([180.0, 150.0], 350, 0.18)

    def play_chime(self, name):
        # Si los chimes están desactivados via .env, no hacemos nada
        if not getattr(self, "CHIMES_ENABLED", True):
            return
        sound = self.chimes.get(name)
        if sound:
            try:
                sound.play()
            except Exception as e:
                print(f"[CHIME PLAY ERROR] {name}: {e}")

    def _load_wake_word_model(self):
        try:
            from openwakeword.model import Model
            self.wake_model = Model(
                wakeword_models=["hey_jarvis"],
                inference_framework="onnx",
            )
            print("[INIT] Wake word listo — di 'Hey Jarvis' para activar.")
        except Exception as e:
            print(f"[INIT] Wake word no disponible ({e}). Corriendo sin wake word.")
            self.wake_model = None

    # ─────────────────────────────────────────────────────────────────────────
    # TTS  —  Edge-TTS (voces neurales de Microsoft)
    # ─────────────────────────────────────────────────────────────────────────

    def speak(self, text, can_interrupt=True, broadcast=True):
        clean = self._clean_text(text)
        print(f"[VOZ] {clean}")
        if self._t_first_speak is None:
            self._t_first_speak = time.time()   # primer speak() de este ciclo

        self._ov("speaking")   # feedback inmediato: el bot está por hablar

        play_local      = self.TTS_OUTPUT in ("local", "both")
        send_to_discord = broadcast and self.TTS_OUTPUT in ("discord", "both")

        # Enviar al bot en paralelo para que tus amigos también lo escuchen
        if send_to_discord:
            threading.Thread(
                target=self._broadcast_to_discord,
                args=(clean,),
                daemon=True,
            ).start()

        if play_local:
            # Reproducción local + tracking del estado (para interrupciones)
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(self._speak_edge(clean, can_interrupt))
            finally:
                loop.close()
        elif send_to_discord:
            # Solo Discord — bloqueamos brevemente para que la cola de
            # comandos no se atropelle (estimación: ~3 palabras por segundo)
            words = max(1, len(clean.split()))
            with self._lock:
                self.is_speaking = True
            time.sleep(min(15, max(1.0, words / 3.0 + 0.5)))
            with self._lock:
                self.is_speaking = False

        self._ov("idle")   # habló, vuelve a escuchar

    def _auth_headers(self):
        return {"Authorization": f"Bearer {self.API_TOKEN}"} if self.API_TOKEN else {}

    def _broadcast_to_discord(self, text):
        """Envía el texto al bot para que lo hable por el canal de voz."""
        try:
            requests.post(
                f"{self.MUSIC_BOT_URL}/say",
                json={"text": text},
                headers=self._auth_headers(),
                timeout=10,
            )
        except requests.ConnectionError:
            pass  # Bot offline, solo hablamos local
        except Exception as e:
            print(f"[BROADCAST] {e}")

    async def _speak_edge(self, text, can_interrupt):
        tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        tmp_path = tmp.name
        tmp.close()

        try:
            communicate = edge_tts.Communicate(text, voice=self.VOICE)
            await communicate.save(tmp_path)
        except Exception as e:
            print(f"[TTS ERROR] {e}")
            os.unlink(tmp_path)
            return

        with self._lock:
            self.is_speaking      = True
            self.interrupt_speech = False

        pygame.mixer.music.load(tmp_path)
        pygame.mixer.music.play()

        if can_interrupt:
            t = threading.Thread(target=self._check_for_interruptions, daemon=True)
            t.start()

        while pygame.mixer.music.get_busy():
            if self.interrupt_speech:
                pygame.mixer.music.stop()
                break
            pygame.time.wait(50)

        with self._lock:
            self.is_speaking = False

        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    def _clean_text(self, text):
        for old, new in {"¿": "", "¡": "", "®": "", "  ": " "}.items():
            text = text.replace(old, new)
        return text.strip()

    # ─────────────────────────────────────────────────────────────────────────
    # STT  —  Whisper local
    # ─────────────────────────────────────────────────────────────────────────

    def listen_command(self, timeout=None):
        """Espera la próxima frase de la cola del background listener y la transcribe.
        Sin gaps: el mic está siempre activo, no perdemos audio entre llamadas."""
        timeout = timeout or self.config["listen_timeout"]
        try:
            audio = self.audio_queue.get(timeout=timeout)
        except queue.Empty:
            return ""

        self._t_listen_start = time.time()   # audio listo = usuario dejó de hablar
        self._last_audio_ts  = time.time()   # listener sigue vivo (llegó audio al queue)
        self._ov("processing")               # el bot recibió audio — el usuario lo verá de inmediato

        # Google STT (rápido y muy preciso en español)
        google_offline = False
        try:
            old_timeout = socket.getdefaulttimeout()
            socket.setdefaulttimeout(3.0)
            try:
                text = self.recognizer.recognize_google(audio, language="es-ES").lower().strip()
            finally:
                socket.setdefaulttimeout(old_timeout)
            if text:
                self._t_stt_done = time.time()   # STT completado
                print(f"[ENTENDÍ] {text}")
                return text
        except sr.UnknownValueError:
            # Audio incomprensible — NO usamos Whisper porque alucina con basura.
            # Mejor descartar y esperar el próximo audio.
            return ""
        except sr.RequestError as e:
            print(f"[GOOGLE OFFLINE/LENTO ({e})] — usando Whisper")
            google_offline = True

        # Solo fallback a Whisper si Google está offline Y el fallback está habilitado
        if not google_offline or not self.whisper_model:
            return ""

        try:
            audio_np = (
                np.frombuffer(audio.get_wav_data(), np.int16)
                .flatten()
                .astype(np.float32) / 32768.0
            )
            result = self.whisper_model.transcribe(audio_np, language="es", fp16=False)
            text = result["text"].lower().strip()
            if text and not self._is_gibberish(text):
                print(f"[ENTENDÍ via Whisper] {text}")
                return text
            elif text:
                print(f"[WHISPER gibberish descartado] '{text[:40]}'")
        except Exception as e:
            print(f"[WHISPER ERROR] {e}")

        return ""

    def _is_gibberish(self, text):
        """Detecta alucinaciones de Whisper: caracteres no latinos, demasiado corto, etc."""
        if not text or len(text.strip()) < 2:
            return True
        text = text.strip()
        spanish_chars = set("abcdefghijklmnñopqrstuvwxyzáéíóúüABCDEFGHIJKLMNÑOPQRSTUVWXYZÁÉÍÓÚÜ")
        alpha = [c for c in text if c.isalpha()]
        if not alpha:
            return True
        spanish_count = sum(1 for c in alpha if c in spanish_chars)
        # Si menos del 70% son caracteres del alfabeto español → gibberish
        if spanish_count / len(alpha) < 0.7:
            return True
        # Frases típicas de alucinación de Whisper con silencio
        common_hallucinations = {
            "gracias por ver el video", "gracias por ver el vídeo",
            "subtítulos por la comunidad de amara.org", "subtítulos",
            "gracias", "thank you", "you", ".", "..",
        }
        if text.strip() in common_hallucinations:
            return True
        # Palabras inglesas típicas de alucinación (cuando Whisper improvisa con audio basura)
        english_red_flags = {
            "the", "was", "with", "this", "that", "have", "been", "would",
            "could", "should", "happened", "tighten", "treasures", "constructed",
            "video", "subscribe", "channel", "thanks", "watching",
        }
        words = [w.strip(".,!?¿¡;:") for w in text.lower().split()]
        english_count = sum(1 for w in words if w in english_red_flags)
        if english_count >= 2:
            return True

        # Demasiados números sueltos (típico de alucinación con audio basura)
        if len(words) >= 4:
            numeric_words = sum(1 for w in words if w.replace(".", "").isdigit())
            if numeric_words / len(words) > 0.3:
                return True
            # Demasiadas "palabras" de 1-2 caracteres
            tiny_words = sum(1 for w in words if 0 < len(w) <= 2 and w.isalpha())
            if tiny_words >= 3:
                return True
            # Promedio de longitud muy bajo → garabato
            avg_len = sum(len(w) for w in words) / len(words)
            if avg_len < 2.5:
                return True

        return False

    # ─────────────────────────────────────────────────────────────────────────
    # Detección de interrupciones  (Google STT — rápido para clips cortos)
    # ─────────────────────────────────────────────────────────────────────────

    def _check_for_interruptions(self):
        rec = sr.Recognizer()
        while self.is_speaking and not self.interrupt_speech:
            try:
                with sr.Microphone() as source:
                    audio = rec.listen(source, timeout=0.3, phrase_time_limit=1.5)
                
                old_timeout = socket.getdefaulttimeout()
                socket.setdefaulttimeout(1.5)
                try:
                    cmd = rec.recognize_google(audio, language="es-ES").lower()
                finally:
                    socket.setdefaulttimeout(old_timeout)
                
                print(f"[INTERRUPCIÓN] {cmd}")
                self._handle_interruption_text(cmd)
            except (sr.WaitTimeoutError, sr.UnknownValueError, sr.RequestError):
                pass
            except Exception as e:
                if "context manager" not in str(e).lower():
                    break
            time.sleep(0.05)

    def _handle_interruption_text(self, cmd):
        parsed = self.parse_command(cmd)
        if parsed["action"] == "switch":
            self.interrupt_speech        = True
            self.detected_device_command = parsed
            return
        interrupt_words = ["para", "stop", "alto", "basta", "detente", "espera", "calla"]
        if any(w in cmd for w in interrupt_words):
            self.interrupt_speech        = True
            self.detected_device_command = None

    # ─────────────────────────────────────────────────────────────────────────
    # Wake Word  —  openwakeword ("Hey Jarvis")
    # ─────────────────────────────────────────────────────────────────────────

    def wait_for_wake_word(self):
        if not self.wake_model:
            return

        try:
            import pyaudio
            CHUNK = 1280
            p      = pyaudio.PyAudio()
            stream = p.open(
                format=pyaudio.paInt16, channels=1, rate=16000,
                input=True, frames_per_buffer=CHUNK,
            )
            print(f"[EN ESPERA] Di 'Hey Jarvis' para activar (umbral: {self.config['wake_word_threshold']})...")

            tick = 0
            max_score_window = 0
            while True:
                chunk_bytes = stream.read(CHUNK, exception_on_overflow=False)
                chunk    = np.frombuffer(chunk_bytes, dtype=np.int16)
                volume   = float(np.abs(chunk).mean())  # nivel de audio del mic
                scores   = self.wake_model.predict(chunk)
                score    = scores.get("hey_jarvis", 0)
                max_score_window = max(max_score_window, score)

                # Heartbeat cada ~2 segundos: muestra que el loop está vivo + el mejor score reciente
                tick += 1
                if tick % 25 == 0:
                    print(f"  [escuchando] vol={volume:6.0f}  mejor-score-reciente={max_score_window:.2f}")
                    max_score_window = 0

                # Cualquier score > 0.05 lo mostramos (te ayuda a ver si te está oyendo)
                if score > 0.05:
                    print(f"  [wake-score] {score:.2f}  {'█' * int(score*20)}")

                if score > self.config["wake_word_threshold"]:
                    print(f"[ACTIVADO ✅] score={score:.2f}")
                    stream.stop_stream()
                    stream.close()
                    p.terminate()
                    return
        except Exception as e:
            print(f"[WAKE WORD ERROR] {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # Control de volumen  —  nircmd.exe
    # ─────────────────────────────────────────────────────────────────────────

    def _nircmd(self, *args):
        path = BASE_DIR / "nircmd.exe"
        subprocess.run([str(path), *args], capture_output=True, timeout=5)

    def volume_up(self):
        self._nircmd("changesysvolume", "5000")
        self.speak(R.volume_up(), can_interrupt=False)

    def volume_down(self):
        self._nircmd("changesysvolume", "-5000")
        self.speak(R.volume_down(), can_interrupt=False)

    def volume_mute(self):
        self._nircmd("mutesysvolume", "2")
        self.speak(R.volume_mute(), can_interrupt=False)

    def volume_set(self, level: int):
        val = int(level * 655.35)          # 0-100  →  0-65535
        self._nircmd("setsysvolume", str(val))
        self.speak(R.volume_set(level), can_interrupt=False)

    # ─────────────────────────────────────────────────────────────────────────
    # Parseo de comandos
    # ─────────────────────────────────────────────────────────────────────────

    def parse_volume_level(self, cmd):
        m = re.search(r"\b(\d{1,3})\b", cmd)
        if m:
            val = int(m.group(1))
            if 0 <= val <= 100:
                return val
        
        # Palabras clave de volumen absoluto
        if any(w in cmd for w in ["maximo", "maxima", "todo", "cien", "100%"]):
            return 100
        if any(w in cmd for w in ["mitad", "medio", "cincuenta"]):
            return 50
        if any(w in cmd for w in ["minimo", "minima", "cero"]):
            return 0
        return -1

    def parse_command(self, cmd):
        if not cmd:
            return {"action": "unknown"}

        cmd = unicodedata.normalize("NFD", cmd)
        cmd = "".join(c for c in cmd if unicodedata.category(c) != "Mn")
        cmd = re.sub(r"[^\w\s]", "", cmd.lower().strip())

        # ── Detección del activador "Rodolfo" (en cualquier parte) ────────
        # Google STT a veces antepone basura tipo "ahí está rodolfo..."
        # así que buscamos el activador en cualquier lugar del comando.
        names_re = "|".join(re.escape(name) for name in sorted(self.ACTIVATOR_NAMES, key=len, reverse=True))
        activator_re = re.compile(rf"(?<!\w)(?:{names_re})(?!\w)[,\s]*")
        m = activator_re.search(cmd)
        has_activator = bool(m)
        if has_activator:
            # Tomamos todo lo que viene DESPUÉS del activador como el comando
            cmd = cmd[m.end():].strip()

        # Modo activador: si no fue invocado, ignorar silenciosamente
        if self.ACTIVATOR_REQUIRED and not has_activator:
            return {"action": "ignored"}

        # Dijo el activador pero nada útil después → saludo
        if not cmd or len(cmd) < 2:
            return {"action": "greet"}

        # Correcciones comunes de Google STT con palabras cortas
        cmd = re.sub(r"\bpom\b", "pon", cmd)
        cmd = re.sub(r"\bpong\b", "pon", cmd)
        cmd = re.sub(r"\bbong\b", "pon", cmd)
        cmd = re.sub(r"\bporn\b", "pon", cmd)
        cmd = re.sub(r"\bpum\b", "pon", cmd)
        cmd = re.sub(r"\bpomp[oó]n\b", "pon", cmd)
        cmd = re.sub(r"\bpompom\b", "pon", cmd)
        cmd = re.sub(r"\bpun\b", "pon", cmd)
        cmd = re.sub(r"\bstock\b", "stop", cmd)
        cmd = re.sub(r"\bskype\b", "skip", cmd)

        # ── Volumen ────────────────────────────────────────────────────────
        # 1. Mutear/Silenciar
        if any(w in cmd for w in [
            "silencio", "mutear", "silenciar", "mute", "sin sonido",
            "callate todo", "apaga el sonido",
        ]):
            return {"action": "volume_mute"}

        # 2. Establecer volumen absoluto (ej: volumen al maximo, pon el volumen al 50)
        if "volumen" in cmd or "sonido" in cmd:
            level = self.parse_volume_level(cmd)
            if level >= 0:
                return {"action": "volume_set", "level": level}

        # 3. Subir volumen
        if any(w in cmd for w in [
            "mas volumen", "volumen arriba", "mas fuerte", "mas alto", "no escucho", "no se escucha",
            "alza el volumen", "alzar volumen",
        ]) or (any(w in cmd for w in ["sube", "subir", "subele", "alza", "alzar"]) and any(w in cmd for w in ["volumen", "sonido", "musica", "audio"])):
            return {"action": "volume_up"}

        # 4. Bajar volumen
        if any(w in cmd for w in [
            "menos volumen", "volumen abajo", "mas bajo", "mas suave", "no tan fuerte", "muy fuerte",
            "bajar la musica", "baja la musica",
        ]) or (any(w in cmd for w in ["baja", "bajar", "bajale"]) and any(w in cmd for w in ["volumen", "sonido", "musica", "audio"])):
            return {"action": "volume_down"}

        # ── Música: STOP / PAUSE / SKIP rápido (priorizar antes de play) ──
        # Captura "rodolfo stop", "rodolfo para", "rodolfo pon stop la musica"...
        # Si el comando contiene una palabra de stop CLARA y no es título de canción
        if re.search(r"\b(stop|deten|detener|detenga|detiene|para|parar|pare|paren)\b.*\b(musica|cancion|tema|todo|esto|esta|reproduccion)\b", cmd) or \
           cmd in ("stop", "para", "deten", "detener", "detenga", "alto", "basta", "pare", "paren"):
            return {"action": "stop_music"}
        if re.search(r"\b(pausa|pausala)\b", cmd):
            return {"action": "pause_music"}
        if re.search(r"\b(salta|saltala|pasala|pasalo|siguiente)\b", cmd):
            return {"action": "skip_music"}

        # ── Música: AGREGAR A LA COLA (intención explícita) ───────────────
        # "luego pon X" / "después coloca X" / "encola X" / "agrega X a la cola"
        queue_match = re.match(
            r"^(?:luego|despues|posteriormente|enseguida|en\s+seguida|"
            r"al\s+rato|despuecito|cuando\s+(?:termine|acabe|se\s+acabe))\s+"
            r"(?:pon(?:me)?|coloca(?:me)?|echa(?:me)?|metele|reproduce(?:me)?|tira(?:me)?)\s+"
            r"(.+?)$",
            cmd,
        )
        if queue_match:
            rest = queue_match.group(1).strip()
            rest = re.sub(r"^(?:la|el|un|una|los|las|algo\s+de)\s+", "", rest)
            rest = re.sub(r"^(?:musica|cancion|tema|rola|track)\s*(?:de\s+)?", "", rest)
            rest = re.sub(r"^(?:de\s+)", "", rest)
            if rest and len(rest) > 1:
                return {"action": "queue_music", "query": rest}

        # "encola X" / "agrega X a la cola" / "agrégala X" / "mete X" / etc.
        # Acepta sufijos "-la/-lo/-me" pegados al verbo (agrégala, encolalo, metelo)
        queue_match2 = re.match(
            r"^(?:encola(?:la|lo|me)?|agrega(?:la|lo|me)?|agregar|"
            r"mete(?:la|lo|me)?|meter|"
            r"poneme|poneles|ponele|ponle)\s+(.+?)$",
            cmd,
        )
        if queue_match2:
            rest = queue_match2.group(1).strip()
            # Quitar "a la cola" / "en cola" sea al principio o al final
            rest = re.sub(r"\s+(?:a\s+la\s+cola|en\s+la\s+cola|en\s+cola)$", "", rest)
            rest = re.sub(r"^(?:a\s+(?:la\s+)?cola\s+|en\s+(?:la\s+)?cola\s+)", "", rest)
            rest = re.sub(r"^(?:la|el|un|una|los|las)\s+", "", rest)
            rest = re.sub(r"^(?:musica|cancion|tema|rola)\s*(?:de\s+)?", "", rest)
            rest = rest.strip()
            if rest and len(rest) > 1:
                return {"action": "queue_music", "query": rest}

        # ── Atajo: si menciona "a la cola" o "en cola" en cualquier parte,
        # tratarlo como queue_music aunque el verbo principal sea "pon" o "metele"
        if re.search(r"\b(?:a\s+la\s+cola|en\s+la\s+cola|en\s+cola|a\s+cola)\b", cmd):
            song = re.sub(
                r"^(?:metele|metelo|metela|metelos|metelas|mete|"
                r"pon|ponme|ponle|ponele|coloca|colocame|"
                r"echa|echame|tira|tirame|dame|"
                r"reproduce|reproduceme|reproducir|play|"
                r"encola(?:la|lo|me)?|agrega(?:la|lo|me)?|agregar)\s+",
                "", cmd,
            )
            song = re.sub(r"\s*\b(?:a\s+la\s+cola|en\s+la\s+cola|en\s+cola|a\s+cola)\b\s*", " ", song).strip()
            song = re.sub(r"^(?:la|el|un|una|los|las)\s+", "", song)
            song = re.sub(r"^(?:musica|cancion|tema|rola|track)\s*(?:de\s+)?", "", song)
            song = song.strip()
            if song and len(song) > 1:
                return {"action": "queue_music", "query": song}

        # ── Música: poner canción (con extracción del título) ─────────────
        play_verbs = [
            "ponme", "pon", "pone", "poner", "ponle", "ponele",
            "reproduce", "reproduceme", "reproducir", "play",
            "coloca", "colocame", "colocar",
            "echa", "echame",
            "tira", "tirame",
            "pongamos", "escuchemos",
            "quiero escuchar", "quiero oir", "quisiera escuchar",
            "metele", "metele con",
            "dame", "dame con", "con",
        ]
        for verb in play_verbs:
            if cmd == verb or cmd.startswith(verb + " "):
                rest = cmd[len(verb):].strip()
                # Limpiar palabras de relleno al inicio
                rest = re.sub(r"^(?:me\s+)?", "", rest)
                rest = re.sub(r"^(?:la|el|un|una|los|las|algo\s+de)\s+", "", rest)
                rest = re.sub(r"^(?:musica|cancion|tema|rola|track|tonada|nota)\s*(?:de\s+)?", "", rest)
                rest = re.sub(r"^(?:de\s+)", "", rest)
                rest = re.sub(r"\s*(?:por\s+favor|porfa|porfis)\s*$", "", rest)
                # Si termina con "a la cola" → es queue_music
                if re.search(r"\s+a\s+la\s+cola$", rest):
                    rest = re.sub(r"\s+a\s+la\s+cola$", "", rest).strip()
                    if rest and len(rest) > 1:
                        return {"action": "queue_music", "query": rest}
                rest = rest.strip()
                if rest and len(rest) > 1 and rest not in ("musica", "cancion", "tema", "algo", "rola"):
                    return {"action": "play_music", "query": rest}
                # Si solo dijo el verbo sin canción → preguntará
                return {"action": "play_music"}

        # ── Música: skip / siguiente ──────────────────────────────────────
        if any(w in cmd for w in [
            "siguiente musica", "siguiente cancion", "siguiente tema", "siguiente",
            "skip", "saltar cancion", "saltar la cancion", "saltala", "saltalo",
            "salta esta", "salta la cancion", "salta",
            "pasala", "pasalo", "pasa la cancion", "pasa esta",
            "cambiala", "cambialo", "cambia la cancion", "cambia esta", "cambia de cancion",
            "otra", "otra cancion", "otra rola", "ponme otra", "pon otra",
            "next", "next song", "no me gusta esta",
        ]):
            return {"action": "skip_music"}

        # ── Música: stop completo ─────────────────────────────────────────
        if any(w in cmd for w in [
            "detener musica", "deten musica", "deten la musica", "detenga musica", "detenga la musica",
            "parar musica", "para la musica", "para musica", "pare la musica", "pare musica",
            "stop musica", "stop la musica",
            "quita la musica", "quita musica", "quitala",
            "apaga la musica", "apaga musica", "apagala",
            "termina la musica", "termina musica", "ya no quiero musica",
            "corta la musica", "corta musica",
        ]):
            return {"action": "stop_music"}

        # ── Música: pausa ─────────────────────────────────────────────────
        if any(w in cmd for w in [
            "pausa la musica", "pausa musica", "pausar musica", "pausa",
            "pausala", "pausalo",
            "frena la musica", "frena musica", "frenala",
            "espera la musica", "ponle pausa",
        ]):
            return {"action": "pause_music"}

        # ── Música: reanudar ──────────────────────────────────────────────
        if any(w in cmd for w in [
            "reanuda musica", "reanuda la musica", "reanudala",
            "continua musica", "continua la musica", "continuala",
            "sigue la musica", "sigue con la musica", "sigue musica", "sigue",
            "resume", "dale play", "vuelve a poner", "vuelve a la musica",
            "quita la pausa", "quitale la pausa",
        ]):
            return {"action": "resume_music"}

        # ── Música: estado / nombre canción actual ────────────────────────
        if any(w in cmd for w in [
            "que esta sonando", "que cancion es", "que cancion es esta",
            "que suena", "que estoy escuchando",
            "cancion actual", "tema actual",
            "como se llama esta", "como se llama la cancion",
            "que tema es", "cual es esta cancion", "cual cancion es",
        ]):
            return {"action": "music_status"}

        # ── Música: eliminar SOLO la última canción de la cola ────────────
        if re.search(
            r"\b(elimina|eliminar|borra|borrar|quita|quitar|saca|sacar|"
            r"elimino|elimine|elimino|borro|quito|saco)\s+"
            r"(?:la\s+)?ultima\b", cmd):
            return {"action": "remove_last"}
        if any(w in cmd for w in [
            "quita esa cancion", "quita esa", "saca esa cancion",
            "borra esa cancion", "elimina esa cancion",
            "elimina la cancion que acabo", "saca la ultima",
        ]):
            return {"action": "remove_last"}

        # ── Música: limpiar cola completa ─────────────────────────────────
        if any(w in cmd for w in [
            "limpia la cola", "limpiar cola", "limpia cola",
            "limpia la lista", "limpiar lista", "limpia lista",
            "vacia la cola", "vaciar cola", "vacia cola",
            "vacia la lista", "vaciar lista", "vacia lista",
            "borra la cola", "borrar cola", "borra cola",
            "borra la lista", "borrar lista", "borra lista",
            "quita la cola", "quitar la cola",
            "quita la lista", "quitar la lista",
            "quita todo de la cola", "quita todas las canciones de la cola",
            "quita todas las canciones en cola", "quita las canciones de la cola",
            "elimina la cola", "eliminar cola", "elimina cola",
            "elimina la lista", "eliminar lista", "elimina lista",
            "elimino la lista", "eliminó la lista", "eligio la lista",
            "eliminan la lista", "eliminan la cola",
        ]):
            return {"action": "clear_queue"}

        # ── Música: bot fuera del canal ───────────────────────────────────
        if any(w in cmd for w in [
            "sal del canal", "desconecta bot", "sal de la voz",
            "vete del canal", "vete", "desconectate", "salte del canal",
        ]):
            return {"action": "disconnect_music"}

        # ── Salir del asistente ───────────────────────────────────────────
        if any(w in cmd for w in [
            "salir", "cerrar", "terminar", "apagate", "duermete",
            "adios", "hasta luego", "chao", "chau", "nos vemos",
            "buenas noches",
        ]):
            return {"action": "exit"}

        # ── Ayuda ─────────────────────────────────────────────────────────
        if any(w in cmd for w in [
            "ayuda", "help", "que puedo decir", "comandos",
            "que sabes hacer", "que puedes hacer", "como te uso", "que haces",
        ]):
            return {"action": "help"}

        # ── Interrupción durante el habla ─────────────────────────────────
        if any(w in cmd for w in ["para", "stop", "alto", "basta", "detente", "espera", "calla"]):
            return {"action": "interrupt"}

        # ── Discord (mensaje de texto) ────────────────────────────────────
        if any(w in cmd for w in [
            "escribir en discord", "mensaje en discord", "enviar mensaje",
            "manda mensaje", "mandar mensaje", "manda un mensaje",
        ]):
            if "musica" not in cmd and "play" not in cmd:
                return {"action": "write_discord"}

        # Fallback: el activador está pero no coincidió con ningún verbo conocido.
        # Solo asumimos play_music si lo que sigue parece UN TÍTULO real:
        #   - 2+ palabras, O
        #   - 1 palabra de 5+ caracteres
        # Esto evita falsos positivos como "rodolfo no" → reproduce "No"
        if cmd:
            words = cmd.split()
            looks_like_title = (
                len(words) >= 2
                or (len(words) == 1 and len(cmd) >= 5)
            )
            # Filler/interjecciones que NO son títulos
            filler = {
                "hola", "buenas", "alo", "oye", "hey", "rodolfo",
                "no", "si", "sí", "ya", "ah", "eh", "ok", "vale",
                "bueno", "buena", "claro", "obvio", "tal", "y",
                "que", "qué", "como", "cómo", "donde", "dónde",
                "este", "esa", "ese", "aja", "ajá", "ahá", "mhm",
                "uno", "dos", "tres", "uy", "ay",
            }
            if looks_like_title and cmd not in filler:
                return {"action": "play_music", "query": cmd}

        return {"action": "unknown"}

    # ─────────────────────────────────────────────────────────────────────────
    # Métricas de rendimiento
    # ─────────────────────────────────────────────────────────────────────────

    def _record_cmd(self, raw: str, action: str, query: str = ""):
        """Calcula latencias y las guarda en performance_log.jsonl + consola."""
        t0   = self._t_listen_start
        t_st = self._t_stt_done
        t_sp = self._t_first_speak
        stt_ms   = int((t_st - t0) * 1000) if t_st > t0 else 0
        first_ms = int((t_sp - t_st) * 1000) if t_sp else None
        _log_perf(raw, action, stt_ms, first_ms, query)
        rsp = f"rsp={first_ms}ms" if first_ms is not None else "rsp=—"
        print(f"[PERF] stt={stt_ms}ms | {rsp} | {action}" + (f" | '{query[:40]}'" if query else ""))

    # ─────────────────────────────────────────────────────────────────────────
    # Ayuda
    # ─────────────────────────────────────────────────────────────────────────

    def show_help(self):
        self.speak(
            "Llámame con Oye Rodolfo antes de cualquier comando. "
            "Para música: Oye Rodolfo pon despacito, Oye Rodolfo pásala, Oye Rodolfo pausa, "
            "Oye Rodolfo sigue, Oye Rodolfo qué está sonando, Oye Rodolfo detén la música. "
            "Para encolar: Oye Rodolfo después pon X, Oye Rodolfo limpia la cola. "
            "Funciona con YouTube y enlaces de Spotify. "
            "Para volumen: Oye Rodolfo sube el volumen, Oye Rodolfo bájale, Oye Rodolfo silencio. "
            "Para cerrar: Oye Rodolfo adiós.",
            can_interrupt=True,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Discord
    # ─────────────────────────────────────────────────────────────────────────

    def _discord_post(self, content):
        if not self.DISCORD_WEBHOOK_URL:
            self.speak("No hay webhook de Discord configurado en el archivo .env.", can_interrupt=False)
            return False
        try:
            r = requests.post(self.DISCORD_WEBHOOK_URL, json={"content": content}, timeout=5)
            return r.status_code == 204
        except requests.Timeout:
            self.speak("Discord tardó demasiado.", can_interrupt=False)
            return False
        except Exception as e:
            print(f"[DISCORD ERROR] {e}")
            return False

    # ── Música vía bot local ─────────────────────────────────────────────────

    def _music_bot(self, method, path, data=None):
        try:
            url = f"{self.MUSIC_BOT_URL}{path}"
            headers = self._auth_headers()
            if method == "POST":
                r = requests.post(url, json=data or {}, headers=headers, timeout=30)
            else:
                r = requests.get(url, headers=headers, timeout=10)
            return r.json()
        except requests.ConnectionError:
            return {"error": "bot offline"}
        except Exception as e:
            return {"error": str(e)}

    def play_music(self, query=None, queue_intent=False):
        # Si no vino con la canción en el comando, preguntamos
        if not query:
            self.speak("¿Qué música quieres?", can_interrupt=False)
            query = self.listen_command(timeout=10)
            if not query:
                self.speak("No escuché la música.", can_interrupt=False)
                return

        # ── Si menciona "playlist" sin URL → buscar entre las guardadas ──
        query_lower = query.lower()
        if "playlist" in query_lower and "http" not in query_lower:
            matched = None
            for name, url in self.playlists.items():
                if name in query_lower:
                    matched = (name, url)
                    break
            if matched:
                name, url = matched
                self.speak(f"Poniendo tu playlist {name}, un momento.", can_interrupt=False)
                query = url
            else:
                if self.playlists:
                    names = ", ".join(self.playlists.keys())
                    self.speak(f"No tengo esa playlist. Las guardadas son: {names}.", can_interrupt=False)
                else:
                    self.speak(
                        "No tengo playlists guardadas. Para usarlas, agrega PLAYLIST_NOMBRE=URL en tu archivo de configuración.",
                        can_interrupt=False, broadcast=False,
                    )
                return
        else:
            # Feedback inmediato: ultra-corto para que el usuario sepa que Rodolfo
            # lo escuchó ANTES de que empiece la búsqueda (1-3s de silencio).
            self.speak("Un momento.", can_interrupt=False)

        result = self._music_bot("POST", "/play", {"query": query})
        if result.get("ok"):
            self.play_chime("success")
            titles      = result.get("added", [])
            started_now = result.get("started_now", False)
            queue_size  = result.get("queue_size", 0)

            if len(titles) == 1:
                if started_now:
                    self.speak(R.music_started_short(), can_interrupt=False)
                else:
                    self.speak(R.music_queued_short(), can_interrupt=False)
            elif len(titles) > 1:
                if started_now:
                    self.speak(R.music_multiple_queued(len(titles), first_title=titles[0]), can_interrupt=False)
                else:
                    self.speak(R.music_multiple_queued(len(titles)), can_interrupt=False)
        else:
            self.play_chime("error")
            err = result.get("error", "")
            if "offline" in err:
                self.speak(R.error_bot_offline(), can_interrupt=False)
            elif "canal de voz" in err:
                self.speak(R.error_no_voice_channel(), can_interrupt=False)
            else:
                self.speak(R.error_generic(), can_interrupt=False)

    def skip_music(self):
        if self._music_bot("POST", "/skip").get("ok"):
            self.play_chime("success")
            self.speak(R.music_skipped(), can_interrupt=False)
        else:
            self.play_chime("error")
            self.speak(R.error_generic(), can_interrupt=False)

    def stop_music(self):
        if self._music_bot("POST", "/stop").get("ok"):
            self.play_chime("success")
            self.speak(R.music_stopped(), can_interrupt=False)
        else:
            self.play_chime("error")
            self.speak(R.error_generic(), can_interrupt=False)

    def pause_music(self):
        if self._music_bot("POST", "/pause").get("ok"):
            self.play_chime("success")
            self.speak(R.music_paused(), can_interrupt=False)
        else:
            self.play_chime("error")
            self.speak(R.error_pause_nothing(), can_interrupt=False)

    def resume_music(self):
        if self._music_bot("POST", "/resume").get("ok"):
            self.play_chime("success")
            self.speak(R.music_resumed(), can_interrupt=False)
        else:
            self.play_chime("error")
            self.speak(R.error_resume_nothing(), can_interrupt=False)

    def music_status(self):
        result = self._music_bot("GET", "/status")
        if "error" in result:
            self.speak(R.error_bot_offline(), can_interrupt=False)
            return
        current = result.get("current")
        queue_len = len(result.get("queue", []))
        if current:
            msg = R.music_status(current[:60])
            if queue_len:
                msg += f" Hay {queue_len} en cola."
            self.speak(msg, can_interrupt=False)
        else:
            self.speak(R.music_status_nothing(), can_interrupt=False)

    def disconnect_music(self):
        result = self._music_bot("POST", "/disconnect")
        if result.get("ok"):
            self.play_chime("success")
            self.speak(R.disconnected(), can_interrupt=False)
        else:
            self.play_chime("error")
            self.speak(R.error_generic(), can_interrupt=False)

    def clear_queue(self):
        result = self._music_bot("POST", "/clear_queue")
        if result.get("ok"):
            self.play_chime("success")
            n = result.get("cleared", 0)
            self.speak(R.queue_cleared(n), can_interrupt=False)
        else:
            self.play_chime("error")
            self.speak("No pude limpiar la cola.", can_interrupt=False)

    def remove_last(self):
        result = self._music_bot("POST", "/remove_last")
        if result.get("ok"):
            self.play_chime("success")
            removed = result.get("removed")
            self.speak(R.queue_last_removed(removed), can_interrupt=False)
        else:
            self.play_chime("error")
            self.speak(R.queue_empty_remove(), can_interrupt=False)

    def write_discord_message(self):
        self.speak("¿Qué quieres escribir?", can_interrupt=False)
        msg = self.listen_command(timeout=10)
        if not msg:
            self.speak("No escuché ningún mensaje.", can_interrupt=False)
            return
        if self._discord_post(msg):
            self.speak("Mensaje enviado.", can_interrupt=False)
        else:
            self.speak("No pude enviar el mensaje.", can_interrupt=False)

    # ─────────────────────────────────────────────────────────────────────────
    # Bucle principal
    # ─────────────────────────────────────────────────────────────────────────

    def run(self):
        self.speak(R.greet_initial(), can_interrupt=False)

        # Watchdog: si pasan más de N segundos SIN que llegue audio al queue
        # (no cuenta los casos en que llega audio pero el STT no entiende)
        # el background listener probablemente murió.
        _WATCHDOG_SECS = 300   # 5 minutos sin NINGÚN audio en el mic → restart

        while True:
            try:
                if self.wake_model:
                    self.wait_for_wake_word()
                    self.speak(R.greet_reply(), can_interrupt=False)
                    self.last_activator_time = time.time()

                cmd = self.listen_command()
                if not cmd:
                    # Solo disparar si pasó mucho tiempo sin que el queue reciba audio
                    # (el timestamp se actualiza en listen_command cada vez que llega audio)
                    secs_silent = time.time() - self._last_audio_ts
                    if secs_silent > _WATCHDOG_SECS:
                        print(f"[WATCHDOG] {secs_silent:.0f}s sin audio del mic — reiniciando listener...")
                        self._ov("error")
                        self._restart_background_listener()
                        self._last_audio_ts = time.time()   # reset para no disparar de nuevo
                        time.sleep(1)
                        self._ov("idle")
                    continue

                self._t_first_speak = None   # reset para este ciclo
                parsed = self.parse_command(cmd)
                action = parsed["action"]

                # Sin el activador "Rodolfo" → ignoramos en silencio o usamos la memoria
                if action == "ignored":
                    if time.time() - self.last_activator_time < self.ACTIVATOR_TIMEOUT:
                        cmd_with_act = f"oye rodolfo {cmd}"
                        print(f"  └─ [COMPLETADO CON MEMORIA] -> '{cmd_with_act}'")
                        parsed = self.parse_command(cmd_with_act)
                        action = parsed["action"]
                        self.last_activator_time = 0.0  # Usar y consumir
                    else:
                        print(f"[IGNORADO] sin activador -> '{cmd}'")
                        self.last_activator_time = 0.0
                        self._record_cmd(cmd, "ignored")
                        continue

                # Resetear la memoria tras una acción real distinta de saludar
                if action != "greet":
                    self.last_activator_time = 0.0

                print(f"[ACCIÓN] {action}")

                # Debounce: bloquea la misma acción si se repite muy rápido (spam de voz)
                _DEBOUNCE_ACTIONS = {"skip_music", "stop_music", "pause_music", "resume_music"}
                if action in _DEBOUNCE_ACTIONS:
                    _now = time.time()
                    _last = self._debounce.get(action, 0.0)
                    if _now - _last < self._debounce_secs:
                        print(f"[DEBOUNCE] '{action}' ignorado ({_now - _last:.1f}s — espera {self._debounce_secs}s)")
                        self._record_cmd(cmd, f"debounced_{action}")
                        continue
                    self._debounce[action] = _now

                if action == "greet":
                    self.speak(R.greet_reply(), can_interrupt=False)
                    self.last_activator_time = time.time()
                    self._record_cmd(cmd, "greet")
                    continue

                if action == "exit":
                    self.speak(R.goodbye(), can_interrupt=False)
                    self._record_cmd(cmd, "exit")
                    break

                elif action == "volume_up":
                    self.volume_up()
                elif action == "volume_down":
                    self.volume_down()
                elif action == "volume_mute":
                    self.volume_mute()
                elif action == "volume_set":
                    self.volume_set(parsed["level"])

                elif action == "interrupt":
                    self.speak("¿Qué necesitas?", can_interrupt=False)

                elif action == "help":
                    self.show_help()

                elif action == "write_discord":
                    self.write_discord_message()
                elif action == "play_music":
                    self.play_music(parsed.get("query"))
                elif action == "queue_music":
                    self.play_music(parsed.get("query"), queue_intent=True)
                elif action == "skip_music":
                    self.skip_music()
                elif action == "stop_music":
                    self.stop_music()
                elif action == "pause_music":
                    self.pause_music()
                elif action == "resume_music":
                    self.resume_music()
                elif action == "music_status":
                    self.music_status()
                elif action == "disconnect_music":
                    self.disconnect_music()
                elif action == "clear_queue":
                    self.clear_queue()
                elif action == "remove_last":
                    self.remove_last()

                else:
                    # No entendido → no spameamos a Discord, solo respondemos local
                    self.play_chime("error")
                    self.speak("No entendí. Di ayuda para ver los comandos.", can_interrupt=True, broadcast=False)

                # Log de rendimiento para todas las acciones que llegan hasta aquí
                self._record_cmd(cmd, action, parsed.get("query", ""))

            except KeyboardInterrupt:
                self.speak(R.goodbye(), can_interrupt=False)
                break
            except Exception as e:
                print(f"[ERROR BUCLE] {e}")
                self.speak("Ocurrió un error. Reintentando.", can_interrupt=False)
                time.sleep(1)


if __name__ == "__main__":
    controller = VoiceAudioController()
    controller.run()
