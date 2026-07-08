"""
voice_metrics.py — Medición de latencias del pipeline de voz.

Uso:
    metrics = VoiceMetrics()
    metrics.mark("wakeword_detected")
    # ... ducking ...
    metrics.mark("ducking_done")
    # ... STT ...
    metrics.mark("stt_done")
    # ... primer byte de TTS ...
    metrics.mark("ttfa")

    metrics.log_report()
    metrics.reset()
"""

import time
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Labels estándar del pipeline
_PIPELINE_LABELS = (
    "wakeword_detected",
    "ducking_done",
    "stt_done",
    "ttfa",
)


class VoiceMetrics:
    """
    Registra timestamps de eventos del pipeline de voz y calcula latencias.

    Todos los tiempos se miden en segundos (monotonic) y se reportan en milisegundos.
    """

    def __init__(self):
        self._marks: Dict[str, float] = {}

    def mark(self, label: str):
        """
        Registra el timestamp actual para el label dado.
        Si el label ya existe, lo sobreescribe.

        Parámetros:
            label: identificador del evento (e.g. 'wakeword_detected', 'stt_done').
        """
        self._marks[label] = time.monotonic()

    def elapsed(self, from_label: str, to_label: str) -> float:
        """
        Calcula la diferencia en milisegundos entre dos marcas.

        Parámetros:
            from_label: label de inicio.
            to_label:   label de fin.

        Retorna:
            Milisegundos transcurridos, o -1.0 si alguna marca no existe.
        """
        t0 = self._marks.get(from_label)
        t1 = self._marks.get(to_label)
        if t0 is None or t1 is None:
            return -1.0
        return (t1 - t0) * 1000.0

    def report(self) -> dict:
        """
        Calcula y retorna un diccionario con las latencias del pipeline.

        Claves del resultado:
            wakeword_ms:  Tiempo hasta detectar el wake word (primer mark).
            ducking_ms:   Tiempo de fade-out de audio.
            stt_ms:       Tiempo de reconocimiento de voz.
            ttfa_ms:      Tiempo total desde wake word hasta primer audio de respuesta.
            raw_marks:    Dict con todos los timestamps registrados (en segundos).
        """
        result = {
            "wakeword_ms": -1.0,
            "ducking_ms": -1.0,
            "stt_ms": -1.0,
            "ttfa_ms": -1.0,
            "raw_marks": dict(self._marks),
        }

        # wakeword_ms: desde inicio hasta detección (si hay marca de inicio)
        if "start" in self._marks and "wakeword_detected" in self._marks:
            result["wakeword_ms"] = self.elapsed("start", "wakeword_detected")

        # ducking_ms: desde detección hasta fin del fade-out
        result["ducking_ms"] = self.elapsed("wakeword_detected", "ducking_done")

        # stt_ms: desde inicio de escucha STT hasta resultado
        result["stt_ms"] = self.elapsed("stt_start", "stt_done")

        # ttfa_ms (Time To First Audio): desde wake word hasta primer audio de respuesta
        result["ttfa_ms"] = self.elapsed("wakeword_detected", "ttfa")

        # Si no hay stt_start, intentar desde ducking_done
        if result["stt_ms"] < 0:
            result["stt_ms"] = self.elapsed("ducking_done", "stt_done")

        return result

    def reset(self):
        """Limpia todas las marcas registradas."""
        self._marks.clear()

    def log_report(self):
        """Imprime el reporte de latencias de forma legible."""
        r = self.report()
        lines = [
            "--- VoiceMetrics Report ---",
            f"  Wake word detection : {_fmt_ms(r['wakeword_ms'])}",
            f"  Ducking fade-out    : {_fmt_ms(r['ducking_ms'])}",
            f"  STT recognition     : {_fmt_ms(r['stt_ms'])}",
            f"  TTFA (total)        : {_fmt_ms(r['ttfa_ms'])}",
        ]
        # Añadir marcas adicionales no estándar
        known = {"start", "wakeword_detected", "ducking_done", "stt_start", "stt_done", "ttfa"}
        extra = {k: v for k, v in self._marks.items() if k not in known}
        if extra:
            lines.append("  Extra marks:")
            for k, v in sorted(extra.items(), key=lambda x: x[1]):
                lines.append(f"    {k}: {v:.4f}s")
        lines.append("---------------------------")
        logger.info("\n".join(lines))
        # También imprimir en stdout para uso en consola/debug
        print("\n".join(lines))


def _fmt_ms(value: float) -> str:
    """Formatea un valor de ms para el reporte."""
    if value < 0:
        return "N/A"
    return f"{value:.1f} ms"
