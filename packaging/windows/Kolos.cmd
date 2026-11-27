@echo off
"%~dp0runtime\python.exe" -B -m kolos_states.task_runner %*
exit /b %errorlevel%
