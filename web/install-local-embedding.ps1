param(
  [switch]$SkipModelDownload,
  [switch]$SkipRebuild
)

$ErrorActionPreference = 'Stop'
$projectPython = Join-Path $PSScriptRoot 'runtime\venv\Scripts\python.exe'
$gpuPython = Join-Path $PSScriptRoot 'runtime\gpu-venv\Scripts\python.exe'
$pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
$python = if (Test-Path -LiteralPath $projectPython) {
  $projectPython
} elseif (Test-Path -LiteralPath $gpuPython) {
  $gpuPython
} elseif ($pythonCommand -and $pythonCommand.Source -notlike '*\WindowsApps\*') {
  $pythonCommand.Source
} else {
  throw 'Python 未找到，请先运行安装信披智审_Windows.cmd。'
}

& $python -m pip install -r (Join-Path $PSScriptRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Python dependencies installation failed.' }

if (-not $SkipModelDownload) {
  & $python (Join-Path $PSScriptRoot 'scripts\download_local_embedding.py')
  if ($LASTEXITCODE -ne 0) { throw 'Local embedding model download failed.' }
}

if (-not $SkipRebuild) {
  & $python (Join-Path $PSScriptRoot 'scripts\rebuild_embeddings.py')
  if ($LASTEXITCODE -ne 0) { throw 'FAISS rebuild failed.' }
}

& $python (Join-Path $PSScriptRoot 'scripts\download_local_embedding.py') --offline-check
if ($LASTEXITCODE -ne 0) { throw 'Offline model check failed.' }
Write-Output 'Local Embedding and FAISS are ready for offline use.'
