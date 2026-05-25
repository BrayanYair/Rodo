@echo off
chcp 65001 >nul 2>&1
title Instalar Companion de Rodolfo

echo.
echo ╔══════════════════════════════════════════════════╗
echo ║   Instalando Companion de Rodolfo               ║
echo ║   Solo necesitas hacer esto UNA VEZ              ║
echo ╚══════════════════════════════════════════════════╝
echo.

:: Verificar Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ⚠️  Python no esta instalado en este sistema.
    echo Intentando instalar Python 3.11 automaticamente...
    echo.
    
    winget install --id Python.Python.3.11 --silent --accept-source-agreements --accept-package-agreements
    
    if %errorlevel% neq 0 (
        echo.
        echo ❌ No se pudo instalar Python automaticamente.
        echo Por favor, descargalo e instalalo manualmente desde:
        echo   https://www.python.org/downloads/
        echo.
        echo ⚠️  IMPORTANTE: Marca la casilla "Add Python to PATH" durante la instalacion.
        echo.
        pause
        exit /b 1
    )
    
    echo.
    echo ✅ Python se instalo con exito.
    echo ⚠️  IMPORTANTE: Cierra esta ventana y vuelve a abrir "instalar.bat"
    echo para que Windows reconozca la nueva instalacion.
    echo.
    pause
    exit /b 0
)

echo [1/2] Instalando dependencias de voz...
pip install SpeechRecognition requests python-dotenv PyAudio

if %errorlevel% neq 0 (
    echo.
    echo Si PyAudio fallo, intenta instalarlo con:
    echo   pip install pipwin
    echo   pipwin install pyaudio
    echo.
    echo O descarga el instalador manual desde:
    echo   https://www.lfd.uci.edu/~gohlke/pythonlibs/#pyaudio
    echo.
    pause
    exit /b 1
)

echo.
echo [2/2] ¡Todo instalado!
echo.
echo ─────────────────────────────────────────────
echo  Ahora ejecuta "iniciar.bat" para empezar.
echo  La primera vez te pedira:
echo    1. Tu nombre - aparece en Discord
echo    2. La URL del webhook - pidela a tu amigo
echo ─────────────────────────────────────────────
echo.
pause
