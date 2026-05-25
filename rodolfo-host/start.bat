@echo off
chcp 65001 >nul 2>&1
title Rodolfo Host
cd /d "%~dp0"
python controller.py
pause
