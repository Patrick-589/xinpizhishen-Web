@echo off
setlocal

set "INSTALL_SCRIPT=%~dp0web\install-windows.ps1"
if not exist "%INSTALL_SCRIPT%" (
  echo Cannot find the installer:
  echo %INSTALL_SCRIPT%
  pause
  exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%INSTALL_SCRIPT%"
if errorlevel 1 (
  echo Installation failed.
  pause
  exit /b 1
)

echo.
echo Installation completed. The application can now run independently on this computer.
pause
endlocal
