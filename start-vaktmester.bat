@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PY=python
where py >nul 2>nul && set PY=py -3
title Broen - vaktmester
:loop
%PY% vaktmester.py broen.json
echo Vaktmesteren stoppet - starter igjen om 10 sekunder (Ctrl+C for aa avslutte)
timeout /t 10 >nul
goto loop
