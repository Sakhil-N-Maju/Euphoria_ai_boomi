@echo off
rem Compare speech-to-text models on one clip:  compare_stt.bat "C:\videos\clip.mp4" --lang ml
setlocal
cd /d "%~dp0"
set "ROOT=%~dp0.."
set "PATH=%ROOT%\tools\ffmpeg\bin;%PATH%"
set HF_HUB_OFFLINE=1
set PYTHONUTF8=1
"%ROOT%\tools\python\python.exe" compare_stt.py %*
pause
