@echo off
:: instalar.bat — Solo se usa si Python aun no esta instalado.
:: Con Python instalado, usa instalar.pyw (sin consola).

pythonw instalar.pyw 2>nul && exit /b

:: pythonw no encontrado → Python no instalado
echo.
echo  Necesitas instalar Python primero.
echo.
echo  1. Ve a: https://www.python.org/downloads/
echo  2. Descarga Python 3.11 o superior
echo  3. IMPORTANTE: marca la casilla "Add Python to PATH"
echo  4. Vuelve a abrir este archivo
echo.
pause
