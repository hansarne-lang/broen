@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === Broen - installasjon ===
echo.

where python >nul 2>nul || (echo [MANGLER] Python 3.11+  -  installer fra https://www.python.org/downloads/ & set FEIL=1)
where git >nul 2>nul || (echo [MANGLER] Git  -  installer fra https://git-scm.com/download/win & set FEIL=1)
where npm >nul 2>nul || (echo [MANGLER] Node.js/npm  -  installer fra https://nodejs.org/ & set FEIL=1)
if defined FEIL (echo. & echo Installer det som mangler og kjor installer.bat paa nytt. & pause & exit /b 1)

where claude >nul 2>nul || (echo Installerer Claude Code... & call npm install -g @anthropic-ai/claude-code)
where codex >nul 2>nul || (echo Installerer Codex CLI... & call npm install -g @openai/codex)

if not exist broen.json (
  copy broen.eksempel.json broen.json >nul
  echo Laget broen.json fra eksempelet - aapner den for redigering.
  notepad broen.json
)

echo.
echo Neste steg:
echo  1. Kjor "claude" og "codex" en gang hver for aa logge inn.
echo  2. Kjor "claude" en gang i repomappen din og godta mappen.
echo  3. Kopier deltakere.json til nettverksdisken (rot-mappen i broen.json).
echo  4. Start start-vaktmester.bat (og start-monitor.bat paa en av PC-ene).
pause
