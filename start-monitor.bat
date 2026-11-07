@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Broen - monitor
start "" http://localhost:8765
python monitor.py broen.json
pause
