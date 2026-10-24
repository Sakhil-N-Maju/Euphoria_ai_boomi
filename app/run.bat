@echo off
rem Starts the editor with the portable Python, ffmpeg and model in this folder's parent.
setlocal
cd /d "%~dp0"
set "ROOT=%~dp0.."
set "PATH=%ROOT%\tools\ffmpeg\bin;%PATH%"
set HF_HUB_OFFLINE=1
set PYTHONUTF8=1
echo Starting Euphoria Editor at http://127.0.0.1:8000  (close this window to stop)
"%ROOT%\tools\python\python.exe" -m editor.server
pause
