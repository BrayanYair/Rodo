"""
overlay.py — Indicador visual de estado para Rodolfo-Amigo

Ventana siempre-encima, sin bordes, semi-transparente.
Muestra en qué paso está el companion: escuchando → procesando → enviando → ok/error.

Estados:
  idle        → ● gris           (esperando, sin actividad)
  listening   → ◉ verde pulsando "Escuchando"  (mic activo, esperando que hables)
  processing  → ◌ amarillo pulsando "Procesando"  (haciendo STT)
  sending     → ◌ azul pulsando  "Enviando"    (mandando a Discord)
  ok          → ● verde fijo     "Enviado"     (llegó ✓, desaparece solo)
  error       → × rojo fijo      "Error"       (algo falló)

Arrastre: click izquierdo + mover.
Ocultar: doble click derecho.
La posición se guarda en overlay_pos.json al soltar.
"""

import json
import threading
import time
import tkinter as tk
from pathlib import Path

# ── Configuración visual ────────────────────────────────────────────────────────

_CFG = Path(__file__).parent / "overlay_pos.json"

_STATES = {
    # state        símbolo  color       texto visible
    "idle":       ("●",    "#4a4a4a",  ""),
    "listening":  ("◉",    "#2ECC71",  "Escuchando"),
    "processing": ("◌",    "#F39C12",  "Procesando"),
    "sending":    ("◌",    "#3498DB",  "Enviando"),
    "ok":         ("●",    "#2ECC71",  "Enviado"),
    "error":      ("×",    "#E74C3C",  "Error"),
}

_PULSE_STATES = {"listening", "processing", "sending"}
_PULSE_DIM    = 0.35

_EXPAND_SECS = 3.0    # segundos visibles antes de colapsar (ok/error)
_DOT_W       = 28
_DOT_H       = 28
_PILL_H      = 34
_BG          = "#1a1a1a"
_FG          = "#eeeeee"
_ALPHA       = 0.85
_FONT_SYM    = ("Segoe UI Symbol", 11, "bold")
_FONT_TXT    = ("Segoe UI", 9)
_DEFAULT_POS = (30, 80)   # un poco más abajo que el host para no solaparse si corren juntos


def _dim(hex_color: str, factor: float = _PULSE_DIM) -> str:
    r = int(hex_color[1:3], 16)
    g = int(hex_color[3:5], 16)
    b = int(hex_color[5:7], 16)
    return f"#{int(r * factor):02x}{int(g * factor):02x}{int(b * factor):02x}"


class StatusOverlay:
    """Overlay de estado para rodolfo-amigo. Thread-safe."""

    def __init__(self):
        self._state       = "idle"
        self._lock        = threading.Lock()
        self._expire      = 0.0
        self._pulse_on    = False
        self._root        = None
        self._sym_lbl     = None
        self._txt_lbl     = None
        self._txt_visible = False
        self._drag_ox     = 0
        self._drag_oy     = 0
        self._pos         = self._load_pos()
        self._thread      = threading.Thread(
            target=self._run, daemon=True, name="amigo-overlay"
        )

    # ── API pública ──────────────────────────────────────────────────────────────

    def start(self):
        self._thread.start()

    def hide(self):
        """Oculta el overlay (por comando de voz)."""
        if self._root:
            self._root.after(0, self._root.withdraw)

    def show(self):
        """Muestra el overlay (por comando de voz)."""
        if self._root:
            self._root.after(0, self._root.deiconify)

    def set_state(self, state: str):
        """Cambia el estado (thread-safe).
        Los estados pulsantes se mantienen hasta que se cambie a otro.
        Los estados finales (ok, error) se auto-colapsan tras _EXPAND_SECS."""
        with self._lock:
            self._state = state
            if state in ("ok", "error", "idle"):
                # ok y error muestran el texto y luego colapsan a idle
                self._expire = time.time() + _EXPAND_SECS if state != "idle" else 0.0
            else:
                # listening/processing/sending: no expiran solos, latirán hasta que
                # el código cambie el estado
                self._expire = time.time() + 60.0   # seguro de emergencia: 1 min máx
        if self._root:
            self._root.after(0, self._refresh)

    # ── Posición persistente ─────────────────────────────────────────────────────

    def _load_pos(self):
        try:
            d = json.loads(_CFG.read_text(encoding="utf-8"))
            return (int(d["x"]), int(d["y"]))
        except Exception:
            return _DEFAULT_POS

    def _save_pos(self, x: int, y: int):
        try:
            _CFG.write_text(json.dumps({"x": x, "y": y}), encoding="utf-8")
        except Exception:
            pass

    # ── Hilo tkinter ─────────────────────────────────────────────────────────────

    def _run(self):
        root = tk.Tk()
        self._root = root

        root.overrideredirect(True)
        root.wm_attributes("-topmost", True)
        try:
            root.wm_attributes("-alpha", _ALPHA)
        except tk.TclError:
            pass
        root.configure(bg=_BG)

        frame = tk.Frame(root, bg=_BG, padx=4, pady=2)
        frame.pack(fill="both", expand=True)

        self._sym_lbl = tk.Label(
            frame, text="●", fg=_STATES["idle"][1],
            bg=_BG, font=_FONT_SYM,
        )
        self._sym_lbl.pack(side="left")

        self._txt_lbl = tk.Label(
            frame, text="", fg=_FG, bg=_BG,
            font=_FONT_TXT, padx=3,
        )

        for w in (root, frame, self._sym_lbl, self._txt_lbl):
            w.bind("<ButtonPress-1>",   self._drag_start)
            w.bind("<B1-Motion>",       self._drag_move)
            w.bind("<ButtonRelease-1>", self._drag_end)
            w.bind("<Button-3>",        self._show_menu)

        # Menú contextual (click derecho)
        self._menu = tk.Menu(root, tearoff=0, bg="#1a1a2e", fg="#e2e8f0",
                             activebackground="#7c6af7", activeforeground="white",
                             font=("Segoe UI", 9), bd=0)
        self._menu.add_command(label="Ocultar",      command=root.withdraw)
        self._menu.add_separator()
        self._menu.add_command(label="Cerrar Rodo",  command=self._quit)

        x, y = self._pos
        root.geometry(f"{_DOT_W}x{_DOT_H}+{x}+{y}")
        root.after(400, self._tick)
        root.mainloop()

    def _tick(self):
        if self._root:
            self._pulse_on = not self._pulse_on
            self._refresh()
            self._root.after(400, self._tick)

    def _refresh(self):
        if not self._root:
            return

        with self._lock:
            state  = self._state
            now    = time.time()
            # Estados finales (ok/error) colapsan tras expirar → vuelven a idle
            if state in ("ok", "error") and now > self._expire:
                self._state = "idle"
                state = "idle"
                self._expire = 0.0
            # Estados pulsantes: si expira el seguro de emergencia, también idle
            elif state in _PULSE_STATES and now > self._expire:
                self._state = "idle"
                state = "idle"
                self._expire = 0.0
            expand = (state != "idle") and (now < self._expire or state in _PULSE_STATES)

        sym, color, text = _STATES.get(state, _STATES["idle"])

        # Pulso: alterna color en estados activos
        if state in _PULSE_STATES and self._pulse_on:
            display_color = _dim(color)
        else:
            display_color = color

        self._sym_lbl.config(text=sym, fg=display_color)

        if expand and text:
            self._txt_lbl.config(text=text)
            if not self._txt_visible:
                self._txt_lbl.pack(side="left", padx=(2, 4))
                self._txt_visible = True
            w = _DOT_W + len(text) * 7 + 22
            self._root.geometry(f"{w}x{_PILL_H}")
        else:
            if self._txt_visible:
                self._txt_lbl.pack_forget()
                self._txt_visible = False
            self._root.geometry(f"{_DOT_W}x{_DOT_H}")

    # ── Arrastre ─────────────────────────────────────────────────────────────────

    def _drag_start(self, event):
        self._drag_ox = event.x_root - self._root.winfo_x()
        self._drag_oy = event.y_root - self._root.winfo_y()

    def _drag_move(self, event):
        x = event.x_root - self._drag_ox
        y = event.y_root - self._drag_oy
        self._root.geometry(f"+{x}+{y}")

    def _drag_end(self, _event):
        x = self._root.winfo_x()
        y = self._root.winfo_y()
        self._save_pos(x, y)

    def _show_menu(self, event):
        try:
            self._menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._menu.grab_release()

    def _quit(self):
        import os
        self._save_pos(self._root.winfo_x(), self._root.winfo_y())
        os._exit(0)
