$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$launcher = Join-Path $projectRoot 'web\launch-app.ps1'
$desktop = [Environment]::GetFolderPath('Desktop')
$shortcutName = ([char]0x4fe1) + ([char]0x62ab) + ([char]0x667a) + ([char]0x5ba1) + '.lnk'
$shortcutPath = Join-Path $desktop $shortcutName
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe')
$shortcut.Arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$launcher`""
$shortcut.WorkingDirectory = $projectRoot
$shortcut.Description = 'Xinpizhishen Compliance Review Platform'
$iconPath = Join-Path -Path $env:SystemRoot -ChildPath 'System32\shell32.dll'
$shortcut.IconLocation = "$iconPath,167"
$shortcut.Save()
Write-Output "Desktop shortcut created: $shortcutPath"
