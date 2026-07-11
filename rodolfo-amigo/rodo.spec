# -*- mode: python ; coding: utf-8 -*-
#
# rodo.spec — Configuración de PyInstaller para Rodo.exe
#
# Para construir:   build.bat
# Salida:           dist\Rodo.exe   (~60-80 MB, sin dependencias externas)
#
# El usuario final SOLO necesita Rodo.exe — sin Python, sin instaladores.

from PyInstaller.utils.hooks import collect_data_files, collect_all

block_cipher = None

# ─── Recopilar archivos de datos de speech_recognition ───────────────────────
# SpeechRecognition incluye modelos y grammars que deben ir en el bundle.
sr_datas, sr_binaries, sr_hidden = collect_all("speech_recognition")

# ─── Análisis de importaciones ────────────────────────────────────────────────
a = Analysis(
    ["amigo.py"],
    pathex=["."],
    binaries=sr_binaries,
    datas=sr_datas + [
        ("rodo_logo.ico", "."),
        ("nircmd.exe", "."),
        # Clasificador de wake word "oye rodo"
        ("modules/wakeword/rodo_verifier.pkl", "modules/wakeword"),
        # Modelo VAD de Silero (ONNX)
        ("modules/vad/silero_vad.onnx", "modules/vad"),
        # __init__.py de paquetes (necesario para imports en modo frozen)
        ("modules/__init__.py", "modules"),
        ("modules/wakeword/__init__.py", "modules/wakeword"),
        ("modules/vad/__init__.py", "modules/vad"),
        ("modules/audio/__init__.py", "modules/audio"),
        ("modules/stt/__init__.py", "modules/stt"),
        ("modules/ducking/__init__.py", "modules/ducking"),
        ("modules/metrics/__init__.py", "modules/metrics"),
        ("modules/parser/__init__.py", "modules/parser"),
    ],
    hiddenimports=sr_hidden + [
        # Audio
        "pyaudio",
        "speech_recognition",
        # UI
        "tkinter",
        "tkinter.ttk",
        "tkinter.messagebox",
        # Config
        "dotenv",
        "json",
        "pathlib",
        # Red
        "requests",
        "urllib3",
        "certifi",
        "charset_normalizer",
        "idna",
        # Sistema
        "unicodedata",
        "threading",
        "socket",
        "subprocess",
        # Bandeja del sistema
        "pystray",
        "pystray._win32",
        "PIL",
        "PIL.Image",
        "PIL.IcoImagePlugin",
        "PIL.PngImagePlugin",
        # Discord RPC — detección automática de identidad
        "pypresence",
        # Módulos locales (por si PyInstaller no los detecta)
        "overlay",
        "config_manager",
        "setup_gui",
        "updater",
        "version",
        "tray",
        "command_parser",
        # Nuevos módulos (opcionales — fallan silenciosamente si no están)
        "modules.ducking.ducking_manager",
        "modules.wakeword.wakeword_engine",
        "modules.vad.vad_engine",
        "modules.audio.audio_loop",
        "modules.stt.stt_engine",
        "modules.metrics.voice_metrics",
        "pycaw",
        "comtypes",
        # STT fallback: faster-whisper (opcional — falla silenciosamente si no instalado)
        "faster_whisper",
        "numpy",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Excluir módulos pesados que no usamos en el flujo principal.
    # numpy y scipy se mantienen — los necesitan ducking/wakeword/vad.
    excludes=[
        "matplotlib",
        "pandas", "cv2", "torch", "tensorflow",
        "whisper", "openai",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="Byarox",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,               # Compresión UPX (reduce tamaño ~30%)
    upx_exclude=[],
    runtime_tmpdir="%LOCALAPPDATA%\\Rodo",
    console=False,          # SIN ventana CMD — solo GUI
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="rodo_logo.ico",
)
