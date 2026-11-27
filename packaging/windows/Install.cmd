@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install.ps1" %*
set "KOLOS_EXIT=%errorlevel%"
if "%~1"=="" pause
exit /b %KOLOS_EXIT%
