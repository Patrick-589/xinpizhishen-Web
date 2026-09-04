param(
  [switch]$ServerOnly,
  [switch]$CheckOnly
)

$ErrorActionPreference = 'Stop'
$webRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$startScript = Join-Path $webRoot 'start-windows.ps1'
$url = 'http://127.0.0.1:8767/index.html#tasks'

if (-not (Test-Path -LiteralPath $startScript)) {
  throw "Cannot find launcher: $startScript"
}

if ($CheckOnly) {
  & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $startScript -CheckOnly
  exit $LASTEXITCODE
}

& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $startScript -ServerOnly
if ($LASTEXITCODE -ne 0) { throw 'Local service failed to start.' }
if ($ServerOnly) { exit 0 }

$edgeCandidates = @(
  (Join-Path $env:ProgramFiles 'Microsoft\Edge\Application\msedge.exe'),
  (Join-Path ${env:ProgramFiles(x86)} 'Microsoft\Edge\Application\msedge.exe'),
  (Join-Path $env:LOCALAPPDATA 'Microsoft\Edge\Application\msedge.exe')
) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }

$edge = $edgeCandidates | Select-Object -First 1
if ($edge) {
  Start-Process -FilePath $edge -ArgumentList @('--new-window', $url, '--start-maximized')
} else {
  Start-Process $url
}
