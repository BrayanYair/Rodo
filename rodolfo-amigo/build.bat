@echo off
chcp 65001 >nul 2>&1
title Construyendo Byarox.exe
cd /d "%~dp0"

echo.
echo ════════════════════════════════════════════
echo   Construyendo Byarox.exe con PyInstaller
echo ════════════════════════════════════════════
echo.

:: Verificar PyInstaller
python -m PyInstaller --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Instalando PyInstaller...
    pip install pyinstaller --quiet
)

:: Verificar dependencias
echo Verificando dependencias...
pip install SpeechRecognition requests PyAudio python-dotenv --quiet

:: Limpiar builds anteriores
if exist "build" rmdir /s /q "build"
if exist "dist\Byarox.exe" del /q "dist\Byarox.exe"

:: Construir
echo.
echo Compilando... (esto tarda 1-3 minutos, es normal)
echo.
python -m PyInstaller rodo.spec --clean --noconfirm

echo.
if exist "dist\Byarox.exe" (
    for %%A in ("dist\Byarox.exe") do (
        set size=%%~zA
    )
    echo ════════════════════════════════════════════
    echo   Byarox.exe generado en: dist\Byarox.exe
    echo   Comparte ese archivo con tus amigos.
    echo ════════════════════════════════════════════
    explorer dist
) else (
    echo ERROR: No se genero Byarox.exe
    echo Revisa los mensajes de arriba para ver que fallo.
)

echo.
pause
