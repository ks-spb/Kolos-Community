@echo off
setlocal
pushd "%~dp0web" || goto error

where node.exe >nul 2>&1 || (
  echo Node.js 20 or newer is required.
  goto error
)
where npm.cmd >nul 2>&1 || (
  echo npm.cmd was not found.
  goto error
)

if not exist "node_modules\typescript\bin\tsc" (
  echo Preparing Kolos Lab for the first launch...
  call npm.cmd ci
  if errorlevel 1 goto error
)

node signal\dev.mjs --open
if errorlevel 1 goto error
popd
exit /b 0

:error
echo Could not start Kolos Lab.
pause
exit /b 1
