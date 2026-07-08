"""
stt_engine.py — Motor de transcripción de voz con fallback local.

Primario:  Google Speech-to-Text (online, gratis vía SpeechRecognition)
Fallback:  faster-whisper (local, offline — requiere `pip install faster-whisper`)

Uso:
    engine = STTEngine(language="es-ES")
    text = engine.transcribe(audio_int16, sample_rate=16000)

    # Solo Whisper local:
    engine = STTEngine(language="es-ES", prefer_local=True)
"""

import logging
import socket

import numpy as np
import speech_recognition as sr

logger = logging.getLogger(__name__)

# Mapa de idioma a código de 2 letras para Whisper
_WHISPER_LANG = {
    "es-ES": "es", "es-MX": "es", "es-PE": "es", "es-AR": "es",
    "en-US": "en", "en-GB": "en",
    "pt-BR": "pt", "fr-FR": "fr", "de-DE": "de",
}


class STTEngine:
    """
    Motor de transcripción de voz.

    Toma np.ndarray[int16] a 16kHz mono (de AudioLoop o cualquier fuente)
    y retorna el texto transcripto como str. Retorna "" si no hay resultado.

    Parámetros:
        language:       Código BCP-47 (ej: "es-ES", "en-US").
        whisper_model:  Modelo de faster-whisper a usar ("tiny", "base", "small").
        prefer_local:   Si True, intenta Whisper primero y Google como fallback.
        google_timeout: Timeout de red para Google STT (segundos).
    """

    def __init__(
        self,
        language:       str   = "es-ES",
        whisper_model:  str   = "base",
        prefer_local:   bool  = False,
        google_timeout: float = 7.0,
    ):
        self._lang           = language
        self._whisper_model  = whisper_model
        self._prefer_local   = prefer_local
        self._google_timeout = google_timeout
        self._recognizer     = sr.Recognizer()
        self._whisper        = None
        self._whisper_tried  = False

    # ─── API pública ───────────────────────────────────────────────────────────

    def transcribe(self, audio_int16: np.ndarray, sample_rate: int = 16_000) -> str:
        """
        Transcribe audio int16 mono a texto.

        Con prefer_local=False (defecto):
          1. Google STT → fallback Whisper si hay error de red
        Con prefer_local=True:
          1. Whisper local → fallback Google si Whisper no disponible
        """
        if self._prefer_local:
            text = self._transcribe_whisper(audio_int16, sample_rate)
            if text:
                return text
            return self._transcribe_google(audio_int16, sample_rate)
        else:
            text = self._transcribe_google(audio_int16, sample_rate)
            if text:
                return text
            # Google falló por red → intentar Whisper local
            return self._transcribe_whisper(audio_int16, sample_rate)

    def whisper_available(self) -> bool:
        """True si faster-whisper está instalado y el modelo se puede cargar."""
        return self._load_whisper() is not None

    # ─── Backends ─────────────────────────────────────────────────────────────

    def _transcribe_google(
        self, audio_int16: np.ndarray, sample_rate: int
    ) -> str:
        """Google Speech-to-Text via SpeechRecognition."""
        try:
            audio_data = sr.AudioData(audio_int16.tobytes(), sample_rate, 2)
            old_to = socket.getdefaulttimeout()
            socket.setdefaulttimeout(self._google_timeout)
            try:
                text = self._recognizer.recognize_google(
                    audio_data, language=self._lang
                )
            finally:
                socket.setdefaulttimeout(old_to)
            logger.info(f"[STT/Google] '{text}'")
            return text.strip()
        except sr.UnknownValueError:
            logger.debug("[STT/Google] no entendido")
            return ""
        except (sr.RequestError, socket.timeout, TimeoutError) as e:
            logger.warning(f"[STT/Google] error de red: {e}")
            return ""
        except Exception as e:
            logger.warning(f"[STT/Google] error: {e}")
            return ""

    def _transcribe_whisper(
        self, audio_int16: np.ndarray, sample_rate: int
    ) -> str:
        """faster-whisper local (offline)."""
        whisper = self._load_whisper()
        if whisper is None:
            return ""
        try:
            # faster-whisper espera float32 normalizado en [-1, 1]
            audio_f32 = audio_int16.astype(np.float32) / 32_768.0

            lang = _WHISPER_LANG.get(self._lang, self._lang[:2])
            segments, _info = whisper.transcribe(
                audio_f32,
                language    = lang,
                beam_size   = 1,        # rápido para comandos cortos
                vad_filter  = False,    # ya usamos Silero VAD
            )
            text = " ".join(seg.text.strip() for seg in segments).strip()
            if text:
                logger.info(f"[STT/Whisper] '{text}'")
            return text
        except Exception as e:
            logger.warning(f"[STT/Whisper] error: {e}")
            return ""

    def _load_whisper(self):
        """Carga el modelo de faster-whisper la primera vez que se necesita."""
        if self._whisper_tried:
            return self._whisper
        self._whisper_tried = True
        try:
            from faster_whisper import WhisperModel
            logger.info(
                f"[STT/Whisper] Cargando modelo '{self._whisper_model}'..."
            )
            self._whisper = WhisperModel(
                self._whisper_model,
                device       = "cpu",
                compute_type = "int8",   # cuantización int8 → 2-4x más rápido en CPU
            )
            logger.info(f"[STT/Whisper] Modelo '{self._whisper_model}' listo.")
        except ImportError:
            logger.warning(
                "[STT/Whisper] faster-whisper no instalado. "
                "Instalar con: pip install faster-whisper"
            )
        except Exception as e:
            logger.warning(f"[STT/Whisper] No se pudo cargar el modelo: {e}")
        return self._whisper
