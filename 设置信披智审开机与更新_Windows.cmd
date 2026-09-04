@echo off
setlocal

set "TASK_SCRIPT=%~dp0web\register-windows-tasks.ps1"
if not exist "%TASK_SCRIPT%" (
  echo Cannot find the task registration script:
  echo %TASK_SCRIPT%
  pause
  exit /b 1
)

echo This will register automatic startup after Windows login and a daily 09:00 update task.
echo If Task Scheduler is restricted, the script will use a current-user startup entry instead.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%TASK_SCRIPT%" -Install
if errorlevel 1 (
  echo Task registration failed.
  pause
  exit /b 1
)

echo.
echo For same-network phone or computer access, run this command as Administrator once:
echo powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%TASK_SCRIPT%" -InstallFirewall
pause
endlocal
