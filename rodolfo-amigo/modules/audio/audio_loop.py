"""
audio_loop.py — Stream de audio siempre activo (full-duplex).

Combina detección de wake word + VAD en un único stream PyAudio 16kHz.
Cuando detecta "byarox" pone el segmento completo (pre-buffer + comando) en audio_queue.

Uso:
    loop = AudioLoop()
    loop.start(is_speaking_event=_is_speaking)
    audio_int16 = loop.audio_queue.get()   # np.ndarray[int16, 16kHz]
    loop.stop()
"""

import collections
import logging
import os
import queue
import sys
import threading

import numpy as np

logger = logging.getLogger(__name__)

SAMPLE_RATE  = 16_000
VAD_CHUNK    = 512          # Silero VAD: 32ms a 16kHz
OWW_CHUNK    = 1_280        # openwakeword: 80ms a 16kHz
RING_SECS    = 0.8          # pre-buffer — suficiente para capturar el inicio de "byarox"
RING_CHUNKS  = int(RING_SECS * SAMPLE_RATE / VAD_CHUNK)  # en chunks de 512 samples


def _find_verifier_pkl() -> str | None:
    """Busca byarox_verifier.pkl en source y modo frozen."""
    candidates = []

    # Modo fuente: modules/audio/ → modules/ → raíz del proyecto → modules/wakeword/
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(os.path.dirname(here))   # rodolfo-amigo/
    candidates.append(os.path.join(root, "modules", "wakeword", "byarox_verifier.pkl"))

    # Modo frozen (PyInstaller)
    if getattr(sys, "frozen", False):
        candidates.append(
            os.path.join(sys._MEIPASS, "modules", "wakeword", "byarox_verifier.pkl")
        )

    for p in candidates:
        if os.path.isfile(p):
            return p
    return None


class AudioLoop:
    """
    Stream PyAudio 16kHz continuo con dos fases:

    WAKE:    Escuchando wake word "byarox".
             Ring buffer de 0.8s activo para no perder el inicio del audio.

    CAPTURE: Wake word detectado.
             VAD (Silero) acumula el segmento de comando hasta silencio o tiempo máx.
             Entrega np.ndarray[int16] en audio_queue.

    Parámetros:
        wakeword_threshold: Score mínimo del clasificador para activar (0–1).
        vad_threshold:      Umbral de probabilidad de voz de Silero (0–1).
        silence_ms:         Silencio consecutivo para cortar el segmento.
        max_command_ms:     Duración máxima del segmento de comando.
    """

    def __init__(
        self,
        wakeword_threshold: float = 0.5,
        vad_threshold:      float = 0.5,
        silence_ms:         int   = 800,
        max_command_ms:     int   = 7_000,
    ):
        self.audio_queue       = queue.Queue()
        self._ww_threshold     = wakeword_threshold
        self._vad_threshold    = vad_threshold
        self._silence_ms       = silence_ms
        self._max_ms           = max_command_ms
        self._stop             = threading.Event()
        self._thread: threading.Thread | None = None
        self._is_speaking: threading.Event | None = None
        self._level_callback = None   # callable(level_0_a_1) — opcional

    # ─── API pública ───────────────────────────────────────────────────────────

    def start(self, is_speaking_event: threading.Event | None = None,
              level_callback=None):
        """Inicia el loop de audio en un hilo daemon.

        level_callback: opcional, recibe el nivel de volumen normalizado (0..1)
                        de cada chunk durante la captura del comando. Sirve para
                        que el overlay reaccione al volumen real. Falla en silencio.
        """
        self._is_speaking = is_speaking_event
        self._level_callback = level_callback
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="AudioLoop"
        )
        self._thread.start()
        logger.info("AudioLoop: iniciado.")

    def stop(self):
        """Detiene el loop y espera a que el hilo termine (máx 3s)."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None
        logger.info("AudioLoop: detenido.")

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ─── Loop interno ──────────────────────────────────────────────────────────

    def _run(self):
        try:
            import pyaudio
        except ImportError:
            logger.error("AudioLoop: pyaudio no disponible.")
            return

        try:
            from openwakeword.model import Model as OWWModel
            oww = OWWModel(
                wakeword_models=["hey_jarvis_v0.1"],
                inference_framework="onnx",
            )
        except Exception as e:
            logger.error(f"AudioLoop: openwakeword no disponible: {e}")
            return

        try:
            from modules.vad.vad_engine import SileroVAD
            vad = SileroVAD(threshold=self._vad_threshold)
        except Exception as e:
            logger.error(f"AudioLoop: SileroVAD no disponible: {e}")
            return

        # Cargar byarox_verifier.pkl (opcional — mejora precisión)
        verifier = None
        pkl_path = _find_verifier_pkl()
        if pkl_path:
            try:
                import pickle
                with open(pkl_path, "rb") as f:
                    verifier = pickle.load(f)
                logger.info(f"AudioLoop: verifier cargado ({pkl_path})")
            except Exception as e:
                logger.warning(f"AudioLoop: no se pudo cargar verifier: {e}")

        pa     = pyaudio.PyAudio()
        stream = None
        try:
            stream = pa.open(
                rate             = SAMPLE_RATE,
                channels         = 1,
                format           = pyaudio.paInt16,
                input            = True,
                frames_per_buffer= VAD_CHUNK,
            )
            logger.info("AudioLoop: stream abierto (512 samples/chunk, 16kHz).")
            self._detect_loop(stream, oww, verifier, vad)
        except Exception as e:
            logger.error(f"AudioLoop: error de stream: {e}")
        finally:
            if stream:
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception:
                    pass
            try:
                pa.terminate()
            except Exception:
                pass
            logger.info("AudioLoop: stream cerrado.")

    def _detect_loop(self, stream, oww, verifier, vad):
        from modules.vad.vad_engine import SpeechSegmenter

        ring       = collections.deque(maxlen=RING_CHUNKS)
        oww_buf    = np.array([], dtype=np.int16)   # acumulador para openwakeword
        mode       = "wake"
        segmenter  = None
        pre_buf    = []

        while not self._stop.is_set():
            try:
                raw = stream.read(VAD_CHUNK, exception_on_overflow=False)
            except Exception:
                continue

            chunk = np.frombuffer(raw, dtype=np.int16)

            # Nivel de volumen para el overlay (reactivo al micro).
            # En captura usa el RMS real; en wake reposa en 0.
            if self._level_callback is not None:
                try:
                    if mode == "capture":
                        rms = float(np.sqrt(np.mean((chunk.astype(np.float32) / 32768.0) ** 2)))
                        self._level_callback(min(1.0, rms * 6.0))
                    else:
                        self._level_callback(0.0)
                except Exception:
                    pass

            # ── WAKE: escuchando wake word ──────────────────────────────────
            if mode == "wake":
                ring.append(chunk.copy())

                # Acumular para openwakeword (~1280 samples por llamada)
                oww_buf = np.concatenate([oww_buf, chunk])
                if len(oww_buf) >= OWW_CHUNK:
                    feed    = oww_buf[:OWW_CHUNK]
                    oww_buf = oww_buf[OWW_CHUNK:]
                    score   = self._ww_score(feed, oww, verifier)

                    is_tts = (
                        self._is_speaking is not None and
                        self._is_speaking.is_set()
                    )

                    if score >= self._ww_threshold and not is_tts:
                        logger.info(
                            f"AudioLoop: wake word detectado (score={score:.2f})"
                        )
                        mode      = "capture"
                        vad.reset()
                        segmenter = SpeechSegmenter(
                            vad,
                            silence_ms = self._silence_ms,
                            max_ms     = self._max_ms,
                        )
                        pre_buf    = [c.copy() for c in ring]
                        oww_buf    = np.array([], dtype=np.int16)

            # ── CAPTURE: acumulando segmento de comando ─────────────────────
            elif mode == "capture":
                segment = segmenter.feed(chunk)
                if segment is not None:
                    # Ensamblar pre-buffer + segmento
                    if pre_buf:
                        full = np.concatenate(pre_buf + [segment])
                    else:
                        full = segment
                    self.audio_queue.put(full.astype(np.int16))
                    logger.info(
                        f"AudioLoop: segmento capturado "
                        f"({len(full)/SAMPLE_RATE:.2f}s, "
                        f"{len(full)} samples)"
                    )
                    mode      = "wake"
                    segmenter = None
                    pre_buf   = []
                    ring.clear()

    def _ww_score(self, chunk: np.ndarray, oww, verifier) -> float:
        """Calcula el score de wake word para un chunk de ~1280 samples."""
        prediction = oww.predict(chunk)     # actualiza estado interno + devuelve scores

        if verifier is not None:
            try:
                feats = oww.preprocessor.get_features(16)   # (1, 16, 96)
                if feats is not None and feats.shape[1] == 16:
                    emb    = feats.reshape(1, -1).astype(np.float32)  # (1, 1536)
                    proba  = verifier.predict_proba(emb)
                    classes = list(verifier.classes_)
                    idx    = classes.index(1) if 1 in classes else -1
                    return float(proba[0][idx])
            except Exception:
                pass

        # Fallback: score nativo de hey_jarvis
        scores = list(prediction.values())
        return float(max(scores)) if scores else 0.0
