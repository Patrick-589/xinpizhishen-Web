@echo off
setlocal

set "START_SCRIPT=%~dp0web\launch-app.ps1"
set "INSTALL_SCRIPT=%~dp0web\install-windows.ps1"

if not exist "%START_SCRIPT%" (
  echo Cannot find the application launcher:
  echo %START_SCRIPT%
  echo.
  echo Keep this launcher in the project root folder and try again.
  pause
  exit /b 1
)

if /I "%~1"=="--check" (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%START_SCRIPT%" -CheckOnly
  exit /b %ERRORLEVEL%
)

if not exist "%~dp0web\runtime\venv\Scripts\python.exe" if not exist "%~dp0web\runtime\gpu-venv\Scripts\python.exe" (
  if not exist "%INSTALL_SCRIPT%" (
    echo Cannot find the application installer:
    echo %INSTALL_SCRIPT%
    pause
    exit /b 1
  )
  echo First use: installing the independent runtime. Keep this window open.
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%INSTALL_SCRIPT%" -NoLaunch
  if errorlevel 1 (
    echo Installation failed. Check the message above and try again.
    pause
    exit /b 1
  )
)

powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "%START_SCRIPT%"
if errorlevel 1 (
  echo Failed to start the local application.
  pause
  exit /b 1
)

endlocal
