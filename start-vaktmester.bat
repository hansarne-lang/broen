@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Broen - vaktmester
:loop
python vaktmester.py broen.json
echo Vaktmesteren stoppet - starter igjen om 10 sekunder (Ctrl+C for aa avslutte)
timeout /t 10 >nul
goto loop
