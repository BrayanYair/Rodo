"""
vad_engine.py — Voice Activity Detection usando Silero VAD v4 con onnxruntime.

Clases principales:
  - SileroVAD: wrapper del modelo ONNX. Predice probabilidad de voz por chunk de 512 samples.
  - SpeechSegmenter: alimenta chunks de SileroVAD y devuelve segmentos completos de habla.

El modelo se descarga automáticamente si no existe en el directorio del módulo.
"""

import os
import sys
import logging
import urllib.request
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# Directorio base del módulo (compatible con PyInstaller frozen)
if getattr(sys, "frozen", False):
    _MODULE_DIR = os.path.join(sys._MEIPASS, "modules", "vad")
else:
    _MODULE_DIR = os.path.dirname(os.path.abspath(__file__))

_MODEL_PATH = os.path.join(_MODULE_DIR, "silero_vad.onnx")
_MODEL_URL = (
    "https://raw.githubusercontent.com/snakers4/silero-vad/"
    "master/src/silero_vad/data/silero_vad.onnx"
)

# Silero VAD v4 espera chunks de 512 samples a 16kHz
_VAD_CHUNK_SAMPLES = 512


def _download_model(url: str, dest: str):
    """Descarga el modelo ONNX desde la URL si no existe."""
    if os.path.isfile(dest):
        return
    logger.info(f"Descargando Silero VAD desde {url} ...")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    try:
        urllib.request.urlretrieve(url, dest)
        logger.info(f"Modelo guardado en {dest}")
    except Exception as e:
        logger.error(f"No se pudo descargar el modelo VAD: {e}")
        raise


class SileroVAD:
    """
    Wrapper de Silero VAD v4 sobre onnxruntime.

    Parámetros:
        threshold:    Umbral de probabilidad para clasificar como voz (0-1).
        sample_rate:  Frecuencia de muestreo esperada (16000 Hz).
    """

    # Muestras de "contexto" (cola del chunk anterior) que el modelo v5
    # necesita pegadas antes de cada chunk nuevo. Sin esto el modelo
    # devuelve ~0 siempre, tenga voz real o no (no tira error, da resultados
    # silenciosamente incorrectos).
    _CONTEXT_SAMPLES = 64

    def __init__(self, threshold: float = 0.5, sample_rate: int = 16000):
        self.threshold = threshold
        self.sample_rate = sample_rate
        self._session = None
        self._legacy_io = False  # True = firma vieja (h/c separados), False = 'state' combinado
        self._h = None
        self._c = None
        self._state = None
        self._context = None
        self._load_model()

    def _load_model(self):
        """Descarga (si hace falta) y carga el modelo ONNX."""
        _download_model(_MODEL_URL, _MODEL_PATH)
        try:
            import onnxruntime as ort
            opts = ort.SessionOptions()
            opts.inter_op_num_threads = 1
            opts.intra_op_num_threads = 1
            opts.log_severity_level = 3  # suprimir warnings de ONNX
            self._session = ort.InferenceSession(_MODEL_PATH, sess_options=opts)
            # Silero VAD cambió su firma ONNX entre versiones: v4 usa "h"/"c"
            # separados (64 unidades), v5+ usa un único "state" (128 unidades).
            # Detectamos cuál tiene el modelo descargado para no romper con
            # actualizaciones futuras del archivo (se baja de "master").
            input_names = {i.name for i in self._session.get_inputs()}
            self._legacy_io = "h" in input_names and "c" in input_names
            logger.info(
                f"SileroVAD: modelo cargado (firma {'legacy h/c' if self._legacy_io else 'state'})."
            )
        except Exception as e:
            logger.error(f"SileroVAD: no se pudo cargar el modelo: {e}")
            self._session = None
        self.reset()

    def reset(self):
        """Resetea el estado interno del modelo recurrente."""
        self._h = np.zeros((2, 1, 64), dtype=np.float32)
        self._c = np.zeros((2, 1, 64), dtype=np.float32)
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros(self._CONTEXT_SAMPLES, dtype=np.float32)

    def predict(self, chunk: np.ndarray) -> float:
        """
        Predice la probabilidad de voz para un chunk de audio.

        Parámetros:
            chunk: array de 512 samples. Puede ser int16 o float32.
                   Si es int16, se normaliza dividiendo por 32768.

        Retorna:
            Probabilidad de voz en [0, 1]. Retorna 0.0 si el modelo no está disponible.
        """
        if self._session is None:
            return 0.0

        try:
            # Normalizar a float32 [-1, 1]
            if chunk.dtype == np.int16:
                audio_f32 = chunk.astype(np.float32) / 32768.0
            elif chunk.dtype != np.float32:
                audio_f32 = chunk.astype(np.float32)
            else:
                audio_f32 = chunk

            # Asegurar longitud exacta de 512 samples
            if len(audio_f32) < _VAD_CHUNK_SAMPLES:
                audio_f32 = np.pad(audio_f32, (0, _VAD_CHUNK_SAMPLES - len(audio_f32)))
            elif len(audio_f32) > _VAD_CHUNK_SAMPLES:
                audio_f32 = audio_f32[:_VAD_CHUNK_SAMPLES]

            sr_input = np.array(self.sample_rate, dtype=np.int64)

            if self._legacy_io:
                # Shape: [1, 512]
                audio_input = audio_f32.reshape(1, _VAD_CHUNK_SAMPLES)
                feeds = {
                    "input": audio_input,
                    "sr": sr_input,
                    "h": self._h,
                    "c": self._c,
                }
                outputs = self._session.run(["output", "hn", "cn"], feeds)
                speech_prob = float(outputs[0].squeeze())
                self._h = outputs[1]
                self._c = outputs[2]
            else:
                # v5 espera el contexto (cola del chunk anterior) pegado
                # antes del chunk nuevo → shape [1, 64+512].
                windowed = np.concatenate([self._context, audio_f32])
                audio_input = windowed.reshape(1, -1)
                feeds = {
                    "input": audio_input,
                    "sr": sr_input,
                    "state": self._state,
                }
                outputs = self._session.run(["output", "stateN"], feeds)
                speech_prob = float(outputs[0].squeeze())
                self._state = outputs[1]
                self._context = audio_f32[-self._CONTEXT_SAMPLES:]

            return speech_prob

        except Exception as e:
            logger.debug(f"SileroVAD.predict error: {e}")
            return 0.0

    def is_speech(self, chunk: np.ndarray) -> bool:
        """Retorna True si el chunk contiene voz (score >= threshold)."""
        return self.predict(chunk) >= self.threshold


class SpeechSegmenter:
    """
    Acumula chunks de 512 samples y detecta segmentos completos de habla.

    La detección de fin de habla se basa en silencio sostenido >= silence_ms,
    o en alcanzar max_ms de audio acumulado.

    Parámetros:
        vad:         Instancia de SileroVAD.
        silence_ms:  Milisegundos de silencio para declarar fin de habla (default 1200).
        max_ms:      Milisegundos máximos de audio antes de forzar retorno (default 7000).
        sample_rate: Frecuencia de muestreo (default 16000).
    """

    def __init__(
        self,
        vad: SileroVAD,
        silence_ms: int = 1200,
        max_ms: int = 7000,
        sample_rate: int = 16000,
    ):
        self._vad = vad
        self._sample_rate = sample_rate
        self._silence_samples = int(silence_ms * sample_rate / 1000)
        self._max_samples = int(max_ms * sample_rate / 1000)
        self._buffer: list = []  # lista de np.ndarray chunks
        self._buffer_len = 0     # total de samples en buffer
        self._silence_len = 0    # samples de silencio consecutivo
        self._in_speech = False  # True si ya detectamos inicio de habla

    def reset(self):
        """Limpia el buffer y el estado interno."""
        self._buffer = []
        self._buffer_len = 0
        self._silence_len = 0
        self._in_speech = False
        self._vad.reset()

    def feed(self, chunk_512: np.ndarray) -> Optional[np.ndarray]:
        """
        Alimenta un chunk de 512 samples al segmentador.

        Retorna:
            np.ndarray con el audio acumulado (int16) cuando se detecta fin de habla,
            o None si sigue acumulando.
        """
        is_speech = self._vad.is_speech(chunk_512)

        if is_speech:
            self._in_speech = True
            self._silence_len = 0
            # Acumular en buffer
            self._buffer.append(chunk_512.copy())
            self._buffer_len += len(chunk_512)
        else:
            if self._in_speech:
                # Seguimos acumulando silencio post-habla
                self._buffer.append(chunk_512.copy())
                self._buffer_len += len(chunk_512)
                self._silence_len += len(chunk_512)
            # Si no hemos empezado a hablar, ignorar silencio inicial

        # Chequear condiciones de retorno
        should_return = False

        if self._in_speech and self._silence_len >= self._silence_samples:
            # Fin de habla: silencio sostenido suficiente
            should_return = True

        if self._buffer_len >= self._max_samples:
            # Tiempo máximo alcanzado
            should_return = True

        if should_return and self._buffer_len > 0:
            # Concatenar y retornar
            audio = np.concatenate(self._buffer)
            # Convertir a int16 si viene como float
            if audio.dtype == np.float32:
                audio = (audio * 32768).clip(-32768, 32767).astype(np.int16)
            elif audio.dtype != np.int16:
                audio = audio.astype(np.int16)
            self.reset()
            return audio

        return None
