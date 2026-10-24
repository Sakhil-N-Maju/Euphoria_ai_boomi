@echo off
rem Downloads the speech-to-text models listed in config.yaml (Malayalam model is about 1.5 GB). Run once.
setlocal
cd /d "%~dp0"
set "ROOT=%~dp0.."
set PYTHONUTF8=1
"%ROOT%\tools\python\python.exe" download_models.py %*
pause
