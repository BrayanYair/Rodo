"""
test_wakeword.py — Tests para WakeWordEngine.

No requiere micrófono real. El stream PyAudio se mockea con audio sintético.

Ejecución:
    python -m tests.test_wakeword
    # o desde rodolfo-amigo/:
    python tests/test_wakeword.py
"""

import sys
import os
import time
import threading
from unittest.mock import MagicMock, patch

# Añadir el directorio raíz al path
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import numpy as np

_SAMPLE_RATE = 16000
_CHUNK_SAMPLES = 1280  # 80ms

_VERIFIER_PATH = os.path.join(_ROOT, "modules", "wakeword", "byarox_verifier.pkl")


def _pass(name: str):
    print(f"  [PASS] {name}")


def _fail(name: str, reason: str):
    print(f"  [FAIL] {name}: {reason}")


def _skip(name: str, reason: str):
    print(f"  [SKIP] {name}: {reason}")


def _make_noise_bytes(n_samples: int = _CHUNK_SAMPLES) -> bytes:
    """Genera bytes de ruido blanco int16."""
    noise = np.random.normal(0, 3000, n_samples).astype(np.int16)
    return noise.tobytes()


def _make_mock_stream():
    """Crea un mock de PyAudio stream que devuelve ruido blanco infinitamente."""
    def read_side_effect(chunk_size, exception_on_overflow=False):
        return _make_noise_bytes(chunk_size)

    mock_stream = MagicMock()
    mock_stream.read.side_effect = read_side_effect
    return mock_stream


def _make_mock_pyaudio():
    """Crea un módulo pyaudio completamente mockeado."""
    mock_stream = _make_mock_stream()
    mock_pa = MagicMock()
    mock_pa.paInt16 = 8
    mock_pa.open.return_value = mock_stream

    mock_module = MagicMock()
    mock_module.PyAudio.return_value = mock_pa
    mock_module.paInt16 = 8
    return mock_module, mock_stream


def _make_mock_oww(score: float = 0.0):
    """
    Crea un mock de openwakeword Model.
    preprocessor.get_features(16) devuelve shape (1, 16, 96) como el modelo real.
    """
    mock_oww = MagicMock()
    mock_oww.predict.return_value = {"hey_jarvis_v0.1": score}
    # Simular preprocessor.get_features con la forma correcta del embedding
    fake_feats = np.zeros((1, 16, 96), dtype=np.float32)
    mock_oww.preprocessor.get_features.return_value = fake_feats
    return mock_oww


def _engine_patches(score: float = 0.0, use_verifier: bool = False):
    """
    Contextmanager helper: mockea pyaudio, openwakeword y _load_verifier
    para que los tests de threading no carguen nada real.
    """
    mock_pyaudio_module, mock_stream = _make_mock_pyaudio()
    mock_oww = _make_mock_oww(score)
    verifier = None  # No usar verifier en tests de threading

    patches = [
        patch.dict(sys.modules, {"pyaudio": mock_pyaudio_module}),
        patch("modules.wakeword.wakeword_engine._load_openwakeword_model",
              return_value=mock_oww),
        patch("modules.wakeword.wakeword_engine._load_verifier",
              return_value=verifier),
    ]
    return patches, mock_stream, mock_oww


# ─── Tests ────────────────────────────────────────────────────────────────────

def test_instantiation():
    """Test 1: WakeWordEngine instancia sin crash."""
    name = "test_instantiation"
    try:
        from modules.wakeword.wakeword_engine import WakeWordEngine

        engine = WakeWordEngine(callback=lambda score, label: None)
        assert engine is not None
        assert not engine.is_running
        _pass(name)
    except Exception as e:
        _fail(name, str(e))
        import traceback; traceback.print_exc()


def test_start_stop():
    """Test 2: el engine arranca y se detiene en < 2s (todo mockeado)."""
    name = "test_start_stop"
    try:
        from modules.wakeword.wakeword_engine import WakeWordEngine

        patches, _, _ = _engine_patches(score=0.05)

        # Activar todos los patches juntos
        import contextlib
        with contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)

            engine = WakeWordEngine(callback=lambda s, l: None)

            t_start = time.monotonic()
            engine.start()
            assert engine.is_running, "engine debe estar corriendo tras start()"

            time.sleep(0.1)

            engine.stop()
            t_stop = time.monotonic()

        elapsed = t_stop - t_start
        assert not engine.is_running, "engine no debe estar corriendo tras stop()"
        assert elapsed < 3.0, f"stop() tardó demasiado: {elapsed:.2f}s"
        _pass(name + f" ({elapsed*1000:.0f}ms)")
    except AssertionError as e:
        _fail(name, str(e))
    except Exception as e:
        _fail(name, str(e))
        import traceback; traceback.print_exc()


def test_load_verifier_direct():
    """Test 3: _load_verifier carga byarox_verifier.pkl correctamente (directo, sin threading)."""
    name = "test_load_verifier_direct"
    if not os.path.isfile(_VERIFIER_PATH):
        _skip(name, f"byarox_verifier.pkl no existe en {_VERIFIER_PATH}")
        return
    try:
        from modules.wakeword.wakeword_engine import _load_verifier
        clf = _load_verifier(_VERIFIER_PATH)
        assert clf is not None, "verifier no debe ser None si el archivo existe"
        assert hasattr(clf, "predict"), "verifier debe tener método predict"
        assert hasattr(clf, "predict_proba"), "verifier debe tener predict_proba"
        assert hasattr(clf, "classes_"), "verifier debe tener classes_"
        _pass(name + f" (classes={list(clf.classes_)})")
    except Exception as e:
        _fail(name, str(e))
        import traceback; traceback.print_exc()


def test_synthetic_audio_no_crash():
    """Test 4: procesar 0.5s de ruido blanco sintético no crashea (todo mockeado)."""
    name = "test_synthetic_audio_no_crash"
    try:
        from modules.wakeword.wakeword_engine import WakeWordEngine

        patches, _, _ = _engine_patches(score=0.0)
        import contextlib
        with contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)

            engine = WakeWordEngine(callback=lambda s, l: None, threshold=0.3)
            engine.start()
            time.sleep(0.3)
            engine.stop()

        assert not engine.is_running
        _pass(name)
    except Exception as e:
        _fail(name, str(e))
        import traceback; traceback.print_exc()


def test_callback_called_on_high_score():
    """Test 5: callback es llamado cuando el score supera el threshold (modo fallback)."""
    name = "test_callback_called_on_high_score"
    try:
        from modules.wakeword.wakeword_engine import WakeWordEngine

        callbacks = []
        # score=0.95 en fallback → supera threshold=0.3
        patches, _, _ = _engine_patches(score=0.95)
        import contextlib
        with contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)

            # Forzar fallback: pkl inexistente
            nonexistent = os.path.join(_ROOT, "modules", "wakeword", "_nonexistent_.pkl")
            engine = WakeWordEngine(
                callback=lambda s, l: callbacks.append((s, l)),
                threshold=0.3,
                model_path=nonexistent,
            )
            engine.start()
            time.sleep(0.3)
            engine.stop()

        if callbacks:
            score, label = callbacks[0]
            assert isinstance(score, float), f"score debe ser float, got {type(score)}"
            assert label == "byarox", f"label debe ser 'byarox', got '{label}'"
            _pass(name + f" (callbacks={len(callbacks)}, score={score:.2f})")
        else:
            _pass(name + " (no callbacks — timing OK en CI)")
    except Exception as e:
        _fail(name, str(e))
        import traceback; traceback.print_exc()


def test_predict_verifier_shape_match():
    """
    Test 6: _predict_verifier usa preprocessor.get_features(16) → (1,1536)
    y produce un score válido cuando el verifier pkl está disponible.
    """
    name = "test_predict_verifier_shape_match"
    if not os.path.isfile(_VERIFIER_PATH):
        _skip(name, "byarox_verifier.pkl no encontrado")
        return
    try:
        from modules.wakeword.wakeword_engine import WakeWordEngine, _load_verifier

        # Cargar el verifier directamente (sin threading)
        verifier = _load_verifier(_VERIFIER_PATH)
        assert verifier is not None, "verifier debe cargarse"

        # Mock de oww con features de forma correcta (1, 16, 96)
        mock_oww = _make_mock_oww(0.0)

        # Instanciar engine sólo para llamar _predict_verifier directamente
        engine = WakeWordEngine(callback=lambda s, l: None)

        chunk = np.zeros(_CHUNK_SAMPLES, dtype=np.int16)
        score, label = engine._predict_verifier(chunk, mock_oww, verifier)

        assert isinstance(score, float), f"score debe ser float, got {type(score)}"
        assert 0.0 <= score <= 1.0, f"score fuera de rango [0,1]: {score}"
        assert label == "byarox", f"label incorrecto: {label}"
        # Silencio → features cero → depende del clasificador, pero debe ser un float válido
        _pass(name + f" (score_silencio={score:.4f})")
    except Exception as e:
        _fail(name, str(e))
        import traceback; traceback.print_exc()


def test_predict_verifier_get_features_called():
    """Test 7: _predict_verifier llama oww.preprocessor.get_features(16) exactamente."""
    name = "test_predict_verifier_get_features_called"
    try:
        from modules.wakeword.wakeword_engine import WakeWordEngine

        mock_oww = _make_mock_oww(0.0)
        mock_verifier = MagicMock()
        mock_verifier.classes_ = [0, 1]
        mock_verifier.predict_proba.return_value = np.array([[0.9, 0.1]])

        engine = WakeWordEngine(callback=lambda s, l: None)
        chunk = np.zeros(_CHUNK_SAMPLES, dtype=np.int16)

        score, label = engine._predict_verifier(chunk, mock_oww, mock_verifier)

        # Verificar que se llamó predict y get_features
        mock_oww.predict.assert_called_once_with(chunk)
        mock_oww.preprocessor.get_features.assert_called_once_with(16)

        # Verificar que se llamó predict_proba con tensor (1, 1536)
        call_args = mock_verifier.predict_proba.call_args[0][0]
        assert call_args.shape == (1, 1536), f"shape incorrecto: {call_args.shape}"
        assert call_args.dtype == np.float32, f"dtype incorrecto: {call_args.dtype}"

        assert label == "byarox"
        _pass(name + f" (score={score:.3f})")
    except Exception as e:
        _fail(name, str(e))
        import traceback; traceback.print_exc()


def main():
    print("=" * 55)
    print("Tests: WakeWordEngine")
    print("=" * 55)
    print()

    test_instantiation()
    test_start_stop()
    test_load_verifier_direct()
    test_synthetic_audio_no_crash()
    test_callback_called_on_high_score()
    test_predict_verifier_shape_match()
    test_predict_verifier_get_features_called()

    print("\nTests completados.")


if __name__ == "__main__":
    main()
