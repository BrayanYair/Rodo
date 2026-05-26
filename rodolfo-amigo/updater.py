"""
updater.py — Sistema de actualización automática de Rodo.

Flujo:
  1. Al arrancar, verifica en GitHub si hay versión nueva (silencioso, 5s timeout).
  2. Si hay update: muestra ventana con changelog y barra de descarga.
  3. Descarga el nuevo Rodo.exe en segundo plano.
  4. Al terminar: crea un script que espera a que el proceso actual cierre,
     reemplaza el .exe y relanza. El usuario no toca nada.

En desarrollo (sin .exe): muestra la notificación pero no hace el reemplazo.
"""

import os
import sys
import json
import threading
import tempfile
import subprocess
import tkinter as tk
from tkinter import ttk

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

from version import VERSION, UPDATE_CHECK_URL


# ─── Helpers de versión ───────────────────────────────────────────────────────

def _parse(v: str) -> tuple:
    try:
        return tuple(int(x) for x in v.strip().lstrip("v").split("."))
    except Exception:
        return (0, 0, 0)


# ─── Check ────────────────────────────────────────────────────────────────────

def check_update() -> dict | None:
    """
    Consulta GitHub. Devuelve el dict de version.json si hay versión más nueva,
    o None si estamos al día / sin internet.
    """
    if not HAS_REQUESTS:
        return None
    try:
        r = requests.get(UPDATE_CHECK_URL, timeout=5)
        if r.status_code != 200:
            return None
        info = r.json()
        if _parse(info.get("version", "0")) > _parse(VERSION):
            return info
        return None
    except Exception:
        return None


# ─── Ventana de actualización ─────────────────────────────────────────────────

BG      = "#1a1a2e"
SURFACE = "#25253a"
ACCENT  = "#7c6af7"
ACCENT_H= "#9d8fff"
TEXT    = "#e2e8f0"
SUBTEXT = "#94a3b8"
GREEN   = "#86efac"
RED     = "#fca5a5"


def _center(win, w, h):
    win.update_idletasks()
    x = (win.winfo_screenwidth()  - w) // 2
    y = (win.winfo_screenheight() - h) // 2
    win.geometry(f"{w}x{h}+{x}+{y}")


class UpdateWindow:
    """
    Ventana modal de actualización.
    Muestra changelog, descarga en segundo plano y aplica el update.
    """

    def __init__(self, info: dict):
        self.info    = info
        self._root   = tk.Tk()
        self._root.title("Rodo — Actualización disponible")
        self._root.configure(bg=BG)
        self._root.resizable(False, False)
        _center(self._root, 380, 260)
        self._root.protocol("WM_DELETE_WINDOW", self._skip)
        self._build()

    def _build(self):
        version   = self.info.get("version",   "?")
        changelog = self.info.get("changelog", "Mejoras y correcciones.")

        tk.Label(self._root, text="🎤  Nueva versión de Rodo",
                 bg=BG, fg=ACCENT,
                 font=("Segoe UI", 14, "bold")).pack(pady=(22, 4))

        tk.Label(self._root, text=f"Versión {version}  (tienes {VERSION})",
                 bg=BG, fg=SUBTEXT,
                 font=("Segoe UI", 9)).pack()

        tk.Label(self._root, text=changelog,
                 bg=BG, fg=TEXT, font=("Segoe UI", 10),
                 wraplength=320, justify="center").pack(pady=(10, 16))

        # Progreso (oculto hasta que empiece la descarga)
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("U.Horizontal.TProgressbar",
                        troughcolor=SURFACE, background=ACCENT,
                        lightcolor=ACCENT, darkcolor=ACCENT,
                        bordercolor=SURFACE, thickness=6)

        self._bar = ttk.Progressbar(self._root, style="U.Horizontal.TProgressbar",
                                    orient="horizontal", length=320,
                                    mode="determinate")

        self._status = tk.StringVar()
        self._status_lbl = tk.Label(self._root, textvariable=self._status,
                                    bg=BG, fg=SUBTEXT, font=("Segoe UI", 9))

        # Botones
        btn_row = tk.Frame(self._root, bg=BG)
        btn_row.pack()

        self._btn_update = tk.Button(
            btn_row, text="Actualizar ahora",
            bg=ACCENT, fg="white", activebackground=ACCENT_H,
            relief="flat", cursor="hand2",
            font=("Segoe UI", 10, "bold"),
            padx=18, pady=8, bd=0,
            command=self._start_download,
        )
        self._btn_update.pack(side="left", padx=6)

        tk.Button(
            btn_row, text="Después",
            bg=SURFACE, fg=SUBTEXT, activebackground="#313150",
            relief="flat", cursor="hand2",
            font=("Segoe UI", 10),
            padx=18, pady=8, bd=0,
            command=self._skip,
        ).pack(side="left", padx=6)

    # ── Descarga ──────────────────────────────────────────────────────────────

    def _start_download(self):
        self._btn_update.config(state="disabled", text="Descargando...")
        self._bar.pack(pady=(16, 4))
        self._status_lbl.pack()
        self._root.geometry("380x310")

        t = threading.Thread(target=self._download_thread, daemon=True)
        t.start()

    def _download_thread(self):
        url = self.info.get("download_url", "")
        if not url:
            self._ui(lambda: self._status.set("Error: URL de descarga no encontrada."))
            return

        try:
            tmp   = tempfile.mkdtemp()
            dest  = os.path.join(tmp, "Rodo_new.exe")
            resp  = requests.get(url, stream=True, timeout=60)
            total = int(resp.headers.get("content-length", 0))
            done  = 0

            with open(dest, "wb") as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)
                        done += len(chunk)
                        if total:
                            pct    = int(done / total * 100)
                            mb     = done  / 1024 / 1024
                            total_ = total / 1024 / 1024
                            self._ui(lambda p=pct, m=mb, t=total_: (
                                self._bar.config(value=p),
                                self._status.set(f"{m:.1f} / {t:.1f} MB"),
                            ))

            self._ui(lambda: self._status.set("Aplicando... Rodo se reiniciará."))
            self._apply(dest)

        except Exception as e:
            self._ui(lambda err=str(e): self._status.set(f"Error: {err}"))
            self._ui(lambda: self._btn_update.config(state="normal",
                                                      text="Reintentar"))

    def _apply(self, new_exe: str):
        """
        Crea un bat que espera a que este proceso cierre, reemplaza el exe
        y lo relanza. Funciona porque Windows permite escribir sobre un .exe
        que ya no está en ejecución.
        """
        # En desarrollo (no frozen) solo avisamos
        if not getattr(sys, "frozen", False):
            self._ui(lambda: self._status.set(
                "Modo desarrollo: descarga OK, reemplazo solo funciona en .exe"))
            return

        current = sys.executable   # ruta absoluta de Rodo.exe en ejecución

        bat = os.path.join(tempfile.gettempdir(), "rodo_update.bat")
        with open(bat, "w") as f:
            f.write(
                f"@echo off\n"
                f"timeout /t 2 /nobreak >nul\n"
                f"copy /y \"{new_exe}\" \"{current}\"\n"
                f"ie4uinit.exe -show\n"
                f"start \"\" \"{current}\"\n"
                f"del \"%~f0\"\n"
            )

        subprocess.Popen(bat, shell=True, creationflags=subprocess.CREATE_NO_WINDOW)
        self._ui(lambda: self._root.after(800, sys.exit))

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _skip(self):
        self._root.destroy()

    def _ui(self, fn):
        self._root.after(0, fn)

    def show(self):
        self._root.mainloop()


# ─── Punto de entrada para amigo.py ──────────────────────────────────────────

def check_and_show_update():
    """
    Verifica si hay update y muestra la ventana si es necesario.
    Bloquea hasta que el usuario decida (actualizar o saltar).
    Llamar ANTES de arrancar la app principal.
    """
    info = check_update()
    if info:
        UpdateWindow(info).show()
