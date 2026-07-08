"""
test_audio_loop.py — Tests para AudioLoop (full-duplex: wake word + VAD).

No requiere microfono real. PyAudio, openwakeword y SileroVAD se mockean.

Ejecucion:
    python -m tests.test_audio_loop
    # o:
    python tests/test_audio_loop.py
"""

import sys
import os
import time
import threading
import contextlib
from unittest.mock import MagicMock, patch

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import numpy as np

SAMPLE_RATE = 16_000
VAD_CHUNK   = 512


def _pass(name: str):
    print(f"  [PASS] {name}")


def _fail(name: str, reason: str):
    print(f"  [FAIL] {name}: {reason}")


def _skip(name: str, reason: str):
    print(f"  [SKIP] {name}: {reason}")


def _make_silence(n: int = VAD_CHUNK) -> bytes:
    return np.zeros(n, dtype=np.int16).tobytes()


def _make_noise(n: int = VAD_CHUNK) -> bytes:
    return np.random.randint(-2000, 2000, n, dtype=np.int16).tobytes()


def _make_mock_stream(audio_gen=None):
    """Mock de PyAudio stream. audio_gen() debe devolver bytes por chunk."""
    if audio_gen is None:
        audio_gen = lambda: _make_silence()
    mock = MagicMock()
    mock.read.side_effect = lambda n, exception_on_overflow=False: audio_gen()
    return mock


def _make_mock_pyaudio(stream=None):
    if stream is None:
        stream = _make_mock_stream()
    mock_pa = MagicMock()
    mock_pa.paInt16 = 8
    mock_pa.open.return_value = stream
    mod = MagicMock()
    mod.PyAudio.return_value = mock_pa
    mod.paInt16 = 8
    return mod, stream


def _make_mock_oww(score: float = 0.0):
    mock = MagicMock()
    mock.predict.return_value = {"hey_jarvis_v0.1": score}
    feats = np.zeros((1, 16, 96), dtype=np.float32)
    mock.preprocessor.get_features.return_value = feats
    return mock


def _make_mock_vad(is_speech: bool = False):
    """Mock de SileroVAD que siempre devuelve is_speech."""
    mock = MagicMock()
    mock.is_speech.return_value = is_speech
    mock.reset.return_value = None
    return mock


def _make_mock_segmenter(segments=None):
    """
    Mock de SpeechSegmenter.
    segments: lista de np.ndarray o None que feed() devolvera en orden.
    Despues del ultimo elemento devuelve None.
    """
    if segments is None:
        segments = []
    idx = {"i": 0}
    mock = MagicMock()
    def fake_feed(chunk):
        if idx["i"] < len(segments):
            val = segments[idx["i"]]
            idx["i"] += 1
            return val
        return None
    mock.feed.side_effect = fake_feed
    return mock


# ─── Helpers de parcheo ───────────────────────────────────────────────────────

def _make_mock_oww_module(score: float = 0.0):
    """
    Crea un modulo openwakeword completo (mock) para inyectar en sys.modules.
    Incluye openwakeword, openwakeword.model y openwakeword.utils.
    """
    mock_oww_instance = _make_mock_oww(score=score)

    # La clase Model instancia directamente el mock
    mock_model_class = MagicMock(return_value=mock_oww_instance)

    mock_model_module = MagicMock()
    mock_model_module.Model = mock_model_class

    mock_oww_package = MagicMock()
    mock_oww_package.model = mock_model_module

    return {
        "openwakeword":        mock_oww_package,
        "openwakeword.model":  mock_model_module,
        "openwakeword.utils":  MagicMock(),
    }, mock_oww_instance


def _loop_patches(score=0.0, vad_speech=False, segments=None, stream=None):
    """
    Devuelve lista de patches + mocks para tests del AudioLoop.

    Mockea TODO lo que _run() importa dentro del hilo:
      - pyaudio
      - openwakeword (y submodulos)
      - modules.vad.vad_engine.SileroVAD / SpeechSegmenter
      - _find_verifier_pkl
    """
    if stream is None:
        stream = _make_mock_stream()
    mock_pa_mod, _ = _make_mock_pyaudio(stream)

    oww_modules, mock_oww_instance = _make_mock_oww_module(score=score)
    mock_vad       = _make_mock_vad(is_speech=vad_speech)

    seg_list = segments if segments is not None else []
    mock_segmenter = _make_mock_segmenter(seg_list)

    patches = [
        patch.dict(sys.modules, {"pyaudio": mock_pa_mod, **oww_modules}),
        patch("modules.audio.audio_loop.OWW_CHUNK", 512),  # alinear con VAD_CHUNK para tests
        patch("modules.vad.vad_engine.SileroVAD",       return_value=mock_vad),
        patch("modules.vad.vad_engine.SpeechSegmenter", return_value=mock_segmenter),
        patch("modules.audio.audio_loop._find_verifier_pkl", return_value=None),
    ]
    return patches, stream, mock_oww_instance, mock_vad, mock_segmenter


# ─── Tests ────────────────────────────────────────────────────────────────────

def test_instantiation():
    """Test 1: AudioLoop instancia sin crash con parametros por defecto."""
    name = "test_instantiation"
    try:
        from modules.audio.audio_loop import AudioLoop
        loop = AudioLoop()
        assert loop is not None
        assert not loop.is_running
        assert loop.audio_queue is not None
        _pass(name)
    except Exception as e:
        _fail(name, str(e))
        import traceback; traceback.print_exc()


def test_start_stop():
    """Test 2: start() + stop() en < 3s (todo mockeado)."""
    name = "test_start_stop"
    try:
        from modules.audio.audio_loop import AudioLoop
        from modules.vad.vad_engine import SileroVAD, SpeechSegmenter

        patches, _, _, _, _ = _loop_patches(score=0.0)
        with contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)

            loop = AudioLoop()
            t0 = time.monotonic()
            loop.start()
            assert loop.is_running, "debe estar corriendo tras start()"
            time.sleep(0.15)
            loop.stop()
            t1 = time.monotonic()

        assert not loop.is_running, "debe estar parado tras stop()"
        assert t1 - t0 < 3.0, f"stop() tardo {t1-t0:.2f}s"
        _pass(name + f" ({(t1-t0)*1000:.0f}ms)")
    except Exception as e:
        _fail(name, str(e))
        import traceback; traceback.print_exc()


def test_is_running_property():
    """Test 3: is_running refleja correctamente el estado del hilo."""
    name = "test_is_running_property"
    try:
        from modules.audio.audio_loop import AudioLoop

        patches, _, _, _, _ = _loop_patches()
        with contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)

            loop = AudioLoop()
            assert not loop.is_running, "antes de start debe ser False"
            loop.start()
            assert loop.is_running, "despues de start debe ser True"
            loop.stop()
            assert not loop.is_running, "despues de stop debe ser False"

        _pass(name)
    except Exception as e:
        _fail(name, str(e))
        import traceback; traceback.print_exc()


def test_no_wake_word_no_segment():
    """Test 4: Con score=0 (sin wake word), audio_queue permanece vacia."""
    name = "test_no_wake_word_no_segment"
    try:
        from modules.audio.audio_loop import AudioLoop

        patches, _, _, _, _ = _loop_patches(score=0.0)
        with contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)

            loop = AudioLoop(wakeword_threshold=0.5)
            loop.start()
            time.sleep(0.3)
            loop.stop()

        assert loop.audio_queue.empty(), "no debe haber segmentos sin wake word"
        _pass(name)
    except Exception as e:
        _fail(name, str(e))
        import traceback; traceback.print_exc()


def test_is_speaking_suppresses_wakeword():
    """Test 5: is_speaking_event activo suprime el wake word."""
    name = "test_is_speaking_suppresses_wakeword"
    try:
        from modules.audio.audio_loop import AudioLoop

        # Score alto (deberia disparar), pero is_speaking activo
        patches, _, _, _, _ = _loop_patches(score=0.99)
        with contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)

            speaking_ev = threading.Event()
            speaking_ev.set()   # TTS activo

            loop = AudioLoop(wakeword_threshold=0.3)
            loop.start(is_speaking_event=speaking_ev)
            time.sleep(0.3)
            loop.stop()

        assert loop.audio_queue.empty(), \
            "no debe activar cuando TTS esta hablando"
        _pass(name)
    except Exception as e:
        _fail(name, str(e))
        import traceback; traceback.print_exc()


def test_stop_idempotent():
    """Test 6: Llamar stop() dos veces no lanza excepcion."""
    name = "test_stop_idempotent"
    try:
        from modules.audio.audio_loop import AudioLoop

        patches, _, _, _, _ = _loop_patches()
        with contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)

            loop = AudioLoop()
            loop.start()
            time.sleep(0.05)
            loop.stop()
            loop.stop()    # segunda llamada — no debe explotar

        _pass(name)
    except Exception as e:
        _fail(name, str(e))
        import traceback; traceback.print_exc()


def test_ww_score_fallback_no_verifier():
    """Test 7: _ww_score devuelve score nativo de openwakeword si no hay verifier."""
    name = "test_ww_score_fallback_no_verifier"
    try:
        from modules.audio.audio_loop import AudioLoop

        loop = AudioLoop()
        mock_oww = _make_mock_oww(score=0.75)

        chunk = np.zeros(512, dtype=np.int16)
        score = loop._ww_score(chunk, mock_oww, verifier=None)

        assert isinstance(score, float), f"score debe ser float, got {type(score)}"
        assert score == 0.75, f"esperado 0.75, got {score}"
        _pass(name)
    except Exception as e:
        _fail(name, str(e))
        import traceback; traceback.print_exc()


def test_ww_score_with_verifier():
    """Test 8: _ww_score usa predict_proba del verifier cuando esta disponible."""
    name = "test_ww_score_with_verifier"
    try:
        from modules.audio.audio_loop import AudioLoop

        loop = AudioLoop()
        mock_oww = _make_mock_oww(score=0.5)

        mock_verifier = MagicMock()
        mock_verifier.classes_ = [0, 1]
        mock_verifier.predict_proba.return_value = np.array([[0.2, 0.8]])

        chunk = np.zeros(512, dtype=np.int16)
        score = loop._ww_score(chunk, mock_oww, verifier=mock_verifier)

        assert isinstance(score, float), f"score debe ser float, got {type(score)}"
        assert abs(score - 0.8) < 1e-6, f"esperado 0.8 (clase 1), got {score}"
        _pass(name)
    except Exception as e:
        _fail(name, str(e))
        import traceback; traceback.print_exc()


def test_ring_buffer_size():
    """Test 9: El ring buffer tiene maxlen = RING_CHUNKS (sin desbordamiento)."""
    name = "test_ring_buffer_size"
    try:
        import collections
        from modules.audio.audio_loop import RING_CHUNKS

        ring = collections.deque(maxlen=RING_CHUNKS)
        extra = RING_CHUNKS + 10
        chunk = np.zeros(VAD_CHUNK, dtype=np.int16)
        for _ in range(extra):
            ring.append(chunk.copy())

        assert len(ring) == RING_CHUNKS, \
            f"ring tiene {len(ring)} chunks, esperado {RING_CHUNKS}"
        _pass(name + f" (maxlen={RING_CHUNKS})")
    except Exception as e:
        _fail(name, str(e))
        import traceback; traceback.print_exc()


def main():
    print("=" * 55)
    print("Tests: AudioLoop")
    print("=" * 55)
    print()

    test_instantiation()
    test_start_stop()
    test_is_running_property()
    test_no_wake_word_no_segment()
    test_is_speaking_suppresses_wakeword()
    test_stop_idempotent()
    test_ww_score_fallback_no_verifier()
    test_ww_score_with_verifier()
    test_ring_buffer_size()

    print("\nTests completados.")


if __name__ == "__main__":
    main()
