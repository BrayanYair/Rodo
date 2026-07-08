"""
tray.py — Ícono de Byarox en la bandeja del sistema (system tray).

Muestra el logo de Byarox junto al reloj mientras el asistente está activo.
Click derecho → menú: Mostrar/Ocultar overlay, Cerrar Byarox.
"""

import os
import sys
import threading
from pathlib import Path


def _icon_path() -> Path:
    """Devuelve la ruta al rodo_logo.ico dentro del bundle o del directorio del script."""
    base = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).parent
    return base / "rodo_logo.ico"


def start_tray(overlay=None, on_quit=None):
    """
    Arranca el ícono de bandeja en un hilo daemon.
    Devuelve el objeto Icon (o None si falla).
    """
    try:
        import pystray
        from PIL import Image

        img  = Image.open(_icon_path())

        # ── Callbacks ────────────────────────────────────────────────────────────
        def _show(icon, item):
            if overlay:
                overlay.show()

        def _hide(icon, item):
            if overlay:
                overlay.hide()

        def _quit(icon, item):
            icon.stop()
            if on_quit:
                on_quit()
            else:
                os._exit(0)

        # ── Menú ─────────────────────────────────────────────────────────────────
        menu = pystray.Menu(
            pystray.MenuItem("Mostrar overlay",  _show),
            pystray.MenuItem("Ocultar overlay",  _hide),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Cerrar Byarox",    _quit),
        )

        icon = pystray.Icon("Byarox", img, "Byarox", menu)

        t = threading.Thread(target=icon.run, daemon=True, name="rodo-tray")
        t.start()
        return icon

    except Exception as e:
        print(f"[TRAY] No disponible: {e}")
        return None
