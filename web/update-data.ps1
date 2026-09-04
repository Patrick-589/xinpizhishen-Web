$ErrorActionPreference = 'Stop'

$webDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$syncScript = Join-Path $webDirectory 'scripts\sync-all.mjs'
$announcementKnowledgeScript = Join-Path $webDirectory 'scripts\sync_company_announcement_knowledge.py'
$ruleKnowledgeScript = Join-Path $webDirectory 'scripts\sync_official_rule_knowledge.py'
$mofKnowledgeScript = Join-Path $webDirectory 'scripts\sync_mof_accounting_knowledge.py'
$nodeCommand = Get-Command node.exe -ErrorAction SilentlyContinue
$projectPython = Join-Path $webDirectory 'runtime\venv\Scripts\python.exe'
$gpuPython = Join-Path $webDirectory 'runtime\gpu-venv\Scripts\python.exe'
$pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
$nodeCandidates = @(
    (Join-Path $env:ProgramFiles 'nodejs\node.exe'),
    (Join-Path ${env:ProgramFiles(x86)} 'nodejs\node.exe'),
    (Join-Path $env:LOCALAPPDATA 'Programs\nodejs\node.exe')
)
$popplerCandidates = @(
    (Join-Path $env:ProgramFiles 'poppler\Library\bin\pdftoppm.exe'),
    (Join-Path ${env:ProgramFiles(x86)} 'poppler\Library\bin\pdftoppm.exe'),
    (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages')
)
$bundledPdftoppm = $popplerCandidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
if (-not $bundledPdftoppm) {
    $wingetRoot = Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages'
    if (Test-Path -LiteralPath $wingetRoot) {
        $foundPdftoppm = Get-ChildItem -LiteralPath $wingetRoot -Filter 'pdftoppm.exe' -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($foundPdftoppm) { $bundledPdftoppm = $foundPdftoppm.FullName }
    }
}

if ($nodeCommand -and $nodeCommand.Source -notlike '*\WindowsApps\*') {
    $nodePath = $nodeCommand.Source
} else {
    $bundledNode = $nodeCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $bundledNode) { throw 'Node.js was not found. Run 安装信披智审_Windows.cmd or install Node.js 20+.' }
    $nodePath = $bundledNode
}

if (Test-Path -LiteralPath $projectPython) {
    $pythonPath = $projectPython
} elseif (Test-Path -LiteralPath $gpuPython) {
    $pythonPath = $gpuPython
} elseif ($pythonCommand -and $pythonCommand.Source -notlike '*\WindowsApps\*') {
    $pythonPath = $pythonCommand.Source
} else {
    throw 'Python was not found. Run web\install-windows.ps1 or install Python 3.11/3.12.'
}

$useGpu = $false
if (Test-Path -LiteralPath $gpuPython) {
    & $gpuPython -c 'import torch; raise SystemExit(0 if torch.cuda.is_available() else 1)'
    if ($LASTEXITCODE -eq 0) {
        $pythonPath = $gpuPython
        $useGpu = $true
    }
}

$previousEmbeddingDevice = $env:LOCAL_EMBEDDING_DEVICE
$previousPdftoppmPath = $env:PDFTOPPM_PATH
$previousOcrMaxPages = $env:OCR_MAX_PAGES
$previousCsrcFullText = $env:CSRC_INCLUDE_FULL_TEXT
if ($useGpu) {
    $env:LOCAL_EMBEDDING_DEVICE = 'cuda'
}
if ([string]::IsNullOrWhiteSpace($env:PDFTOPPM_PATH) -and (Test-Path -LiteralPath $bundledPdftoppm)) {
    $env:PDFTOPPM_PATH = $bundledPdftoppm
}
$env:CSRC_INCLUDE_FULL_TEXT = '1'
if ([string]::IsNullOrWhiteSpace($env:OCR_MAX_PAGES)) {
    $env:OCR_MAX_PAGES = '500'
}

Push-Location (Split-Path -Parent $webDirectory)
try {
    $syncFailures = [System.Collections.Generic.List[string]]::new()
    & $nodePath $syncScript
    if ($LASTEXITCODE -ne 0) { $syncFailures.Add("Data index sync failed. Exit code: $LASTEXITCODE") }
    & $pythonPath $ruleKnowledgeScript --retry-failed
    if ($LASTEXITCODE -ne 0) { $syncFailures.Add("Official rule knowledge sync failed. Exit code: $LASTEXITCODE") }
    & $pythonPath $mofKnowledgeScript --retry-failed
    if ($LASTEXITCODE -ne 0) { $syncFailures.Add("MOF accounting knowledge sync failed. Exit code: $LASTEXITCODE") }
    & $pythonPath $announcementKnowledgeScript --retry-failed
    if ($LASTEXITCODE -ne 0) { $syncFailures.Add("Company announcement knowledge sync failed. Exit code: $LASTEXITCODE") }
    if ($syncFailures.Count -gt 0) {
        throw ($syncFailures -join [Environment]::NewLine)
    }
    Write-Host 'Official rule bodies, announcements, and local RAG vectors have been updated.' -ForegroundColor Green
} finally {
    Pop-Location
    $env:LOCAL_EMBEDDING_DEVICE = $previousEmbeddingDevice
    $env:PDFTOPPM_PATH = $previousPdftoppmPath
    $env:OCR_MAX_PAGES = $previousOcrMaxPages
    $env:CSRC_INCLUDE_FULL_TEXT = $previousCsrcFullText
}
