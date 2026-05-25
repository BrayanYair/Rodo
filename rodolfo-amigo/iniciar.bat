@echo off
chcp 65001 >nul 2>&1
title Amigo de Rodolfo
cd /d "%~dp0"

echo.
echo   Iniciando companion de Rodolfo...
echo   (Si es tu primera vez, ejecuta "instalar.bat" primero)
echo.

python amigo.py

if %errorlevel% neq 0 (
    echo.
    echo Algo fallo. Verifica:
    echo   1. Que hayas ejecutado instalar.bat
    echo   2. Que tengas microfono conectado
    echo   3. Que el webhook de Discord sea correcto
    echo.
)
pause
