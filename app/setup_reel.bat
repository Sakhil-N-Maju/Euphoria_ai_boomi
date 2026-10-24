@echo off
rem Optional: the website Setup panel (http://127.0.0.1:8000/site) does the same. Safe to run again.
setlocal
cd /d "%~dp0"
set "ROOT=%~dp0.."
set "PATH=%ROOT%\tools\ffmpeg\bin;%ROOT%\tools\node;%PATH%"
echo Installing the reel render tools, fonts and the cut-out model (one time)...
"%ROOT%\tools\python\python.exe" reel_agent\creator-reel\scripts\setup_tools.py data\reel_tools
echo.
echo Done. Start run.bat and open http://127.0.0.1:8000/site
pause
