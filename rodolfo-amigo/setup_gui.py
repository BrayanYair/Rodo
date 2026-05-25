"""
setup_gui.py — Asistente de configuración visual para Rodo.

Se abre automáticamente la primera vez. El usuario no toca ningún archivo.
"""

import tkinter as tk
from tkinter import messagebox

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

F_TITLE  = ("Segoe UI", 22, "bold")
F_HEAD   = ("Segoe UI", 11, "bold")
F_BODY   = ("Segoe UI", 10)
F_SMALL  = ("Segoe UI", 9)
F_BTN    = ("Segoe UI", 11, "bold")


def _center(win, w, h):
    win.update_idletasks()
    x = (win.winfo_screenwidth()  - w) // 2
    y = (win.winfo_screenheight() - h) // 2
    win.geometry(f"{w}x{h}+{x}+{y}")


def _entry(parent, var, show="", width=44):
    e = tk.Entry(
        parent, textvariable=var, show=show, width=width,
        bg=SURFACE, fg=TEXT, insertbackground=TEXT,
        relief="flat", font=F_BODY,
        highlightthickness=1,
        highlightbackground="#3a3a5c",
        highlightcolor=ACCENT,
    )
    # Focus highlight
    e.bind("<FocusIn>",  lambda ev: e.config(highlightbackground=ACCENT))
    e.bind("<FocusOut>", lambda ev: e.config(highlightbackground="#3a3a5c"))
    return e


def _label(parent, text, color=TEXT, font=F_BODY, anchor="w", **kw):
    return tk.Label(parent, text=text, bg=BG, fg=color, font=font,
                    anchor=anchor, **kw)


def _sep(parent):
    tk.Frame(parent, bg=SURFACE, height=1).pack(fill="x", pady=12)


# ─── Ventana principal ────────────────────────────────────────────────────────

def run_setup(prefill: dict | None = None) -> dict | None:
    """
    Muestra el asistente de configuración.
    Retorna el config guardado o None si el usuario cierra sin guardar.
    """
    pre    = prefill or {}
    result = None

    root = tk.Tk()
    root.title("Rodo — Configuración")
    root.configure(bg=BG)
    root.resizable(False, False)
    _center(root, 440, 490)

    # ── Header ────────────────────────────────────────────────────────────────
    tk.Label(root, text="🎤  Rodo", bg=BG, fg=ACCENT,
             font=F_TITLE).pack(pady=(28, 2))
    _label(root, "Configuración rápida — solo se hace una vez",
           color=SUBTEXT, font=F_SMALL, anchor="center").pack(pady=(0, 20))

    # ── Formulario ────────────────────────────────────────────────────────────
    form = tk.Frame(root, bg=BG)
    form.pack(fill="x", padx=36)

    # ── Tu apodo ──────────────────────────────────────────────────────────────
    _label(form, "Tu apodo", font=F_HEAD).pack(anchor="w")
    _label(form, "Cómo quieres que te identifique Rodo",
           color=SUBTEXT, font=F_SMALL).pack(anchor="w")

    nombre_var = tk.StringVar(value=pre.get("nombre", ""))
    nombre_entry = _entry(form, nombre_var)
    nombre_entry.pack(fill="x", pady=(6, 4), ipady=7)

    _label(form, "Ej: Pepe, El gordo, Camila...",
           color=SUBTEXT, font=F_SMALL).pack(anchor="w", pady=(0, 4))

    _sep(form)

    # ── Datos del servidor ────────────────────────────────────────────────────
    _label(form, "Datos del servidor", font=F_HEAD).pack(anchor="w")

    # Caja explicativa
    info = tk.Frame(form, bg=SURFACE, padx=12, pady=8)
    info.pack(fill="x", pady=(6, 12))
    tk.Label(info, text="ℹ  El dueño de Rodo te envía estos datos\n   por WhatsApp o Discord.",
             bg=SURFACE, fg=SUBTEXT, font=F_SMALL, justify="left").pack(anchor="w")

    # URL
    _label(form, "Dirección del servidor").pack(anchor="w")
    api_url_var = tk.StringVar(value=pre.get("api_url", ""))
    _entry(form, api_url_var).pack(fill="x", pady=(4, 4), ipady=7)
    _label(form, "Ej: http://45.76.123.200:5000",
           color=SUBTEXT, font=F_SMALL).pack(anchor="w", pady=(0, 10))

    # Token
    _label(form, "Contraseña de acceso").pack(anchor="w")
    api_token_var = tk.StringVar(value=pre.get("api_token", ""))
    token_entry   = _entry(form, api_token_var, show="•")
    token_entry.pack(fill="x", pady=(4, 4), ipady=7)

    show_var = tk.BooleanVar(value=False)
    def _toggle():
        token_entry.config(show="" if show_var.get() else "•")
    tk.Checkbutton(form, text="Mostrar contraseña", variable=show_var,
                   bg=BG, fg=SUBTEXT, selectcolor=BG,
                   activebackground=BG, activeforeground=SUBTEXT,
                   font=F_SMALL, command=_toggle).pack(anchor="w")

    # ── Estado / error ────────────────────────────────────────────────────────
    status_var = tk.StringVar()
    status_lbl = tk.Label(root, textvariable=status_var, bg=BG,
                          fg=YELLOW, font=F_SMALL)
    status_lbl.pack(pady=(10, 0))

    # ── Botón guardar ─────────────────────────────────────────────────────────
    def _save():
        nonlocal result

        nombre = nombre_var.get().strip()
        url    = api_url_var.get().strip().rstrip("/")
        token  = api_token_var.get().strip()

        # Validar
        if not nombre:
            status_var.set("⚠  Escribe tu apodo para continuar.")
            nombre_entry.focus_set()
            return
        if not url:
            status_var.set("⚠  Ingresa la dirección del servidor.")
            return
        if not url.startswith("http"):
            status_var.set("⚠  La dirección debe empezar con http:// o https://")
            return
        if not token:
            status_var.set("⚠  Ingresa la contraseña de acceso.")
            return

        cfg = {
            "nombre":      nombre,
            "mode":        "api",
            "webhook_url": "",
            "api_url":     url,
            "api_token":   token,
        }

        try:
            save_config(cfg)
            result = cfg
            status_var.set("✓  ¡Listo!")
            status_lbl.config(fg=GREEN)
            root.after(700, root.destroy)
        except Exception as e:
            status_var.set(f"Error al guardar: {e}")
            status_lbl.config(fg=RED)

    btn = tk.Button(
        root, text="Empezar  →", command=_save,
        bg=ACCENT, fg="white", activebackground=ACCENT_H, activeforeground="white",
        relief="flat", cursor="hand2", font=F_BTN,
        padx=28, pady=10, bd=0,
    )
    btn.bind("<Enter>", lambda e: btn.config(bg=ACCENT_H))
    btn.bind("<Leave>", lambda e: btn.config(bg=ACCENT))
    btn.pack(pady=(8, 28))

    root.mainloop()
    return result


def run_reconfigure() -> dict | None:
    """Abre el setup precargado con los datos actuales (para 'Cambiar config')."""
    return run_setup(prefill=load_config())


if __name__ == "__main__":
    cfg = run_setup()
    print("Config:", cfg)
