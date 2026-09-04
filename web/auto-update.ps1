param(
  [switch]$Once,
  [switch]$CheckOnly
)

$ErrorActionPreference = 'Stop'
$webRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $webRoot
$updateScript = Join-Path $webRoot 'update-data.ps1'
$rebuildScript = Join-Path $webRoot 'scripts\rebuild_embeddings.py'
$runtimeRoot = Join-Path $webRoot 'runtime'
$logDirectory = Join-Path $runtimeRoot 'logs'
$logPath = Join-Path $logDirectory 'auto-update.log'
$lockPath = Join-Path $runtimeRoot 'auto-update.lock'
$projectPython = Join-Path $webRoot 'runtime\venv\Scripts\python.exe'
$gpuPython = Join-Path $webRoot 'runtime\gpu-venv\Scripts\python.exe'

New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null

function Get-PythonPath {
  if (Test-Path -LiteralPath $projectPython) { return $projectPython }
  if (Test-Path -LiteralPath $gpuPython) { return $gpuPython }
  $command = Get-Command python.exe -ErrorAction SilentlyContinue
  if ($command -and $command.Source -notlike '*\WindowsApps\*') { return $command.Source }
  throw 'Python 未找到。请先运行 web\install-windows.ps1 安装项目运行环境。'
}

function Get-NodePath {
  $candidates = @(
    (Join-Path $env:ProgramFiles 'nodejs\node.exe'),
    (Join-Path ${env:ProgramFiles(x86)} 'nodejs\node.exe'),
    (Join-Path $env:LOCALAPPDATA 'Programs\nodejs\node.exe')
  )
  $command = Get-Command node.exe -ErrorAction SilentlyContinue
  if ($command -and $command.Source -notlike '*\WindowsApps\*') { return $command.Source }
  return $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}

function Write-UpdateLog([string]$Message) {
  $line = "[$([DateTime]::Now.ToString('yyyy-MM-dd HH:mm:ss zzz'))] $Message"
  Add-Content -LiteralPath $logPath -Value $line -Encoding UTF8
  Write-Output $line
}

$lock = $null
try {
  try {
    $lock = [System.IO.File]::Open(
      $lockPath,
      [System.IO.FileMode]::OpenOrCreate,
      [System.IO.FileAccess]::ReadWrite,
      [System.IO.FileShare]::None
    )
  } catch [System.IO.IOException] {
    Write-UpdateLog '已有同步任务正在运行，本次跳过。'
    exit 0
  }

  $python = Get-PythonPath
  if ($CheckOnly) {
    $node = Get-NodePath
    if (-not $node) { throw 'Node.js 未找到，自动更新需要 Node.js 20+。请重新运行安装程序。' }
    Write-UpdateLog "环境检查通过：Python=$python；Node=$node；更新脚本=$updateScript"
    exit 0
  }
  Write-UpdateLog "开始同步：$projectRoot"
  Push-Location $projectRoot
  try {
    & $updateScript *>> $logPath
    if ($LASTEXITCODE -ne 0) {
      throw "官方数据或知识库同步失败，退出码：$LASTEXITCODE"
    }

    # Existing import scripts embed new/changed official documents. This pass
    # repairs any pending or interrupted document without re-embedding ready chunks.
    & $python $rebuildScript --missing-only *>> $logPath
    if ($LASTEXITCODE -ne 0) {
      throw "缺失向量补建失败，退出码：$LASTEXITCODE"
    }
  } finally {
    Pop-Location
  }
  Write-UpdateLog '同步完成：官方索引、正文知识库和本地 RAG 向量均已检查。'
} catch {
  Write-UpdateLog "同步失败：$($_.Exception.Message)"
  exit 1
} finally {
  if ($lock) { $lock.Dispose() }
}
