@echo off
chcp 65001 >nul 2>&1
title Rodolfo - Dev Local
cd /d "%~dp0"
python dev-local.py
pause
