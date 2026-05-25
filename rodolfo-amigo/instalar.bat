@echo off
chcp 65001 >nul 2>&1
title Instalar Rodo

echo.
echo ╔══════════════════════════════════════════════════╗
echo ║            Instalando Rodo                       ║
echo ║        Solo necesitas hacer esto UNA VEZ         ║
echo ╚══════════════════════════════════════════════════╝
echo.

:: Verificar Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Python no esta instalado. Instalando automaticamente...
    echo.
    winget install --id Python.Python.3.11 --silent --accept-source-agreements --accept-package-agreements
    if %errorlevel% neq 0 (
        echo.
        echo No se pudo instalar Python automaticamente.
        echo Descargalo desde: https://www.python.org/downloads/
        echo IMPORTANTE: marca "Add Python to PATH" al instalar.
        echo.
        pause
        exit /b 1
    )
    echo.
    echo Python instalado. Cierra esta ventana y vuelve a abrir instalar.bat
    echo.
    pause
    exit /b 0
)

echo Instalando dependencias...
pip install SpeechRecognition requests PyAudio python-dotenv

if %errorlevel% neq 0 (
    echo.
    echo Si PyAudio fallo, prueba:
    echo   pip install pipwin
    echo   pipwin install pyaudio
    echo.
    pause
    exit /b 1
)

echo.
echo ════════════════════════════════════════════════
echo   Listo! Ahora abre Rodo.bat para empezar.
echo   La primera vez te pedira los datos del servidor.
echo ════════════════════════════════════════════════
echo.
pause
