@echo off
rem Command-line editing:  edit.bat "C:\path\to\video.mp4" --lang ml
setlocal
cd /d "%~dp0"
set "ROOT=%~dp0.."
set "PATH=%ROOT%\tools\ffmpeg\bin;%PATH%"
set HF_HUB_OFFLINE=1
set PYTHONUTF8=1
"%ROOT%\tools\python\python.exe" cli.py %*
