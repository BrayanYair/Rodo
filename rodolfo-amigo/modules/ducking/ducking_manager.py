"""
ducking_manager.py — Audio ducking usando pycaw.

Reduce el volumen de aplicaciones multimedia (Spotify, Chrome, Firefox, Edge)
cuando el asistente de voz está escuchando o hablando, y lo restaura después.

Si no hay sesiones multimedia activas, atenúa el volumen maestro del sistema.
Si pycaw no está disponible, opera en modo silencioso (sin crash).
"""

import time
import threading
import queue
import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Nombres de proceso considerados "multimedia"
_MEDIA_PROCESS_NAMES = {
    "spotify.exe",
    "chrome.exe",
    "firefox.exe",
    "msedge.exe",
    "vlc.exe",
    "mpc-hc64.exe",
    "mpc-hc.exe",
    "foobar2000.exe",
    "musicbee.exe",
}


def _try_import_pycaw():
    """Intenta importar pycaw. Retorna (AudioUtilities, IAudioEndpointVolume, ISimpleAudioVolume) o Nones."""
    try:
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume, ISimpleAudioVolume
        from comtypes import CLSCTX_ALL
        return AudioUtilities, IAudioEndpointVolume, ISimpleAudioVolume, CLSCTX_ALL
    except Exception as e:
        logger.warning(f"pycaw no disponible: {e}")
        return None, None, None, None


class DuckingManager:
    """
    Gestiona el audio ducking de aplicaciones multimedia durante la escucha del asistente.

    Parámetros:
        target_volume:  Volumen objetivo al hacer duck (0.0-1.0). Default 0.15.
        fade_out_ms:    Duración del fade-out en ms. Default 120.
        fade_in_ms:     Duración del fade-in en ms. Default 300.
    """

    def __init__(
        self,
        target_volume: float = 0.15,
        fade_out_ms: int = 120,
        fade_in_ms: int = 300,
    ):
        self._target_volume = max(0.0, min(1.0, target_volume))
        self._fade_out_ms = fade_out_ms
        self._fade_in_ms = fade_in_ms
        self._is_ducked = False
        self._lock = threading.Lock()

        # Guardar estado original por sesión: {pid: (session_obj, original_volume)}
        self._session_states: Dict[int, Tuple] = {}
        # Estado del volumen maestro
        self._master_original: Optional[float] = None
        self._ducked_master = False

        # Importar pycaw
        self._AudioUtilities, self._IAudioEndpointVolume, self._ISimpleAudioVolume, self._CLSCTX_ALL = _try_import_pycaw()
        self._pycaw_available = self._AudioUtilities is not None

        # Todo el trabajo de COM (pycaw/comtypes) corre en UN único hilo
        # daemon persistente. Antes cada duck()/restore() lanzaba su propio
        # hilo suelto — con el wake word local disparando seguido, esos
        # hilos se solapaban y terminaban tocando los mismos objetos COM
        # desde threads distintos ("COM method call without VTable"),
        # corrompiendo memoria y crasheando el proceso entero (segfault).
        # Serializar todo en un solo hilo elimina esa condición de carrera.
        self._op_queue: "queue.Queue[str]" = queue.Queue()
        self._worker = threading.Thread(
            target=self._worker_loop, daemon=True, name="DuckingWorker"
        )
        self._worker.start()

    @property
    def is_ducked(self) -> bool:
        """True si el ducking está activo actualmente."""
        return self._is_ducked

    def duck(self):
        """
        Reduce el volumen de aplicaciones multimedia.
        Operación no bloqueante: se encola y el fade ocurre en el hilo worker.
        """
        with self._lock:
            if self._is_ducked:
                return
            self._is_ducked = True
        self._op_queue.put("duck")

    def restore(self):
        """
        Restaura el volumen original.
        Operación no bloqueante: se encola y el fade ocurre en el hilo worker.
        """
        with self._lock:
            if not self._is_ducked:
                return
            self._is_ducked = False
        self._op_queue.put("restore")

    def _worker_loop(self):
        """Procesa duck/restore en orden, siempre en este mismo hilo."""
        while True:
            op = self._op_queue.get()
            try:
                if op == "duck":
                    self._do_duck()
                elif op == "restore":
                    self._do_restore()
            except Exception as e:
                logger.warning(f"DuckingManager worker error ({op}): {e}")

    # ------------------------------------------------------------------
    # Internos
    # ------------------------------------------------------------------

    def _get_media_sessions(self) -> List:
        """Retorna lista de sesiones de audio que son aplicaciones multimedia."""
        if not self._pycaw_available:
            return []
        try:
            all_sessions = self._AudioUtilities.GetAllSessions()
            media_sessions = []
            for session in all_sessions:
                try:
                    if session.Process is None:
                        continue
                    pname = session.Process.name().lower()
                    if pname in _MEDIA_PROCESS_NAMES:
                        media_sessions.append(session)
                except Exception:
                    continue
            return media_sessions
        except Exception as e:
            logger.debug(f"_get_media_sessions error: {e}")
            return []

    def _get_session_volume(self, session) -> Optional[float]:
        """Obtiene el volumen actual (0-1) de una sesión."""
        try:
            vol = session._ctl.QueryInterface(self._ISimpleAudioVolume)
            return vol.GetMasterVolume()
        except Exception:
            return None

    def _set_session_volume(self, session, volume: float) -> bool:
        """Establece el volumen (0-1) de una sesión."""
        try:
            vol = session._ctl.QueryInterface(self._ISimpleAudioVolume)
            vol.SetMasterVolume(max(0.0, min(1.0, volume)), None)
            return True
        except Exception:
            return False

    def _get_master_volume(self) -> Optional[float]:
        """Obtiene el volumen maestro del sistema (0-1)."""
        if not self._pycaw_available:
            return None
        try:
            devices = self._AudioUtilities.GetSpeakers()
            interface = devices.Activate(
                self._IAudioEndpointVolume._iid_,
                self._CLSCTX_ALL,
                None,
            )
            from ctypes import cast, POINTER
            from comtypes import CLSCTX_ALL as _CA
            master_vol = cast(interface, POINTER(self._IAudioEndpointVolume))
            return master_vol.GetMasterVolumeLevelScalar()
        except Exception as e:
            logger.debug(f"_get_master_volume error: {e}")
            return None

    def _set_master_volume(self, volume: float) -> bool:
        """Establece el volumen maestro del sistema (0-1)."""
        if not self._pycaw_available:
            return False
        try:
            devices = self._AudioUtilities.GetSpeakers()
            interface = devices.Activate(
                self._IAudioEndpointVolume._iid_,
                self._CLSCTX_ALL,
                None,
            )
            from ctypes import cast, POINTER
            master_vol = cast(interface, POINTER(self._IAudioEndpointVolume))
            master_vol.SetMasterVolumeLevelScalar(max(0.0, min(1.0, volume)), None)
            return True
        except Exception as e:
            logger.debug(f"_set_master_volume error: {e}")
            return False

    def _fade_volume(self, get_fn, set_fn, target: float, duration_ms: int, steps: int = 15):
        """
        Hace fade suave desde el volumen actual al target.

        Parámetros:
            get_fn:      Callable que retorna volumen actual (float o None).
            set_fn:      Callable(volume) que establece el volumen.
            target:      Volumen objetivo [0, 1].
            duration_ms: Duración total del fade en ms.
            steps:       Número de pasos del fade.
        """
        current = get_fn()
        if current is None:
            return
        sleep_per_step = duration_ms / 1000.0 / steps
        for i in range(1, steps + 1):
            t = i / steps
            vol = current + (target - current) * t
            set_fn(vol)
            time.sleep(sleep_per_step)

    def _do_duck(self):
        """Ejecuta el fade-out en el hilo de ducking."""
        try:
            sessions = self._get_media_sessions()

            if sessions:
                # Guardar volúmenes originales y hacer fade-out por sesión
                self._session_states = {}
                for session in sessions:
                    try:
                        orig = self._get_session_volume(session)
                        if orig is None:
                            continue
                        pid = session.ProcessId
                        self._session_states[pid] = (session, orig)

                        steps = max(5, int(self._fade_out_ms / 20))
                        sleep_per_step = self._fade_out_ms / 1000.0 / steps
                        for i in range(1, steps + 1):
                            t = i / steps
                            vol = orig + (self._target_volume - orig) * t
                            self._set_session_volume(session, vol)
                            time.sleep(sleep_per_step)
                    except Exception as e:
                        logger.debug(f"duck session error: {e}")
                self._ducked_master = False
            else:
                # No hay sesiones multimedia: atenuar volumen maestro
                master = self._get_master_volume()
                if master is not None:
                    self._master_original = master
                    self._ducked_master = True
                    target = master * self._target_volume  # relativo al actual
                    target = max(0.0, min(1.0, target))
                    steps = max(5, int(self._fade_out_ms / 20))
                    sleep_per_step = self._fade_out_ms / 1000.0 / steps
                    for i in range(1, steps + 1):
                        t = i / steps
                        vol = master + (target - master) * t
                        self._set_master_volume(vol)
                        time.sleep(sleep_per_step)

        except Exception as e:
            logger.warning(f"DuckingManager._do_duck error: {e}")

    def _do_restore(self):
        """Ejecuta el fade-in en el hilo de ducking."""
        try:
            if self._session_states:
                # duck() y restore() corren en hilos daemon distintos cada vez
                # (uno nuevo por llamada). Los objetos COM de pycaw son de un
                # apartment de threading — usar en este hilo un objeto de
                # sesión obtenido en el hilo de duck() es una violación de COM
                # ("COM method call without VTable") que puede terminar en
                # segfault. Reobtenemos las sesiones frescas acá y matcheamos
                # por PID en vez de reusar el objeto viejo.
                fresh_by_pid = {s.ProcessId: s for s in self._get_media_sessions()}
                for pid, (_stale_session, orig) in list(self._session_states.items()):
                    session = fresh_by_pid.get(pid)
                    if session is None:
                        continue
                    try:
                        current = self._get_session_volume(session)
                        if current is None:
                            continue
                        steps = max(5, int(self._fade_in_ms / 20))
                        sleep_per_step = self._fade_in_ms / 1000.0 / steps
                        for i in range(1, steps + 1):
                            t = i / steps
                            vol = current + (orig - current) * t
                            self._set_session_volume(session, vol)
                            time.sleep(sleep_per_step)
                    except Exception as e:
                        logger.debug(f"restore session error: {e}")
                self._session_states = {}

            elif self._ducked_master and self._master_original is not None:
                current = self._get_master_volume()
                if current is not None:
                    steps = max(5, int(self._fade_in_ms / 20))
                    sleep_per_step = self._fade_in_ms / 1000.0 / steps
                    orig = self._master_original
                    for i in range(1, steps + 1):
                        t = i / steps
                        vol = current + (orig - current) * t
                        self._set_master_volume(vol)
                        time.sleep(sleep_per_step)
                self._ducked_master = False
                self._master_original = None

        except Exception as e:
            logger.warning(f"DuckingManager._do_restore error: {e}")
