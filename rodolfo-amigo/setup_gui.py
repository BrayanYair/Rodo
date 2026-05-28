"""
setup_gui.py — Asistente de configuración visual para Rodo.

Se abre automáticamente la primera vez. El usuario no toca ningún archivo.
"""

import tkinter as tk

from config_manager import save_config, load_config


# ─── Tema visual ──────────────────────────────────────────────────────────────

BG       = "#1a1a2e"
SURFACE  = "#25253a"
ACCENT   = "#7c6af7"
ACCENT_H = "#9d8fff"
TEXT     = "#e2e8f0"
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


def _entry(parent, var, show=""):
    e = tk.Entry(
        parent, textvariable=var, show=show,
        bg=SURFACE, fg=TEXT, insertbackground=TEXT,
        relief="flat", font=F_BODY,
        highlightthickness=1,
        highlightbackground="#3a3a5c",
        highlightcolor=ACCENT,
    )
    e.bind("<FocusIn>",  lambda ev: e.config(highlightbackground=ACCENT))
    e.bind("<FocusOut>", lambda ev: e.config(highlightbackground="#3a3a5c"))
    return e


def _label(parent, text, color=TEXT, font=F_BODY, anchor="w", **kw):
    return tk.Label(parent, text=text, bg=BG, fg=color, font=font,
                    anchor=anchor, **kw)


def _sep(parent):
    tk.Frame(parent, bg=SURFACE, height=1).pack(fill="x", pady=6)


# ─── Ventana principal ────────────────────────────────────────────────────────

def run_setup(prefill: dict | None = None) -> dict | None:
    pre    = prefill or {}
    result = None

    root = tk.Tk()
    root.title("Rodo — Configuración")
    root.configure(bg=BG)
    root.resizable(True, True)
    _center(root, 440, 500)

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

        # Cargar config existente para preservar campos que no se editan aquí
        # (discord_id, access_token, etc.) — evita borrarlos al reconfigurar.
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

    # ── BOTÓN fijo abajo (se empaca PRIMERO para que siempre sea visible) ─────
    bottom = tk.Frame(root, bg=BG)
    bottom.pack(side="bottom", fill="x", padx=36, pady=(0, 12))

    tk.Label(bottom, textvariable=status_var, bg=BG,
             fg=YELLOW, font=F_SMALL).pack(pady=(4, 4))

    btn = tk.Button(
        bottom, text="Empezar  →", command=_save,
        bg=ACCENT, fg="white", activebackground=ACCENT_H, activeforeground="white",
        relief="flat", cursor="hand2", font=F_BTN,
        padx=28, pady=10, bd=0,
    )
    btn.bind("<Enter>", lambda e: btn.config(bg=ACCENT_H))
    btn.bind("<Leave>", lambda e: btn.config(bg=ACCENT))
    btn.pack(fill="x")

    # ── Contenido (se empaca después, ocupa el resto del espacio) ─────────────
    content = tk.Frame(root, bg=BG)
    content.pack(side="top", fill="both", expand=True, padx=36)

    # Header
    tk.Label(content, text="🎤  Rodo", bg=BG, fg=ACCENT,
             font=F_TITLE).pack(pady=(16, 2))
    _label(content, "Configuración rápida — solo se hace una vez",
           color=SUBTEXT, font=F_SMALL, anchor="center").pack(pady=(0, 10))

    # Tu apodo
    _label(content, "Tu apodo", font=F_HEAD).pack(anchor="w")
    _label(content, "Cómo quieres que te identifique Rodo",
           color=SUBTEXT, font=F_SMALL).pack(anchor="w")
    nombre_entry = _entry(content, nombre_var)
    nombre_entry.pack(fill="x", pady=(4, 2), ipady=6)
    _label(content, "Ej: Pepe, El gordo, Camila...",
           color=SUBTEXT, font=F_SMALL).pack(anchor="w", pady=(0, 2))

    _sep(content)

    # Datos del servidor
    _label(content, "Datos del servidor", font=F_HEAD).pack(anchor="w")
    info = tk.Frame(content, bg=SURFACE, padx=10, pady=6)
    info.pack(fill="x", pady=(4, 8))
    tk.Label(info, text="ℹ  El dueño de Rodo te envía estos datos\n   por WhatsApp o Discord.",
             bg=SURFACE, fg=SUBTEXT, font=F_SMALL, justify="left").pack(anchor="w")

    _label(content, "Dirección del servidor").pack(anchor="w")
    _entry(content, api_url_var).pack(fill="x", pady=(4, 2), ipady=6)
    _label(content, "Ej: http://45.76.123.200:5000",
           color=SUBTEXT, font=F_SMALL).pack(anchor="w", pady=(0, 6))

    _label(content, "Contraseña de acceso").pack(anchor="w")
    token_entry = _entry(content, api_token_var, show="•")
    token_entry.pack(fill="x", pady=(4, 2), ipady=6)

    def _toggle():
        token_entry.config(show="" if show_var.get() else "•")
    tk.Checkbutton(content, text="Mostrar contraseña", variable=show_var,
                   bg=BG, fg=SUBTEXT, selectcolor=BG,
                   activebackground=BG, activeforeground=SUBTEXT,
                   font=F_SMALL, command=_toggle).pack(anchor="w", pady=(2, 0))

    # Enter guarda desde cualquier campo
    root.bind("<Return>", _save)

    root.mainloop()
    return result


def run_reconfigure() -> dict | None:
    return run_setup(prefill=load_config())


if __name__ == "__main__":
    cfg = run_setup()
    print("Config:", cfg)
