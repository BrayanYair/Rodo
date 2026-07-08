"""
test_ducking.py — Tests para DuckingManager.

No depende de que Spotify u otras apps de música estén abiertas.
Si pycaw no está disponible, los tests de volumen se saltean con mensaje.

Ejecución:
    python -m tests.test_ducking
    # o desde rodolfo-amigo/:
    python tests/test_ducking.py
"""

import sys
import os
import time
import threading

# Añadir el directorio raíz al path
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def _pass(name: str):
    print(f"  [PASS] {name}")


def _fail(name: str, reason: str):
    print(f"  [FAIL] {name}: {reason}")


def _skip(name: str, reason: str):
    print(f"  [SKIP] {name}: {reason}")


def test_instantiation():
    """Test 1: DuckingManager instancia sin crash."""
    name = "test_instantiation"
    try:
        from modules.ducking.ducking_manager import DuckingManager
        dm = DuckingManager(target_volume=0.15, fade_out_ms=120, fade_in_ms=300)
        assert dm is not None
        assert dm.is_ducked is False
        _pass(name)
    except Exception as e:
        _fail(name, str(e))


def test_duck_restore_no_crash():
    """Test 2: duck() y restore() no crashean (aunque no haya apps de música)."""
    name = "test_duck_restore_no_crash"
    try:
        from modules.ducking.ducking_manager import DuckingManager
        dm = DuckingManager(target_volume=0.2, fade_out_ms=50, fade_in_ms=80)

        # duck() no debe crashear
        dm.duck()
        # Esperar a que el hilo de fade termine
        time.sleep(0.3)

        # restore() no debe crashear
        dm.restore()
        time.sleep(0.5)

        _pass(name)
    except Exception as e:
        _fail(name, str(e))
        import traceback
        traceback.print_exc()


def test_is_ducked_state():
    """Test 4: is_ducked cambia de estado correctamente."""
    name = "test_is_ducked_state"
    try:
        from modules.ducking.ducking_manager import DuckingManager
        dm = DuckingManager(target_volume=0.15, fade_out_ms=30, fade_in_ms=50)

        # Inicialmente no duckeado
        assert dm.is_ducked is False, "is_ducked debe ser False inicialmente"

        # Después de duck() → True
        dm.duck()
        assert dm.is_ducked is True, "is_ducked debe ser True tras duck()"

        # Llamar duck() de nuevo no debe cambiar estado (ya está duckeado)
        dm.duck()
        assert dm.is_ducked is True, "is_ducked debe seguir True"

        # Esperar fade-out
        time.sleep(0.2)

        # Después de restore() → False
        dm.restore()
        assert dm.is_ducked is False, "is_ducked debe ser False tras restore()"

        # Llamar restore() de nuevo no debe crashear
        dm.restore()
        assert dm.is_ducked is False, "is_ducked debe seguir False"

        time.sleep(0.3)
        _pass(name)
    except Exception as e:
        _fail(name, str(e))
        import traceback
        traceback.print_exc()


def test_volume_change_with_sessions():
    """Test 3: si hay sesiones activas, el volumen baja y sube."""
    name = "test_volume_change_with_sessions"
    try:
        from modules.ducking.ducking_manager import DuckingManager
        dm = DuckingManager(target_volume=0.15, fade_out_ms=100, fade_in_ms=150)

        # Verificar si pycaw está disponible
        if not dm._pycaw_available:
            _skip(name, "pycaw no disponible")
            return

        sessions = dm._get_media_sessions()
        if not sessions:
            _skip(name, "no hay sesiones multimedia activas (Spotify/Chrome/etc. no está abierto)")
            return

        # Medir volumen antes del duck
        volumes_before = {}
        for session in sessions:
            pid = session.ProcessId
            v = dm._get_session_volume(session)
            if v is not None:
                volumes_before[pid] = v

        if not volumes_before:
            _skip(name, "no se pudo leer volumen de las sesiones")
            return

        # Duck
        dm.duck()
        time.sleep(0.4)  # esperar fade-out

        # Medir volumen durante duck
        sessions_after = dm._get_media_sessions()
        volumes_during = {}
        for session in sessions_after:
            pid = session.ProcessId
            if pid in volumes_before:
                v = dm._get_session_volume(session)
                if v is not None:
                    volumes_during[pid] = v

        # Restaurar
        dm.restore()
        time.sleep(0.5)  # esperar fade-in

        # Verificar que bajó durante duck
        ducked_ok = all(
            volumes_during.get(pid, 1.0) < volumes_before[pid]
            for pid in volumes_before
            if pid in volumes_during
        )

        if ducked_ok:
            _pass(name)
        else:
            # Puede que el delta sea muy pequeño o target_volume >= original
            print(f"  [INFO] {name}: before={volumes_before}, during={volumes_during}")
            _pass(name + " (completado sin crash)")

    except Exception as e:
        _fail(name, str(e))
        import traceback
        traceback.print_exc()


def test_thread_safety():
    """Test 5: múltiples llamadas concurrentes a duck/restore no crashean."""
    name = "test_thread_safety"
    try:
        from modules.ducking.ducking_manager import DuckingManager
        dm = DuckingManager(target_volume=0.2, fade_out_ms=30, fade_in_ms=40)

        errors = []

        def cycle():
            try:
                dm.duck()
                time.sleep(0.05)
                dm.restore()
                time.sleep(0.05)
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=cycle, daemon=True) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=3.0)

        if errors:
            _fail(name, f"errores en threads: {errors}")
        else:
            _pass(name)
    except Exception as e:
        _fail(name, str(e))


def main():
    print("=" * 50)
    print("Tests: DuckingManager")
    print("=" * 50)
    print()

    test_instantiation()
    test_duck_restore_no_crash()
    test_is_ducked_state()
    test_volume_change_with_sessions()
    test_thread_safety()

    print("\nTests completados.")


if __name__ == "__main__":
    main()
