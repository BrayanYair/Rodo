"""
setup_gui.py — Asistente de configuración visual para rodolfo-amigo.

Se abre automáticamente la primera vez que el usuario corre la app.
No requiere ningún archivo .env ni conocimiento técnico.
"""

import tkinter as tk
from tkinter import ttk, messagebox
import threading

from config_manager import save_config, load_config, reset_config


# ─── Colores y fuentes ────────────────────────────────────────────────────────

BG        = "#1e1e2e"   # fondo oscuro
SURFACE   = "#2a2a3e"   # tarjetas
ACCENT    = "#7c6af7"   # morado principal
ACCENT_HO = "#9d8fff"   # hover
TEXT      = "#cdd6f4"   # texto principal
SUBTEXT   = "#a6adc8"   # texto secundario
GREEN     = "#a6e3a1"
RED       = "#f38ba8"
YELLOW    = "#f9e2af"

FONT_TITLE  = ("Segoe UI", 16, "bold")
FONT_LABEL  = ("Segoe UI", 10)
FONT_SMALL  = ("Segoe UI", 9)
FONT_BUTTON = ("Segoe UI", 10, "bold")
FONT_INPUT  = ("Segoe UI", 10)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _center(win, w, h):
    win.update_idletasks()
    sw = win.winfo_screenwidth()
    sh = win.winfo_screenheight()
    x  = (sw - w) // 2
    y  = (sh - h) // 2
    win.geometry(f"{w}x{h}+{x}+{y}")


def _entry(parent, **kw) -> tk.Entry:
    return tk.Entry(
        parent,
        bg=SURFACE, fg=TEXT,
        insertbackground=TEXT,
        relief="flat",
        highlightthickness=1,
        highlightbackground=ACCENT,
        highlightcolor=ACCENT_HO,
        font=FONT_INPUT,
        **kw,
    )


def _label(parent, text, color=TEXT, font=FONT_LABEL, **kw) -> tk.Label:
    return tk.Label(parent, text=text, bg=BG, fg=color, font=font, **kw)


def _sublabel(parent, text, **kw) -> tk.Label:
    return tk.Label(parent, text=text, bg=BG, fg=SUBTEXT, font=FONT_SMALL, **kw)


def _btn(parent, text, command, bg=ACCENT, fg="white", **kw) -> tk.Button:
    b = tk.Button(
        parent, text=text, command=command,
        bg=bg, fg=fg, activebackground=ACCENT_HO, activeforeground="white",
        relief="flat", cursor="hand2", font=FONT_BUTTON,
        padx=16, pady=8, bd=0,
        **kw,
    )
    b.bind("<Enter>", lambda e: b.config(bg=ACCENT_HO))
    b.bind("<Leave>", lambda e: b.config(bg=bg))
    return b


# ─── Ventana principal de setup ───────────────────────────────────────────────

def run_setup(prefill: dict | None = None) -> dict | None:
    """
    Muestra el asistente de configuración.
    Retorna el dict de config si el usuario guarda, o None si cierra/cancela.
    """
    pre = prefill or {}
    result: dict | None = None

    root = tk.Tk()
    root.title("Configuración — Rodolfo Amigo")
    root.configure(bg=BG)
    root.resizable(False, False)
    _center(root, 460, 510)

    # ── Título ────────────────────────────────────────────────────────────────
    tk.Label(root, text="🎤  Rodolfo Amigo", bg=BG, fg=ACCENT,
             font=("Segoe UI", 20, "bold")).pack(pady=(24, 2))
    _sublabel(root, "Configuración inicial — solo se hace una vez").pack(pady=(0, 18))

    # ── Contenedor ────────────────────────────────────────────────────────────
    frame = tk.Frame(root, bg=BG)
    frame.pack(fill="x", padx=32)

    # ── Nombre ────────────────────────────────────────────────────────────────
    _label(frame, "Tu nombre").pack(anchor="w")
    _sublabel(frame, "Aparecerá en Discord cuando hables").pack(anchor="w")
    nombre_var = tk.StringVar(value=pre.get("nombre", ""))
    nombre_entry = _entry(frame, textvariable=nombre_var, width=42)
    nombre_entry.pack(fill="x", pady=(4, 14), ipady=6)

    # ── Separador ─────────────────────────────────────────────────────────────
    tk.Frame(frame, bg=SURFACE, height=1).pack(fill="x", pady=(0, 14))

    # ── Modo de conexión ──────────────────────────────────────────────────────
    _label(frame, "Modo de conexión").pack(anchor="w")

    mode_var = tk.StringVar(value=pre.get("mode", "webhook"))

    modes_frame = tk.Frame(frame, bg=BG)
    modes_frame.pack(fill="x", pady=(6, 14))

    def _radio(parent, text, sub, value):
        f = tk.Frame(parent, bg=SURFACE, padx=12, pady=10)
        f.pack(side="left", expand=True, fill="x", padx=(0, 6))
        rb = tk.Radiobutton(f, text=text, variable=mode_var, value=value,
                            bg=SURFACE, fg=TEXT, selectcolor=SURFACE,
                            activebackground=SURFACE, activeforeground=ACCENT,
                            font=FONT_LABEL, cursor="hand2",
                            command=_on_mode_change)
        rb.pack(anchor="w")
        tk.Label(f, text=sub, bg=SURFACE, fg=SUBTEXT,
                 font=FONT_SMALL, wraplength=140, justify="left").pack(anchor="w")

    _radio(modes_frame, "Discord webhook", "El dueño del bot\nte da una URL",    "webhook")
    _radio(modes_frame, "API directa ⚡",  "El bot tiene\nservidor propio",      "api")

    # ── Campos según el modo ──────────────────────────────────────────────────
    webhook_frame = tk.Frame(frame, bg=BG)
    api_frame     = tk.Frame(frame, bg=BG)

    # Webhook
    _label(webhook_frame, "URL del webhook de Discord").pack(anchor="w")
    _sublabel(webhook_frame, "Empieza con https://discord.com/api/webhooks/...").pack(anchor="w")
    webhook_var = tk.StringVar(value=pre.get("webhook_url", ""))
    _entry(webhook_frame, textvariable=webhook_var, width=42).pack(fill="x", pady=(4, 0), ipady=6)

    # API directa
    _label(api_frame, "URL del servidor").pack(anchor="w")
    _sublabel(api_frame, "Ej: https://rodolfo.midominio.com  o  http://203.0.113.1:5000").pack(anchor="w")
    api_url_var = tk.StringVar(value=pre.get("api_url", ""))
    _entry(api_frame, textvariable=api_url_var, width=42).pack(fill="x", pady=(4, 10), ipady=6)

    _label(api_frame, "Token de acceso").pack(anchor="w")
    _sublabel(api_frame, "Te lo da el dueño del servidor").pack(anchor="w")
    api_token_var = tk.StringVar(value=pre.get("api_token", ""))
    token_entry = _entry(api_frame, textvariable=api_token_var, width=42, show="•")
    token_entry.pack(fill="x", pady=(4, 0), ipady=6)

    # Toggle mostrar/ocultar token
    show_token = tk.BooleanVar(value=False)
    def _toggle_token():
        token_entry.config(show="" if show_token.get() else "•")
    tk.Checkbutton(api_frame, text="Mostrar token", variable=show_token,
                   bg=BG, fg=SUBTEXT, selectcolor=BG, activebackground=BG,
                   activeforeground=SUBTEXT, font=FONT_SMALL,
                   command=_toggle_token).pack(anchor="w", pady=(4, 0))

    def _on_mode_change():
        if mode_var.get() == "webhook":
            api_frame.pack_forget()
            webhook_frame.pack(fill="x")
        else:
            webhook_frame.pack_forget()
            api_frame.pack(fill="x")

    # Mostrar el frame correcto al inicio
    if mode_var.get() == "webhook":
        webhook_frame.pack(fill="x")
    else:
        api_frame.pack(fill="x")

    # ── Botones ───────────────────────────────────────────────────────────────
    status_var = tk.StringVar()
    status_lbl = tk.Label(root, textvariable=status_var, bg=BG, fg=RED,
                          font=FONT_SMALL)
    status_lbl.pack(pady=(14, 0))

    def _validate_and_save():
        nonlocal result

        nombre = nombre_var.get().strip()
        if not nombre:
            status_var.set("⚠  Escribe tu nombre para continuar.")
            status_lbl.config(fg=YELLOW)
            nombre_entry.focus_set()
            return

        mode = mode_var.get()
        cfg  = {"nombre": nombre, "mode": mode,
                "webhook_url": "", "api_url": "", "api_token": ""}

        if mode == "webhook":
            url = webhook_var.get().strip()
            if not url.startswith("https://discord.com/api/webhooks/"):
                status_var.set("⚠  La URL del webhook no parece correcta.")
                status_lbl.config(fg=YELLOW)
                return
            cfg["webhook_url"] = url
        else:
            url   = api_url_var.get().strip().rstrip("/")
            token = api_token_var.get().strip()
            if not url:
                status_var.set("⚠  Ingresa la URL del servidor.")
                status_lbl.config(fg=YELLOW)
                return
            if not token:
                status_var.set("⚠  Ingresa el token de acceso.")
                status_lbl.config(fg=YELLOW)
                return
            cfg["api_url"]   = url
            cfg["api_token"] = token

        # Guardar
        try:
            save_config(cfg)
            result = cfg
            status_var.set("✓ Configuración guardada.")
            status_lbl.config(fg=GREEN)
            root.after(800, root.destroy)
        except Exception as e:
            status_var.set(f"Error al guardar: {e}")
            status_lbl.config(fg=RED)

    btn_frame = tk.Frame(root, bg=BG)
    btn_frame.pack(pady=(8, 24))

    _btn(btn_frame, "Guardar y continuar →", _validate_and_save).pack(side="left", padx=6)

    root.mainloop()
    return result


# ─── Ventana de reconfiguración ───────────────────────────────────────────────

def run_reconfigure() -> dict | None:
    """
    Abre el setup precargado con la config actual.
    Útil para el menú 'Reconfigurar' o si el usuario quiere cambiar algo.
    """
    current = load_config()
    return run_setup(prefill=current)


# ─── Test rápido ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    cfg = run_setup()
    if cfg:
        print("Config guardada:", cfg)
    else:
        print("Cancelado.")
