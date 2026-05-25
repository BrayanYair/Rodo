"""
instalar.pyw — Instalador gráfico de Rodo.

Extensión .pyw = Windows abre esto con pythonw.exe → CERO consola CMD.
El usuario solo ve esta ventana. Nada más.
"""

import sys
import subprocess
import threading
import tkinter as tk
from tkinter import ttk
import os


# ─── Paquetes a instalar ──────────────────────────────────────────────────────
#  (nombre_pip, módulo_python_para_verificar)
PACKAGES = [
    ("SpeechRecognition", "speech_recognition"),
    ("requests",          "requests"),
    ("PyAudio",           "pyaudio"),
    ("python-dotenv",     "dotenv"),
]


# ─── Tema ─────────────────────────────────────────────────────────────────────
BG       = "#1a1a2e"
SURFACE  = "#25253a"
ACCENT   = "#7c6af7"
ACCENT_H = "#9d8fff"
TEXT     = "#e2e8f0"
SUBTEXT  = "#94a3b8"
GREEN    = "#86efac"
YELLOW   = "#fde68a"
RED      = "#fca5a5"

F_BIG    = ("Segoe UI", 22, "bold")
F_SUB    = ("Segoe UI", 10)
F_STEP   = ("Segoe UI", 10)
F_BTN    = ("Segoe UI", 11, "bold")


def _center(win, w, h):
    win.update_idletasks()
    x = (win.winfo_screenwidth()  - w) // 2
    y = (win.winfo_screenheight() - h) // 2
    win.geometry(f"{w}x{h}+{x}+{y}")


# ─── App ──────────────────────────────────────────────────────────────────────

class InstallerApp:

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Rodo — Instalación")
        self.root.configure(bg=BG)
        self.root.resizable(False, False)
        _center(self.root, 420, 400)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._installing = True

        self._build_ui()
        self.root.after(300, self._start_install)  # pequeña pausa para que cargue la UI

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Header
        tk.Label(self.root, text="🎤  Rodo", bg=BG, fg=ACCENT,
                 font=F_BIG).pack(pady=(28, 4))
        self.subtitle = tk.Label(self.root,
                                 text="Instalando lo necesario...",
                                 bg=BG, fg=SUBTEXT, font=F_SUB)
        self.subtitle.pack(pady=(0, 20))

        # Pasos
        steps_frame = tk.Frame(self.root, bg=BG)
        steps_frame.pack(fill="x", padx=48)

        self._step_widgets = {}
        for pkg_name, _ in PACKAGES:
            row = tk.Frame(steps_frame, bg=BG)
            row.pack(fill="x", pady=3)

            icon = tk.Label(row, text="○", bg=BG, fg=SUBTEXT,
                            font=("Segoe UI", 11), width=3, anchor="w")
            icon.pack(side="left")

            label = tk.Label(row, text=pkg_name, bg=BG, fg=SUBTEXT,
                             font=F_STEP, anchor="w")
            label.pack(side="left", fill="x")

            self._step_widgets[pkg_name] = (icon, label)

        # Barra de progreso
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Rodo.Horizontal.TProgressbar",
            troughcolor=SURFACE, background=ACCENT,
            lightcolor=ACCENT, darkcolor=ACCENT,
            bordercolor=SURFACE, thickness=6,
        )
        self.progress = ttk.Progressbar(
            self.root, style="Rodo.Horizontal.TProgressbar",
            orient="horizontal", length=330, mode="determinate",
        )
        self.progress.pack(pady=(22, 6))

        self.status_var = tk.StringVar(value="Iniciando...")
        tk.Label(self.root, textvariable=self.status_var,
                 bg=BG, fg=SUBTEXT, font=("Segoe UI", 9)).pack()

        # Botón (oculto hasta terminar)
        self.btn = tk.Button(
            self.root, text="Abrir Rodo  →",
            bg=ACCENT, fg="white",
            activebackground=ACCENT_H, activeforeground="white",
            relief="flat", cursor="hand2", font=F_BTN,
            padx=28, pady=10, bd=0,
            command=self._open_rodo,
        )
        self.btn.bind("<Enter>", lambda e: self.btn.config(bg=ACCENT_H))
        self.btn.bind("<Leave>", lambda e: self.btn.config(bg=ACCENT))

    def _set_step(self, pkg_name: str, state: str):
        """state: 'pending' | 'running' | 'done' | 'skipped' | 'error'"""
        icon_lbl, text_lbl = self._step_widgets[pkg_name]
        icons  = {"pending": "○", "running": "◌", "done": "●", "skipped": "●", "error": "✕"}
        colors = {"pending": SUBTEXT, "running": TEXT, "done": GREEN, "skipped": GREEN, "error": RED}
        icon_lbl.config(text=icons[state],  fg=colors[state])
        text_lbl.config(fg=colors[state])

    # ── Instalación en hilo separado ──────────────────────────────────────────

    def _start_install(self):
        t = threading.Thread(target=self._install_thread, daemon=True)
        t.start()

    def _install_thread(self):
        failed  = []
        total   = len(PACKAGES)

        for i, (pkg_name, import_name) in enumerate(PACKAGES):
            # Marcar como "instalando"
            self._ui(lambda p=pkg_name: self._set_step(p, "running"))
            self._ui(lambda p=pkg_name: self.status_var.set(f"Instalando {p}..."))

            success = self._install_package(pkg_name, import_name)

            state = "done" if success else "error"
            self._ui(lambda p=pkg_name, s=state: self._set_step(p, s))
            if not success:
                failed.append(pkg_name)

            pct = int((i + 1) / total * 100)
            self._ui(lambda v=pct: self.progress.config(value=v))

        self._ui(lambda: self._on_done(failed))

    def _install_package(self, pkg_name: str, import_name: str) -> bool:
        """Intenta importar primero; si falla, instala con pip."""
        try:
            __import__(import_name)
            return True   # ya estaba instalado
        except ImportError:
            pass

        # Intentar instalar con pip
        ok = self._pip_install(pkg_name)
        if ok:
            return True

        # PyAudio tiene binarios especiales en Windows — intentar pipwin
        if pkg_name == "PyAudio":
            self._pip_install("pipwin")
            ok = self._pipwin_install("pyaudio")
            if ok:
                return True

        return False

    def _pip_install(self, package: str) -> bool:
        try:
            r = subprocess.run(
                [sys.executable, "-m", "pip", "install", package, "--quiet"],
                capture_output=True, timeout=120,
            )
            return r.returncode == 0
        except Exception:
            return False

    def _pipwin_install(self, package: str) -> bool:
        try:
            r = subprocess.run(
                [sys.executable, "-m", "pipwin", "install", package],
                capture_output=True, timeout=120,
            )
            return r.returncode == 0
        except Exception:
            return False

    # ── Finalización ──────────────────────────────────────────────────────────

    def _on_done(self, failed: list):
        self._installing = False

        if not failed:
            self.subtitle.config(text="¡Todo listo!", fg=GREEN)
            self.status_var.set("")
            self.progress.config(value=100)
            self.btn.config(text="Abrir Rodo  →", bg=ACCENT)
        else:
            self.subtitle.config(
                text=f"Algunos componentes fallaron: {', '.join(failed)}", fg=YELLOW)
            self.status_var.set("Puedes intentar abrirlo de todas formas.")
            self.btn.config(text="Abrir Rodo de todas formas  →", bg="#5a5490")

        self.btn.pack(pady=(16, 28))

    def _open_rodo(self):
        rodo = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Rodo.bat")
        if os.path.exists(rodo):
            subprocess.Popen(rodo, shell=True)
        self.root.destroy()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _ui(self, fn):
        """Ejecuta fn en el hilo de la UI."""
        self.root.after(0, fn)

    def _on_close(self):
        if self._installing:
            pass   # no cerrar mientras instala
        else:
            self.root.destroy()

    def run(self):
        self.root.mainloop()


# ─── Punto de entrada ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    InstallerApp().run()
