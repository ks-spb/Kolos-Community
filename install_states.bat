@echo off
cd /d "%~dp0"
py -3 -m pip install -r requirements-states.txt
if errorlevel 1 (echo Installation failed. & pause & exit /b 1)
py -3 -m kolos_states.cli --selftest
pause
