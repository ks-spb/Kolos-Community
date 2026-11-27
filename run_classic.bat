@echo off
setlocal
cd /d "%~dp0"
set GLAZ_UI=classic
py -3 "%~dp0Glaz\main.py"
if errorlevel 1 pause
endlocal
