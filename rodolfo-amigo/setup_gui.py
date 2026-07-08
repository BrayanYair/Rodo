"""
setup_gui.py — Asistente de configuración visual para Byarox con diseño premium 3D.

Se abre automáticamente la primera vez. El usuario no toca ningún archivo.
"""

import tkinter as tk
from pathlib import Path
from PIL import Image, ImageTk

from config_manager import save_config, load_config


# ─── Tema visual ──────────────────────────────────────────────────────────────

BG       = "#0f0f1a"
SURFACE  = "#18182b"
ACCENT   = "#7c6af7"
ACCENT_H = "#9d8fff"
TEXT     = "#f1f5f9"
SUBTEXT  = "#94a3b8"
GREEN    = "#86efac"
YELLOW   = "#fde68a"
RED      = "#fca5a5"

F_TITLE  = ("Segoe UI", 20, "bold")
F_HEAD   = ("Segoe UI", 11, "bold")
F_BODY   = ("Segoe UI", 10)
F_SMALL  = ("Segoe UI", 9)
F_BTN    = ("Segoe UI", 11, "bold")


def _center(win, w, h):
    win.update_idletasks()
    sw = win.winfo_screenwidth()
    sh = win.winfo_screenheight()
    h  = min(h, sh - 80)
    x  = (sw - w) // 2
    y  = max(10, (sh - h) // 2)
    win.geometry(f"{w}x{h}+{x}+{y}")


def draw_rounded_rect(canvas, x1, y1, x2, y2, radius, **kwargs):
    points = [
        x1 + radius, y1,
        x1 + radius, y1,
        x2 - radius, y1,
        x2 - radius, y1,
        x2, y1,
        x2, y1 + radius,
        x2, y1 + radius,
        x2, y2 - radius,
        x2, y2 - radius,
        x2, y2,
        x2 - radius, y2,
        x2 - radius, y2,
        x1 + radius, y2,
        x1 + radius, y2,
        x1, y2,
        x1, y2 - radius,
        x1, y2 - radius,
        x1, y1 + radius,
        x1, y1 + radius,
        x1, y1
    ]
    return canvas.create_polygon(points, **kwargs, smooth=True)


# ─── Widgets Personalizados ───────────────────────────────────────────────────

class RoundedCanvasEntry(tk.Canvas):
    def __init__(self, parent, textvariable, show="", bg_color=BG, surface_color=SURFACE,
                 border_color="#2e2e4a", focus_color=ACCENT, radius=10):
        super().__init__(parent, bg=bg_color, bd=0, highlightthickness=0, height=36)
        self.textvariable = textvariable
        self.show = show
        self.surface_color = surface_color
        self.border_color = border_color
        self.focus_color = focus_color
        self.current_border = border_color
        self.radius = radius

        self.entry = tk.Entry(
            self, textvariable=self.textvariable, show=self.show,
            bg=self.surface_color, fg=TEXT, insertbackground=TEXT,
            relief="flat", font=F_BODY, bd=0
        )

        self.bind("<Configure>", self._draw)
        self.entry.bind("<FocusIn>", self._on_focus_in)
        self.entry.bind("<FocusOut>", self._on_focus_out)

    def _draw(self, event=None):
        self.delete("all")
        w = self.winfo_width()
        h = self.winfo_height()
        if w < 10 or h < 10:
            return

        # Dibuja borde y fondo
        draw_rounded_rect(self, 0, 0, w, h, self.radius, fill=self.current_border)
        draw_rounded_rect(self, 1, 1, w-1, h-1, self.radius - 1, fill=self.surface_color)

        # Ubica la caja de texto real adentro
        self.create_window(12, h//2, window=self.entry, anchor="w", width=w-24)

    def _on_focus_in(self, event):
        self.current_border = self.focus_color
        self._draw()

    def _on_focus_out(self, event):
        self.current_border = self.border_color
        self._draw()

    def config(self, **kwargs):
        if "show" in kwargs:
            self.entry.config(show=kwargs.pop("show"))
        super().config(**kwargs)


class RoundedCanvasButton(tk.Canvas):
    def __init__(self, parent, text, command, bg_color=BG, btn_color=ACCENT,
                 hover_color=ACCENT_H, active_color="#5e4ec2", fg="white", radius=10):
        super().__init__(parent, bg=bg_color, bd=0, highlightthickness=0, height=44, cursor="hand2")
        self.text = text
        self.command = command
        self.btn_color = btn_color
        self.hover_color = hover_color
        self.active_color = active_color
        self.current_color = btn_color
        self.fg = fg
        self.radius = radius

        self.bind("<Configure>", self._draw)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)

    def _draw(self, event=None):
        self.delete("all")
        w = self.winfo_width()
        h = self.winfo_height()
        if w < 10 or h < 10:
            return
        draw_rounded_rect(self, 0, 0, w, h, self.radius, fill=self.current_color)
        self.create_text(w//2, h//2, text=self.text, fill=self.fg, font=F_BTN)

    def _on_enter(self, event):
        self.current_color = self.hover_color
        self._draw()

    def _on_leave(self, event):
        self.current_color = self.btn_color
        self._draw()

    def _on_press(self, event):
        self.current_color = self.active_color
        self._draw()

    def _on_release(self, event):
        self.current_color = self.hover_color
        self._draw()
        if self.command:
            self.command()


def _label(parent, text, color=TEXT, font=F_BODY, anchor="w", **kw):
    return tk.Label(parent, text=text, bg=BG, fg=color, font=font,
                    anchor=anchor, **kw)


def _sep(parent):
    tk.Frame(parent, bg=SURFACE, height=1).pack(fill="x", pady=8)


# ─── Ventana principal ────────────────────────────────────────────────────────

def run_setup(prefill: dict | None = None) -> dict | None:
    pre    = prefill or {}
    result = None

    root = tk.Tk()
    root.title("Byarox - Configuración")
    root.configure(bg=BG)
    root.resizable(True, True)
    _center(root, 440, 560)

    # ── Variables ─────────────────────────────────────────────────────────────
    nombre_var    = tk.StringVar(value=pre.get("nombre",    ""))
    api_url_var   = tk.StringVar(value=pre.get("api_url",   ""))
    api_token_var = tk.StringVar(value=pre.get("api_token", ""))
    show_var      = tk.BooleanVar(value=False)
    status_var    = tk.StringVar()

    # ── Lógica de guardado ────────────────────────────────────────────────────
    def _save(_event=None):
        nonlocal result
        nombre = nombre_var.get().strip()
        url    = api_url_var.get().strip().rstrip("/")
        token  = api_token_var.get().strip()

        if not nombre:
            status_var.set("⚠  Escribe tu apodo.")
            return
        if not url:
            status_var.set("⚠  Ingresa la dirección del servidor.")
            return
        if not url.startswith("http"):
            status_var.set("⚠  Debe empezar con http:// o https://")
            return
        if not token:
            status_var.set("⚠  Ingresa la contraseña de acceso.")
            return

        existing = load_config()
        cfg = {
            **existing,
            "nombre":      nombre,
            "mode":        "api",
            "webhook_url": "",
            "api_url":     url,
            "api_token":   token,
        }
        try:
            save_config(cfg)
            result = cfg
            status_var.set("✓  ¡Listo! Arrancando...")
            root.after(600, root.destroy)
        except Exception as e:
            status_var.set(f"⚠  Error: {e}")

    # ── BOTÓN fijo abajo ──────────────────────────────────────────────────────
    bottom = tk.Frame(root, bg=BG)
    bottom.pack(side="bottom", fill="x", padx=36, pady=(0, 16))

    tk.Label(bottom, textvariable=status_var, bg=BG,
             fg=YELLOW, font=F_SMALL).pack(pady=(4, 6))

    btn = RoundedCanvasButton(bottom, text="Empezar  →", command=_save)
    btn.pack(fill="x")

    # ── Contenido ─────────────────────────────────────────────────────────────
    content = tk.Frame(root, bg=BG)
    content.pack(side="top", fill="both", expand=True, padx=36)

    # Header / Logo
    logo_path = Path(__file__).parent / "rodo_logo.png"
    if logo_path.exists():
        try:
            img = Image.open(logo_path)
            img = img.resize((100, 100), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            logo_lbl = tk.Label(content, image=photo, bg=BG)
            logo_lbl.image = photo  # mantener referencia
            logo_lbl.pack(pady=(16, 2))
        except Exception:
            tk.Label(content, text="🎤  Byarox", bg=BG, fg=ACCENT, font=F_TITLE).pack(pady=(16, 2))
    else:
        tk.Label(content, text="🎤  Byarox", bg=BG, fg=ACCENT, font=F_TITLE).pack(pady=(16, 2))

    _label(content, "Configuración rápida — solo se hace una vez",
           color=SUBTEXT, font=F_SMALL, anchor="center").pack(pady=(0, 10))

    # Tu apodo
    _label(content, "Tu apodo", font=F_HEAD).pack(anchor="w")
    _label(content, "Cómo quieres que te identifique Byarox",
           color=SUBTEXT, font=F_SMALL).pack(anchor="w")
    nombre_entry = RoundedCanvasEntry(content, nombre_var)
    nombre_entry.pack(fill="x", pady=(4, 2))
    _label(content, "Ej: Pepe, El gordo, Camila...",
           color=SUBTEXT, font=F_SMALL).pack(anchor="w", pady=(0, 2))

    _sep(content)

    # Datos del servidor
    _label(content, "Datos del servidor", font=F_HEAD).pack(anchor="w")
    info = tk.Frame(content, bg=SURFACE, padx=12, pady=8)
    info.pack(fill="x", pady=(4, 8))
    tk.Label(info, text="ℹ  El dueño de Byarox te envía estos datos\n   por WhatsApp o Discord.",
             bg=SURFACE, fg=SUBTEXT, font=F_SMALL, justify="left").pack(anchor="w")

    _label(content, "Dirección del servidor").pack(anchor="w")
    api_url_entry = RoundedCanvasEntry(content, api_url_var)
    api_url_entry.pack(fill="x", pady=(4, 2))
    _label(content, "Ej: http://45.76.123.200:5000",
           color=SUBTEXT, font=F_SMALL).pack(anchor="w", pady=(0, 6))

    _label(content, "Contraseña de acceso").pack(anchor="w")
    token_entry = RoundedCanvasEntry(content, api_token_var, show="•")
    token_entry.pack(fill="x", pady=(4, 2))

    def _toggle():
        token_entry.config(show="" if show_var.get() else "•")
    tk.Checkbutton(content, text="Mostrar contraseña", variable=show_var,
                   bg=BG, fg=SUBTEXT, selectcolor=BG,
                   activebackground=BG, activeforeground=SUBTEXT,
                   font=F_SMALL, command=_toggle, bd=0, highlightthickness=0).pack(anchor="w", pady=(4, 0))

    root.bind("<Return>", _save)

    root.mainloop()
    return result


def run_reconfigure() -> dict | None:
    return run_setup(prefill=load_config())


if __name__ == "__main__":
    cfg = run_setup()
    print("Config:", cfg)
