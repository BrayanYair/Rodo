"""
wakeword_engine.py — Motor de detección de wake word para Byarox.

Modos de operación:
  1. Verifier (pkl): usa embedding_model.onnx de openwakeword + clasificador sklearn pkl.
  2. Fallback: usa hey_jarvis_v0.1 con threshold=0.3 directamente.

Uso:
    engine = WakeWordEngine(callback=my_cb)
    engine.start()
    # ... esperar detecciones ...
    engine.stop()
"""

import os
import sys
import threading
import logging
import traceback
from typing import Callable, Optional

import numpy as np

logger = logging.getLogger(__name__)

# Directorio base del módulo (compatible con PyInstaller frozen)
if getattr(sys, "frozen", False):
    _MODULE_DIR = os.path.join(sys._MEIPASS, "modules", "wakeword")
else:
    _MODULE_DIR = os.path.dirname(os.path.abspath(__file__))

_VERIFIER_PATH = os.path.join(_MODULE_DIR, "byarox_verifier.pkl")

# Parámetros de audio
_SAMPLE_RATE = 16000
_CHUNK_SAMPLES = 1280  # 80 ms a 16kHz


def _load_pyaudio():
    """Importa PyAudio, retorna None si no está disponible."""
    try:
        import pyaudio
        return pyaudio
    except ImportError:
        logger.error("PyAudio no está instalado.")
        return None


def _load_openwakeword_model(wakeword_name: str):
    """Carga un modelo de openwakeword. Retorna None si falla."""
    try:
        from openwakeword.model import Model
        model = Model(wakeword_models=[wakeword_name], inference_framework="onnx")
        return model
    except Exception as e:
        logger.error(f"No se pudo cargar openwakeword model '{wakeword_name}': {e}")
        return None


def _load_verifier(pkl_path: str):
    """Carga el clasificador sklearn desde pickle. Retorna None si falla."""
    try:
        import pickle
        with open(pkl_path, "rb") as f:
            clf = pickle.load(f)
        logger.info(f"Verifier cargado desde {pkl_path}")
        return clf
    except Exception as e:
        logger.warning(f"No se pudo cargar verifier pkl: {e}")
        return None


class WakeWordEngine:
    """
    Motor de detección de wake word.

    Parámetros:
        callback: función llamada cuando se detecta el wake word.
                  Recibe (score: float, label: str).
        model_path: ruta al pkl del verifier. Si es None usa _VERIFIER_PATH por defecto.
        threshold: score mínimo para disparar el callback en modo fallback.
    """

    def __init__(
        self,
        callback: Callable[[float, str], None],
        model_path: Optional[str] = None,
        threshold: float = 0.3,
    ):
        self._callback = callback
        self._threshold = threshold
        self._model_path = model_path if model_path is not None else _VERIFIER_PATH
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        # Determinar modo de operación
        self._use_verifier = os.path.isfile(self._model_path)
        if self._use_verifier:
            logger.info("WakeWordEngine: modo VERIFIER (pkl)")
        else:
            logger.info("WakeWordEngine: modo FALLBACK (hey_jarvis threshold=0.3)")

    @property
    def is_running(self) -> bool:
        """True si el hilo de escucha está activo."""
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        """Inicia la escucha en un hilo daemon."""
        if self.is_running:
            logger.warning("WakeWordEngine ya está corriendo.")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="WakeWordThread")
        self._thread.start()
        logger.info("WakeWordEngine iniciado.")

    def stop(self):
        """Detiene la escucha. Bloquea hasta que el hilo termina (máx 3s)."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None
        logger.info("WakeWordEngine detenido.")

    # ------------------------------------------------------------------
    # Loop principal
    # ------------------------------------------------------------------

    def _run_loop(self):
        """Loop de captura y detección. Corre en hilo daemon."""
        pyaudio = _load_pyaudio()
        if pyaudio is None:
            logger.error("WakeWordEngine: PyAudio no disponible, hilo terminado.")
            return

        # Cargar modelo openwakeword (siempre necesario para embeddings)
        oww_model = _load_openwakeword_model("hey_jarvis_v0.1")
        if oww_model is None:
            logger.error("WakeWordEngine: openwakeword no disponible, hilo terminado.")
            return

        # Cargar verifier si corresponde
        verifier = None
        if self._use_verifier:
            verifier = _load_verifier(self._model_path)
            if verifier is None:
                logger.warning("WakeWordEngine: pkl no cargó, usando fallback.")
                self._use_verifier = False

        # Abrir stream PyAudio
        pa = pyaudio.PyAudio()
        stream = None
        try:
            stream = pa.open(
                rate=_SAMPLE_RATE,
                channels=1,
                format=pyaudio.paInt16,
                input=True,
                frames_per_buffer=_CHUNK_SAMPLES,
            )
            logger.info("WakeWordEngine: stream PyAudio abierto.")
            self._detection_loop(stream, oww_model, verifier)
        except Exception as e:
            logger.error(f"WakeWordEngine error de stream: {e}\n{traceback.format_exc()}")
        finally:
            try:
                if stream is not None:
                    stream.stop_stream()
                    stream.close()
            except Exception:
                pass
            try:
                pa.terminate()
            except Exception:
                pass
            logger.info("WakeWordEngine: stream cerrado.")

    def _detection_loop(self, stream, oww_model, verifier):
        """Loop de lectura y predicción sobre el stream abierto."""
        while not self._stop_event.is_set():
            try:
                raw = stream.read(_CHUNK_SAMPLES, exception_on_overflow=False)
            except Exception as e:
                logger.debug(f"WakeWordEngine read error: {e}")
                continue

            audio_int16 = np.frombuffer(raw, dtype=np.int16)

            if self._use_verifier and verifier is not None:
                # Extraer embeddings con openwakeword y clasificar
                score, label = self._predict_verifier(audio_int16, oww_model, verifier)
            else:
                # Modo fallback: usar score nativo de hey_jarvis
                score, label = self._predict_fallback(audio_int16, oww_model)

            if score >= self._threshold:
                try:
                    self._callback(score, label)
                except Exception as e:
                    logger.error(f"WakeWordEngine callback error: {e}")

    def _predict_fallback(self, audio_int16: np.ndarray, oww_model) -> tuple:
        """Modo fallback: usa score nativo de hey_jarvis_v0.1."""
        try:
            # openwakeword.predict espera int16 o float32
            prediction = oww_model.predict(audio_int16)
            # prediction es dict: {model_name: score}
            scores = list(prediction.values())
            score = float(max(scores)) if scores else 0.0
            return score, "byarox"
        except Exception as e:
            logger.debug(f"_predict_fallback error: {e}")
            return 0.0, "byarox"

    def _predict_verifier(self, audio_int16: np.ndarray, oww_model, verifier) -> tuple:
        """
        Extrae embeddings con openwakeword y clasifica con el verifier pkl.

        Usa el mismo método que train_byarox.py:
          oww_model.predict(chunk) → actualiza el preprocessor interno
          oww_model.preprocessor.get_features(16) → shape (1, 16, 96)
          flatten → (1, 1536) → LogisticRegression → proba clase 1
        """
        try:
            oww_model.predict(audio_int16)

            # Mismo método que el entrenamiento: get_features(16) → (1, 16, 96)
            feats = oww_model.preprocessor.get_features(16)
            if feats is None or feats.shape[1] != 16:
                return 0.0, "byarox"

            emb_flat = feats.reshape(1, -1).astype(np.float32)  # (1, 1536)

            if hasattr(verifier, "predict_proba"):
                proba = verifier.predict_proba(emb_flat)
                classes = list(verifier.classes_)
                idx = classes.index(1) if 1 in classes else -1
                score = float(proba[0][idx])
            else:
                score = float(verifier.predict(emb_flat)[0])

            return score, "byarox"
        except Exception as e:
            logger.debug(f"_predict_verifier error: {e}")
            return 0.0, "byarox"
