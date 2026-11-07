@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PY=python
where py >nul 2>nul && set PY=py -3
title Broen - monitor
start "" http://localhost:8765
%PY% monitor.py broen.json
pause
