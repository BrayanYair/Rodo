"""
overlay.py — Indicador visual de estado de Rodolfo

Ventana siempre-encima, sin bordes, semi-transparente.
- Idle    : punto gris 28×28 px (casi invisible)
- Activo  : pill con texto que desaparece sola en ~3.5 s

Estados:
  idle        → ● gris          (escuchando en background, nada que mostrar)
  processing  → ◌ amarillo      "Procesando"  (recibió audio, haciendo STT)
  speaking    → ♪ azul          "Hablando"    (TTS activo)
  playing     → ▶ violeta       "Música"      (música sonando, sin comando activo)
  error       → × rojo          "Error"       (algo salió mal)

Uso:
    from overlay import StatusOverlay
    ov = StatusOverlay()
    ov.start()            # lanza hilo daemon, no bloquea
    ov.set_state("processing")
    ov.set_state("idle")

Arrastre: click izquierdo + mover.
Cerrar: doble click derecho (emergencia).
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
    # state       símbolo  color       texto visible
    "idle":      ("●",    "#4a4a4a",  ""),
    "processing":("◌",    "#FFB800",  "Procesando"),
    "speaking":  ("♪",    "#4499FF",  "Hablando"),
    "playing":   ("▶",    "#9B59B6",  "Música"),
    "error":     ("×",    "#E74C3C",  "Error"),
}

_EXPAND_SECS  = 3.5    # segundos que permanece expandido antes de colapsar
_DOT_W        = 28     # ancho colapsado (cuadrado)
_DOT_H        = 28     # alto colapsado
_PILL_H       = 34     # alto cuando está expandido
_BG           = "#1a1a1a"
_FG           = "#eeeeee"
_ALPHA        = 0.85
_FONT_SYM     = ("Segoe UI Symbol", 11, "bold")
_FONT_TXT     = ("Segoe UI", 9)
_DEFAULT_POS  = (30, 30)   # top-left si no hay posición guardada
_PULSE_STATES = {"processing", "speaking"}   # estados que latirán
_PULSE_DIM    = 0.35   # factor de oscurecimiento en el pulso (0=negro, 1=original)


def _dim(hex_color: str, factor: float = _PULSE_DIM) -> str:
    """Oscurece un color hex por un factor para el efecto de pulso."""
    r = int(hex_color[1:3], 16)
    g = int(hex_color[3:5], 16)
    b = int(hex_color[5:7], 16)
    return f"#{int(r * factor):02x}{int(g * factor):02x}{int(b * factor):02x}"


class StatusOverlay:
    """Overlay de estado no intrusivo. Thread-safe."""

    def __init__(self):
        self._state   = "idle"
        self._lock    = threading.Lock()
        self._expire      = 0.0      # epoch → momento de colapsar el pill
        self._pulse_on    = False    # alterna cada tick para el latido
        self._root        = None
        self._sym_lbl     = None
        self._txt_lbl     = None
        self._txt_visible = False
        self._drag_ox     = 0
        self._drag_oy     = 0
        self._pos         = self._load_pos()
        self._thread  = threading.Thread(
            target=self._run, daemon=True, name="rodolfo-overlay"
        )

    # ── API pública ──────────────────────────────────────────────────────────────

    def start(self):
        """Lanza el overlay en un hilo daemon. No bloquea."""
        self._thread.start()

    def set_state(self, state: str):
        """Cambia el estado visual (thread-safe).
        'idle' hace colapsar al punto de inmediato."""
        with self._lock:
            prev = self._state
            self._state = state
            if state != "idle":
                self._expire = time.time() + _EXPAND_SECS
            else:
                self._expire = 0.0

        if prev != state and self._root:
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

        root.overrideredirect(True)               # sin bordes ni barra de título
        root.wm_attributes("-topmost", True)       # siempre encima
        try:
            root.wm_attributes("-alpha", _ALPHA)   # transparencia (falla en algunos GPU)
        except tk.TclError:
            pass
        root.configure(bg=_BG)

        # ── Widgets ──────────────────────────────────────────────────────────────
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
        # txt_lbl se agrega al layout solo cuando hay texto

        # ── Arrastre ─────────────────────────────────────────────────────────────
        for w in (root, frame, self._sym_lbl, self._txt_lbl):
            w.bind("<ButtonPress-1>",   self._drag_start)
            w.bind("<B1-Motion>",       self._drag_move)
            w.bind("<ButtonRelease-1>", self._drag_end)

        # Doble click derecho → ocultar (emergencia si estorba)
        root.bind("<Double-Button-3>", lambda _e: root.withdraw())
        # Un click derecho → volver a mostrar si estaba oculto
        root.bind("<Button-3>", lambda _e: root.deiconify())

        # ── Posición inicial ──────────────────────────────────────────────────────
        x, y = self._pos
        root.geometry(f"{_DOT_W}x{_DOT_H}+{x}+{y}")

        # ── Loop de auto-colapso ─────────────────────────────────────────────────
        root.after(400, self._tick)
        root.mainloop()

    def _tick(self):
        """Corre cada 400 ms: alterna el pulso y refresca."""
        if self._root:
            self._pulse_on = not self._pulse_on
            self._refresh()
            self._root.after(400, self._tick)

    def _refresh(self):
        """Actualiza widgets y tamaño de ventana según el estado actual."""
        if not self._root:
            return

        with self._lock:
            state  = self._state
            expand = (state != "idle") and (time.time() < self._expire)

        sym, color, text = _STATES.get(state, _STATES["idle"])

        # Pulso: alterna entre el color normal y uno más oscuro en estados activos
        display_color = _dim(color) if (state in _PULSE_STATES and self._pulse_on) else color
        self._sym_lbl.config(text=sym, fg=display_color)

        if expand and text:
            # ── Expandido: punto + texto ──────────────────────────────────────
            self._txt_lbl.config(text=text)
            if not self._txt_visible:
                self._txt_lbl.pack(side="left", padx=(2, 4))
                self._txt_visible = True
            # ancho dinámico: ~7 px por carácter + márgenes
            w = _DOT_W + len(text) * 7 + 22
            self._root.geometry(f"{w}x{_PILL_H}")
        else:
            # ── Colapsado: solo punto ─────────────────────────────────────────
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
