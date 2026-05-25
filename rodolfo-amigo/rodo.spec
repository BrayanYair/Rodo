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
    datas=sr_datas,
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
        # Módulos locales (por si PyInstaller no los detecta)
        "overlay",
        "config_manager",
        "setup_gui",
        "updater",
        "version",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Excluir módulos pesados que no usamos
    excludes=[
        "numpy", "scipy", "matplotlib", "PIL", "Pillow",
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
    name="Rodo",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,               # Compresión UPX (reduce tamaño ~30%)
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # SIN ventana CMD — solo GUI
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon="rodo.ico",      # Descomentar cuando tengas el icono
)
