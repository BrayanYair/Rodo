@echo off
chcp 65001 >nul 2>&1
title Rodo
cd /d "%~dp0"

python amigo.py

if %errorlevel% neq 0 (
    echo.
    echo Algo salio mal. Verifica:
    echo   1. Que hayas ejecutado instalar.bat al menos una vez
    echo   2. Que tengas microfono conectado
    echo   3. Que el servidor de Rodo este encendido
    echo.
)
pause
