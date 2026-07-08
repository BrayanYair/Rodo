"""
test_stt_engine.py — Tests para STTEngine (Google STT + Whisper fallback).

No requiere internet ni GPU. Google STT y Whisper se mockean con stubs.

Ejecucion:
    python -m tests.test_stt_engine
    # o:
    python tests/test_stt_engine.py
"""

import sys
import os
from unittest.mock import MagicMock, patch

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import numpy as np


def _pass(name: str):
    print(f"  [PASS] {name}")


def _fail(name: str, reason: str):
    print(f"  [FAIL] {name}: {reason}")


def _skip(name: str, reason: str):
    print(f"  [SKIP] {name}: {reason}")


def _make_audio(duration_ms: int = 500, sr: int = 16_000) -> np.ndarray:
    """Genera audio de ruido blanco int16."""
    n = int(sr * duration_ms / 1000)
    return np.random.randint(-3000, 3000, n, dtype=np.int16)


# ─── Tests ────────────────────────────────────────────────────────────────────

def test_instantiation():
    """Test 1: STTEngine instancia sin crash."""
    name = "test_instantiation"
    try:
        from modules.stt.stt_engine import STTEngine
        engine = STTEngine()
        assert engine is not None
        assert engine._lang == "es-ES"
        assert not engine._prefer_local
        _pass(name)
    except Exception as e:
        _fail(name, str(e))
        import traceback; traceback.print_exc()


def test_transcribe_google_ok():
    """Test 2: transcribe() devuelve texto cuando Google STT responde."""
    name = "test_transcribe_google_ok"
    try:
        from modules.stt.stt_engine import STTEngine
        import speech_recognition as sr

        engine = STTEngine()

        with patch.object(engine._recognizer, "recognize_google", return_value="hola mundo"):
            result = engine.transcribe(_make_audio())

        assert result == "hola mundo", f"Esperado 'hola mundo', got '{result}'"
        _pass(name)
    except Exception as e:
        _fail(name, str(e))
        import traceback; traceback.print_exc()


def test_transcribe_google_unknown_value():
    """Test 3: transcribe() devuelve '' cuando Google no entiende el audio."""
    name = "test_transcribe_google_unknown_value"
    try:
        import speech_recognition as sr
        from modules.stt.stt_engine import STTEngine

        engine = STTEngine()

        with patch.object(engine._recognizer, "recognize_google",
                          side_effect=sr.UnknownValueError()):
            result = engine.transcribe(_make_audio())

        assert result == "", f"Esperado '', got '{result}'"
        _pass(name)
    except Exception as e:
        _fail(name, str(e))
        import traceback; traceback.print_exc()


def test_transcribe_google_network_error_falls_back_to_whisper():
    """Test 4: Si Google falla por red, intenta Whisper local."""
    name = "test_transcribe_google_network_error_falls_back_to_whisper"
    try:
        import speech_recognition as sr
        from modules.stt.stt_engine import STTEngine

        engine = STTEngine(prefer_local=False)

        # Google lanza RequestError; Whisper devuelve texto
        with patch.object(engine._recognizer, "recognize_google",
                          side_effect=sr.RequestError("simulated")):
            with patch.object(engine, "_transcribe_whisper", return_value="texto por whisper"):
                result = engine.transcribe(_make_audio())

        assert result == "texto por whisper", f"got '{result}'"
        _pass(name)
    except Exception as e:
        _fail(name, str(e))
        import traceback; traceback.print_exc()


def test_prefer_local_uses_whisper_first():
    """Test 5: Con prefer_local=True, Whisper es el primer intento."""
    name = "test_prefer_local_uses_whisper_first"
    try:
        from modules.stt.stt_engine import STTEngine

        engine = STTEngine(prefer_local=True)

        with patch.object(engine, "_transcribe_whisper", return_value="whisper habla") as mock_w:
            with patch.object(engine, "_transcribe_google", return_value="google habla") as mock_g:
                result = engine.transcribe(_make_audio())

        mock_w.assert_called_once()
        mock_g.assert_not_called()     # no debe llamarse si Whisper tuvo exito
        assert result == "whisper habla", f"got '{result}'"
        _pass(name)
    except Exception as e:
        _fail(name, str(e))
        import traceback; traceback.print_exc()


def test_prefer_local_falls_back_to_google():
    """Test 6: Con prefer_local=True, si Whisper devuelve '', cae a Google."""
    name = "test_prefer_local_falls_back_to_google"
    try:
        from modules.stt.stt_engine import STTEngine

        engine = STTEngine(prefer_local=True)

        with patch.object(engine, "_transcribe_whisper", return_value="") as mock_w:
            with patch.object(engine, "_transcribe_google", return_value="google secundario") as mock_g:
                result = engine.transcribe(_make_audio())

        mock_w.assert_called_once()
        mock_g.assert_called_once()
        assert result == "google secundario", f"got '{result}'"
        _pass(name)
    except Exception as e:
        _fail(name, str(e))
        import traceback; traceback.print_exc()


def test_transcribe_whisper_normalizes_audio():
    """Test 7: _transcribe_whisper convierte int16 a float32 correctamente."""
    name = "test_transcribe_whisper_normalizes_audio"
    try:
        from modules.stt.stt_engine import STTEngine

        engine = STTEngine()

        # Mock de WhisperModel: capturamos el audio que recibe
        mock_whisper = MagicMock()
        captured = {}
        def fake_transcribe(audio, **kw):
            captured["audio"] = audio
            seg = MagicMock()
            seg.text = "transcrito"
            return [seg], MagicMock()
        mock_whisper.transcribe.side_effect = fake_transcribe

        engine._whisper = mock_whisper
        engine._whisper_tried = True   # saltar _load_whisper

        audio_int16 = _make_audio()
        result = engine._transcribe_whisper(audio_int16, 16_000)

        assert result == "transcrito", f"got '{result}'"
        assert "audio" in captured, "no se llamó a whisper.transcribe"
        arr = captured["audio"]
        assert arr.dtype == np.float32, f"dtype incorrecto: {arr.dtype}"
        assert arr.max() <= 1.0 and arr.min() >= -1.0, "audio no normalizado"
        _pass(name)
    except Exception as e:
        _fail(name, str(e))
        import traceback; traceback.print_exc()


def test_whisper_not_available_returns_empty():
    """Test 8: Si faster-whisper no esta instalado, _transcribe_whisper devuelve ''."""
    name = "test_whisper_not_available_returns_empty"
    try:
        from modules.stt.stt_engine import STTEngine

        engine = STTEngine()
        # Simular que faster-whisper no esta instalado
        engine._whisper = None
        engine._whisper_tried = True  # skip _load_whisper

        result = engine._transcribe_whisper(_make_audio(), 16_000)
        assert result == "", f"Esperado '', got '{result}'"
        _pass(name)
    except Exception as e:
        _fail(name, str(e))
        import traceback; traceback.print_exc()


def test_whisper_language_mapping():
    """Test 9: El codigo de idioma se mapea correctamente de BCP-47 a 2 letras."""
    name = "test_whisper_language_mapping"
    try:
        from modules.stt.stt_engine import STTEngine, _WHISPER_LANG

        assert _WHISPER_LANG.get("es-ES") == "es"
        assert _WHISPER_LANG.get("en-US") == "en"
        assert _WHISPER_LANG.get("pt-BR") == "pt"

        engine_es = STTEngine(language="es-ES")
        engine_en = STTEngine(language="en-US")
        assert engine_es._lang == "es-ES"
        assert engine_en._lang == "en-US"

        # Verificar que el idioma que se pasa a whisper es el de 2 letras
        mock_whisper = MagicMock()
        captured_kwargs = {}
        def fake_transcribe(audio, **kw):
            captured_kwargs.update(kw)
            return [], MagicMock()
        mock_whisper.transcribe.side_effect = fake_transcribe
        engine_es._whisper = mock_whisper
        engine_es._whisper_tried = True

        engine_es._transcribe_whisper(np.zeros(1600, dtype=np.int16), 16_000)
        assert captured_kwargs.get("language") == "es", \
            f"language incorrecto: {captured_kwargs.get('language')}"

        _pass(name)
    except Exception as e:
        _fail(name, str(e))
        import traceback; traceback.print_exc()


def main():
    print("=" * 55)
    print("Tests: STTEngine")
    print("=" * 55)
    print()

    test_instantiation()
    test_transcribe_google_ok()
    test_transcribe_google_unknown_value()
    test_transcribe_google_network_error_falls_back_to_whisper()
    test_prefer_local_uses_whisper_first()
    test_prefer_local_falls_back_to_google()
    test_transcribe_whisper_normalizes_audio()
    test_whisper_not_available_returns_empty()
    test_whisper_language_mapping()

    print("\nTests completados.")


if __name__ == "__main__":
    main()
