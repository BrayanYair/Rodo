"""
overlay.py — Indicador visual de estado interactivo 3D para Rodolfo-Amigo.

Robot 3D animado, siempre-encima, flotante, con transparencia ALPHA REAL.

Render: ventana Win32 pura (capa con UpdateLayeredWindow) → bordes suaves,
sin flicker ni desaparición (no mezcla tkinter con la capa).
Fallback: si Win32 no está disponible, usa tkinter con color-key.

Estados: idle / listening / processing / sending / error / talking
  * Parpadeo horneado en el render (idle, talking)
  * Cross-fade suave (~220ms) entre estados
  * Reactivo al volumen real del micro en "listening" (set_audio_level)
"""

import json
import math
import os
import threading
import time
from pathlib import Path
from PIL import Image, ImageTk, ImageDraw, ImageFont, ImageChops

# ── Configuración visual ────────────────────────────────────────────────────────
_CFG = Path(__file__).parent / "overlay_pos.json"

_TEXTS = {
    "idle": "", "listening": "Escuchando", "processing": "Procesando",
    "sending": "Enviando", "talking": "", "ok": "Enviado", "error": "Error",
}

_EXPAND_SECS = 3.0
_DOT_W       = 80
_DOT_H       = 80
_IMG_SZ      = 64
_TRANS_SECS  = 0.22
_AUDIO_SCALE = 0.20
_PILL_BG     = (18, 18, 36, 235)
_PILL_BORDER = (46, 46, 74, 255)
_TEXT_COLOR  = (255, 255, 255, 255)
_DEFAULT_POS = (30, 80)

_TRANS_BG    = "#000001"   # color-key del fallback tkinter


# ════════════════════════════════════════════════════════════════════════════
#  Win32
# ════════════════════════════════════════════════════════════════════════════
_WIN32_OK = False
if os.name == "nt":
    try:
        import ctypes
        from ctypes import wintypes

        _user32 = ctypes.windll.user32
        _gdi32  = ctypes.windll.gdi32
        _kernel32 = ctypes.windll.kernel32

        WS_EX_LAYERED   = 0x00080000
        WS_EX_TOPMOST   = 0x00000008
        WS_EX_TOOLWINDOW= 0x00000080
        WS_POPUP        = 0x80000000
        ULW_ALPHA       = 0x00000002
        AC_SRC_OVER     = 0x00
        AC_SRC_ALPHA    = 0x01
        BI_RGB          = 0
        DIB_RGB_COLORS  = 0
        SW_HIDE         = 0
        SW_SHOWNOACTIVATE = 4
        WM_DESTROY      = 0x0002
        WM_TIMER        = 0x0113
        WM_LBUTTONDOWN  = 0x0201
        WM_MOUSEMOVE    = 0x0200
        WM_LBUTTONUP    = 0x0202
        WM_RBUTTONUP    = 0x0205
        WM_COMMAND      = 0x0111
        WM_APP_HIDE     = 0x8001
        WM_APP_SHOW     = 0x8002
        TPM_RETURNCMD   = 0x0100
        TPM_RIGHTBUTTON = 0x0002
        MF_STRING       = 0x0000
        MF_SEPARATOR    = 0x0800
        MK_LBUTTON      = 0x0001

        class _BLENDFUNCTION(ctypes.Structure):
            _fields_ = [("BlendOp", ctypes.c_byte), ("BlendFlags", ctypes.c_byte),
                        ("SourceConstantAlpha", ctypes.c_byte), ("AlphaFormat", ctypes.c_byte)]

        class _POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        class _SIZE(ctypes.Structure):
            _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]

        class _BMIH(ctypes.Structure):
            _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_long),
                        ("biHeight", ctypes.c_long), ("biPlanes", ctypes.c_uint16),
                        ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                        ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_long),
                        ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", ctypes.c_uint32),
                        ("biClrImportant", ctypes.c_uint32)]

        class _BITMAPINFO(ctypes.Structure):
            _fields_ = [("bmiHeader", _BMIH), ("bmiColors", ctypes.c_uint32 * 3)]

        _WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_long, wintypes.HWND, wintypes.UINT,
                                      wintypes.WPARAM, wintypes.LPARAM)

        class _WNDCLASS(ctypes.Structure):
            _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", _WNDPROC),
                        ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                        ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                        ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                        ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]

        _user32.DefWindowProcW.restype = ctypes.c_long
        _user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        _user32.GetDC.restype = wintypes.HDC
        _user32.GetDC.argtypes = [wintypes.HWND]
        _user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
        _user32.UpdateLayeredWindow.restype = wintypes.BOOL
        _user32.UpdateLayeredWindow.argtypes = [
            wintypes.HWND, wintypes.HDC, ctypes.POINTER(_POINT), ctypes.POINTER(_SIZE),
            wintypes.HDC, ctypes.POINTER(_POINT), wintypes.DWORD,
            ctypes.POINTER(_BLENDFUNCTION), wintypes.DWORD]
        _gdi32.CreateCompatibleDC.restype = wintypes.HDC
        _gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
        _gdi32.CreateDIBSection.restype = wintypes.HBITMAP
        _gdi32.CreateDIBSection.argtypes = [
            wintypes.HDC, ctypes.POINTER(_BITMAPINFO), wintypes.UINT,
            ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
        _gdi32.SelectObject.restype = wintypes.HGDIOBJ
        _gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
        _gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
        _gdi32.DeleteDC.argtypes = [wintypes.HDC]
        _user32.CreateWindowExW.restype = wintypes.HWND
        _user32.CreateWindowExW.argtypes = [
            wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
        _user32.RegisterClassW.argtypes = [ctypes.POINTER(_WNDCLASS)]
        _user32.RegisterClassW.restype = wintypes.ATOM
        _kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        _kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        _user32.GetCursorPos.argtypes = [ctypes.POINTER(_POINT)]
        _user32.SetTimer.argtypes = [wintypes.HWND, ctypes.c_void_p, wintypes.UINT, ctypes.c_void_p]
        _user32.CreatePopupMenu.restype = wintypes.HMENU
        _user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_void_p, wintypes.LPCWSTR]
        _user32.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int,
                                           ctypes.c_int, wintypes.HWND, ctypes.c_void_p]
        _user32.TrackPopupMenu.restype = wintypes.BOOL
        _user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]

        _WIN32_OK = True
    except Exception:
        _WIN32_OK = False


def _push_layered(hwnd, img_rgba, wx, wy):
    """Pinta img_rgba (PIL RGBA) en hwnd con alpha real por píxel (premultiplicado BGRA)."""
    w, h = img_rgba.size
    r, g, b, a = img_rgba.split()
    pr = ImageChops.multiply(r, a)
    pg = ImageChops.multiply(g, a)
    pb = ImageChops.multiply(b, a)
    raw = Image.merge("RGBA", (pb, pg, pr, a)).tobytes("raw", "RGBA")

    screen_dc = _user32.GetDC(None)
    mem_dc    = _gdi32.CreateCompatibleDC(screen_dc)
    bmi = _BITMAPINFO()
    bmi.bmiHeader.biSize        = ctypes.sizeof(_BMIH)
    bmi.bmiHeader.biWidth       = w
    bmi.bmiHeader.biHeight      = -h
    bmi.bmiHeader.biPlanes      = 1
    bmi.bmiHeader.biBitCount    = 32
    bmi.bmiHeader.biCompression = BI_RGB
    bits = ctypes.c_void_p()
    hbmp = _gdi32.CreateDIBSection(mem_dc, ctypes.byref(bmi), DIB_RGB_COLORS,
                                   ctypes.byref(bits), None, 0)
    old = _gdi32.SelectObject(mem_dc, hbmp)
    ctypes.memmove(bits, raw, len(raw))

    size  = _SIZE(w, h)
    src   = _POINT(0, 0)
    dst   = _POINT(int(wx), int(wy))
    blend = _BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
    _user32.UpdateLayeredWindow(hwnd, screen_dc, ctypes.byref(dst), ctypes.byref(size),
                                mem_dc, ctypes.byref(src), 0, ctypes.byref(blend), ULW_ALPHA)
    _gdi32.SelectObject(mem_dc, old)
    _gdi32.DeleteObject(hbmp)
    _gdi32.DeleteDC(mem_dc)
    _user32.ReleaseDC(None, screen_dc)


def _load_font(size):
    for name in ("segoeuib.ttf", "seguisb.ttf", "arialbd.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


# ════════════════════════════════════════════════════════════════════════════
#  Cache de frames
# ════════════════════════════════════════════════════════════════════════════
class AnimatedMascotCache:
    _STATE_ALIASES = {"ok": "sending"}
    _STATES = ("idle", "listening", "processing", "sending", "error", "talking")

    def __init__(self, base_folder, size=(_IMG_SZ, _IMG_SZ)):
        self.base_folder = Path(base_folder)
        self.size = size
        self._frames_by_state = {}
        self._pil_cache = {}
        for state in self._STATES:
            self._frames_by_state[state] = self._load_state(state)

    def _load_state(self, state):
        out = []
        for folder in (self.base_folder / state, self.base_folder):
            if not folder.exists():
                continue
            for i in range(1, 100):
                p = folder / f"frame_{i:02d}.png"
                if p.exists():
                    try:
                        out.append(Image.open(p).convert("RGBA").resize(self.size, Image.Resampling.LANCZOS))
                    except Exception:
                        pass
            if out:
                return out
        fallback = self.base_folder.parent / "rodo_logo.png"
        if fallback.exists():
            try:
                return [Image.open(fallback).convert("RGBA").resize(self.size, Image.Resampling.LANCZOS)]
            except Exception:
                pass
        return []

    def _resolve(self, state):
        return self._STATE_ALIASES.get(state, state)

    @property
    def frames(self):
        return self._frames_by_state.get("idle") or []

    def frames_for(self, state):
        st = self._resolve(state)
        return self._frames_by_state.get(st) or self._frames_by_state.get("idle") or []

    def get_pil(self, frame_index, opacity, state="idle"):
        st = self._resolve(state)
        frames = self._frames_by_state.get(st) or self._frames_by_state.get("idle") or []
        if not frames:
            return None
        idx = frame_index % len(frames)
        okey = round(max(0.0, min(1.0, opacity)), 1)
        key = (st, idx, okey)
        if key not in self._pil_cache:
            im = frames[idx].copy()
            if okey < 1.0:
                r, g, b, a = im.split()
                a = a.point(lambda p: int(p * okey))
                im.putalpha(a)
            self._pil_cache[key] = im
        return self._pil_cache[key]


# ════════════════════════════════════════════════════════════════════════════
#  Overlay
# ════════════════════════════════════════════════════════════════════════════
class StatusOverlay:
    def __init__(self):
        self._state    = "idle"
        self._lock     = threading.Lock()
        self._expire   = 0.0
        self._pos      = self._load_pos()
        self._img_cache = AnimatedMascotCache(Path(__file__).parent / "frames", size=(_IMG_SZ, _IMG_SZ))

        # Cross-fade
        self._displayed_state  = "idle"
        self._prev_state       = None
        self._prev_frame_idx   = 0
        self._prev_opacity     = 1.0
        self._transition_start = 0.0
        self._last_frame_idx   = 0
        self._last_opacity     = 1.0
        self._audio_level      = 0.0

        self._wx, self._wy = self._pos
        self._font   = _load_font(15)
        self._hidden = False

        # Win32
        self._hwnd = None
        self._wndproc_ref = None
        self._dragging = False
        self._drag_dx = 0
        self._drag_dy = 0
        self._win_w = _DOT_W
        self._win_h = _DOT_H

        # Fallback tkinter
        self._use_tk = not _WIN32_OK
        self._root = None
        self._canvas = None
        self._photo_ref = None

        self._thread = threading.Thread(target=self._run, daemon=True, name="amigo-overlay")

    # ── API pública ──────────────────────────────────────────────────────────
    def start(self):
        self._thread.start()

    def set_state(self, state):
        with self._lock:
            self._state = state
            if state in ("ok", "error", "idle"):
                self._expire = time.time() + _EXPAND_SECS if state != "idle" else 0.0
            else:
                self._expire = time.time() + 60.0

    def get_state(self):
        with self._lock:
            return self._state

    def set_audio_level(self, level):
        with self._lock:
            self._audio_level = max(0.0, min(1.0, float(level)))

    def hide(self):
        self._hidden = True
        if self._hwnd:
            try: _user32.PostMessageW(self._hwnd, WM_APP_HIDE, 0, 0)
            except Exception: pass
        elif self._root:
            self._root.after(0, self._root.withdraw)

    def show(self):
        self._hidden = False
        if self._hwnd:
            try: _user32.PostMessageW(self._hwnd, WM_APP_SHOW, 0, 0)
            except Exception: pass
        elif self._root:
            self._root.after(0, self._root.deiconify)

    # ── Persistencia ─────────────────────────────────────────────────────────
    def _load_pos(self):
        try:
            d = json.loads(_CFG.read_text(encoding="utf-8"))
            return (int(d["x"]), int(d["y"]))
        except Exception:
            return _DEFAULT_POS

    def _save_pos(self, x, y):
        try:
            _CFG.write_text(json.dumps({"x": int(x), "y": int(y)}), encoding="utf-8")
        except Exception:
            pass

    # ── Lógica de animación (compartida) ────────────────────────────────────────
    def _frame_idx_for(self, state, t, n):
        rates = {"idle": 12, "listening": 13, "processing": 11,
                 "sending": 14, "talking": 14, "error": 18}
        return int(t * rates.get(state, 12)) % n

    def _opacity_for(self, state, t):
        if state == "idle":
            return 0.62
        if state == "listening":
            return 0.70 + 0.30 * (0.5 + 0.5 * math.sin(t * 9.0))
        return 1.0

    def _offset_for(self, state, t):
        if state == "idle":       return math.cos(t * 1.0) * 0.5, math.sin(t * 1.4) * 1.0
        if state == "listening":  return math.sin(t * 2.6) * 1.0, math.cos(t * 1.8) * 0.7
        if state == "processing": return 0.0, -abs(math.sin(t * 3.0)) * 1.4
        if state == "sending":    return 0.0, math.sin(t * 8.0) * 1.2
        if state == "talking":    return 0.0, math.sin(t * 3.5) * 0.9
        if state == "error":      return math.sin(t * 22.0) * 2.5, 0.0
        return 0.0, 0.0

    def _build_mascot(self, state, t, now, audio_level):
        frames_state = self._img_cache.frames_for(state)
        if not frames_state:
            return None
        n = len(frames_state)
        frame_idx = self._frame_idx_for(state, t, n)
        opacity   = self._opacity_for(state, t)
        self._last_frame_idx = frame_idx
        self._last_opacity   = opacity

        img = self._img_cache.get_pil(frame_idx, opacity, state)
        if img is None:
            return None

        if self._prev_state is not None:
            elapsed = now - self._transition_start
            if elapsed < _TRANS_SECS:
                a = elapsed / _TRANS_SECS
                prev = self._img_cache.get_pil(self._prev_frame_idx, self._prev_opacity, self._prev_state)
                if prev is not None and prev.size == img.size:
                    img = Image.blend(prev, img, a)
            else:
                self._prev_state = None

        if state == "listening" and audio_level > 0.01:
            ns = max(1, int(_IMG_SZ * (1.0 + audio_level * _AUDIO_SCALE)))
            img = img.resize((ns, ns), Image.Resampling.LANCZOS)
        return img

    def _compute_frame(self):
        """Devuelve (PIL RGBA del overlay completo, w, h)."""
        now = time.time()
        with self._lock:
            state = self._state
            audio_level = self._audio_level
            if state in ("ok", "error") and now > self._expire:
                self._state = state = "idle"; self._expire = 0.0
            elif state not in ("ok", "error", "idle") and now > self._expire:
                self._state = state = "idle"; self._expire = 0.0

        if state != self._displayed_state:
            self._prev_state      = self._displayed_state
            self._prev_frame_idx  = self._last_frame_idx
            self._prev_opacity    = self._last_opacity
            self._transition_start = now
            self._displayed_state = state

        t = now
        text = _TEXTS.get(state, "") if state in ("error", "ok") else ""
        offx, offy = self._offset_for(state, t)
        w = _DOT_W + (len(text) * 9 + 24 if text else 0)
        h = _DOT_H

        frame = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        if text:
            d = ImageDraw.Draw(frame)
            d.rounded_rectangle([2, 2, w - 3, h - 3], radius=16, fill=_PILL_BG,
                                outline=_PILL_BORDER, width=1)
            try:
                d.text((_DOT_W + 2, h // 2), text, font=self._font, fill=_TEXT_COLOR, anchor="lm")
            except Exception:
                d.text((_DOT_W + 2, h // 2 - 7), text, font=self._font, fill=_TEXT_COLOR)

        mascot = self._build_mascot(state, t, now, audio_level)
        if mascot is not None:
            mw, mh = mascot.size
            cx = _DOT_W // 2 + offx
            cy = _DOT_H // 2 + offy
            frame.alpha_composite(mascot, (int(cx - mw / 2), int(cy - mh / 2)))
        return frame, w, h

    # ── Arranque ───────────────────────────────────────────────────────────────
    def _run(self):
        if not self._use_tk:
            try:
                self._run_win32()
                return
            except Exception:
                self._use_tk = True  # caer a tkinter
        self._run_tk()

    # ── Win32 (alpha real, sin tkinter) ─────────────────────────────────────────
    def _run_win32(self):
        hinst = _kernel32.GetModuleHandleW(None)
        self._wndproc_ref = _WNDPROC(self._wndproc)
        cls = _WNDCLASS()
        cls.lpfnWndProc   = self._wndproc_ref
        cls.hInstance     = hinst
        cls.lpszClassName = "ByaroxOverlayWnd"
        cls.hCursor       = 0
        _user32.RegisterClassW(ctypes.byref(cls))

        ex_style = WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW
        self._hwnd = _user32.CreateWindowExW(
            ex_style, "ByaroxOverlayWnd", "Byarox", WS_POPUP,
            int(self._wx), int(self._wy), _DOT_W, _DOT_H,
            None, None, hinst, None)
        if not self._hwnd:
            raise RuntimeError("CreateWindowExW falló")

        _user32.ShowWindow(self._hwnd, SW_SHOWNOACTIVATE)
        self._render_win32()  # primer frame
        _user32.SetTimer(self._hwnd, 1, 30, None)

        msg = wintypes.MSG()
        while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            _user32.TranslateMessage(ctypes.byref(msg))
            _user32.DispatchMessageW(ctypes.byref(msg))

    def _render_win32(self):
        try:
            frame, w, h = self._compute_frame()
            if self._hidden:
                return
            self._win_w, self._win_h = w, h
            _push_layered(self._hwnd, frame, self._wx, self._wy)
        except Exception:
            pass

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == WM_TIMER:
            self._render_win32()
            return 0
        if msg == WM_LBUTTONDOWN:
            pt = _POINT(); _user32.GetCursorPos(ctypes.byref(pt))
            self._dragging = True
            self._drag_dx = pt.x - int(self._wx)
            self._drag_dy = pt.y - int(self._wy)
            _user32.SetCapture(hwnd)
            return 0
        if msg == WM_MOUSEMOVE and (wparam & MK_LBUTTON) and self._dragging:
            pt = _POINT(); _user32.GetCursorPos(ctypes.byref(pt))
            self._wx = pt.x - self._drag_dx
            self._wy = pt.y - self._drag_dy
            self._render_win32()
            return 0
        if msg == WM_LBUTTONUP:
            self._dragging = False
            _user32.ReleaseCapture()
            self._save_pos(self._wx, self._wy)
            return 0
        if msg == WM_RBUTTONUP:
            self._show_menu_win32(hwnd)
            return 0
        if msg == WM_APP_HIDE:
            _user32.ShowWindow(hwnd, SW_HIDE)
            return 0
        if msg == WM_APP_SHOW:
            _user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
            return 0
        if msg == WM_DESTROY:
            _user32.PostQuitMessage(0)
            return 0
        return _user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _show_menu_win32(self, hwnd):
        try:
            menu = _user32.CreatePopupMenu()
            _user32.AppendMenuW(menu, MF_STRING, 1, "Ocultar")
            _user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
            _user32.AppendMenuW(menu, MF_STRING, 2, "Cerrar Byarox")
            pt = _POINT(); _user32.GetCursorPos(ctypes.byref(pt))
            _user32.SetForegroundWindow(hwnd)
            cmd = _user32.TrackPopupMenu(menu, TPM_RETURNCMD | TPM_RIGHTBUTTON,
                                         pt.x, pt.y, 0, hwnd, None)
            _user32.DestroyMenu(menu)
            if cmd == 1:
                self.hide()
            elif cmd == 2:
                self._save_pos(self._wx, self._wy)
                os._exit(0)
        except Exception:
            pass

    # ── Fallback tkinter (color-key) ─────────────────────────────────────────────
    def _run_tk(self):
        import tkinter as tk
        root = tk.Tk(); self._root = root
        root.overrideredirect(True)
        root.wm_attributes("-topmost", True)
        root.configure(bg=_TRANS_BG)
        try: root.wm_attributes("-transparentcolor", _TRANS_BG)
        except tk.TclError: pass
        self._canvas = tk.Canvas(root, bg=_TRANS_BG, bd=0, highlightthickness=0)
        self._canvas.pack(fill="both", expand=True)
        for w in (root, self._canvas):
            w.bind("<ButtonPress-1>",   self._tk_drag_start)
            w.bind("<B1-Motion>",       self._tk_drag_move)
            w.bind("<ButtonRelease-1>", lambda e: self._save_pos(self._wx, self._wy))
        root.geometry(f"{_DOT_W}x{_DOT_H}+{int(self._wx)}+{int(self._wy)}")
        self._tk_tick()
        root.mainloop()

    def _tk_tick(self):
        if self._root:
            try:
                frame, w, h = self._compute_frame()
                self._canvas.delete("all")
                self._photo_ref = ImageTk.PhotoImage(frame)
                self._canvas.create_image(0, 0, image=self._photo_ref, anchor="nw")
                self._root.geometry(f"{w}x{h}+{int(self._wx)}+{int(self._wy)}")
            except Exception:
                pass
            self._root.after(30, self._tk_tick)

    def _tk_drag_start(self, e):
        self._drag_dx = e.x_root - int(self._wx)
        self._drag_dy = e.y_root - int(self._wy)

    def _tk_drag_move(self, e):
        self._wx = e.x_root - self._drag_dx
        self._wy = e.y_root - self._drag_dy


if __name__ == "__main__":
    import time as _t
    ov = StatusOverlay(); ov.start()
    _t.sleep(0.6)
    print("Ciclando estados (Ctrl+C para salir):")
    cycle = ["idle", "listening", "processing", "talking", "sending", "error"]
    i = 0
    try:
        while True:
            st = cycle[i % len(cycle)]
            print(f"  -> {st}")
            ov.set_state(st)
            t0 = _t.time()
            while _t.time() - t0 < 4:
                if st == "listening":
                    ov.set_audio_level(0.5 + 0.5 * math.sin((_t.time() - t0) * 6.0))
                _t.sleep(0.05)
            i += 1
    except KeyboardInterrupt:
        print("Saliendo.")
