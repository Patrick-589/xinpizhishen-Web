param(
  [switch]$SkipEmbeddingModel,
  [switch]$SkipInitialIndex,
  [switch]$NoLaunch
)

$ErrorActionPreference = 'Stop'
$webRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $webRoot
$venvPath = Join-Path $webRoot 'runtime\venv'
$venvPython = Join-Path $venvPath 'Scripts\python.exe'
$gpuVenvPython = Join-Path $webRoot 'runtime\gpu-venv\Scripts\python.exe'
$requirements = Join-Path $webRoot 'requirements.txt'
$productionRequirements = Join-Path $webRoot 'requirements-production.txt'
$downloadScript = Join-Path $webRoot 'scripts\download_local_embedding.py'
$rebuildScript = Join-Path $webRoot 'scripts\rebuild_embeddings.py'
$relocateScript = Join-Path $webRoot 'scripts\relocate_packaged_runtime.py'
$registerTasksScript = Join-Path $webRoot 'register-windows-tasks.ps1'
$distributionManifest = Join-Path $webRoot 'runtime\distribution-manifest.json'
$environmentPath = Join-Path $projectRoot '.env'
$credentialsPath = Join-Path $projectRoot '首次登录信息.txt'
$shortcutScript = Join-Path $webRoot 'scripts\create-desktop-shortcut.ps1'

function Find-SystemPython {
  $candidates = @(
    (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'),
    (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\python.exe'),
    (Join-Path $env:ProgramFiles 'Python312\python.exe'),
    (Join-Path $env:ProgramFiles 'Python311\python.exe')
  )
  foreach ($candidate in $candidates) {
    if (Test-Path -LiteralPath $candidate) { return $candidate }
  }
  $command = Get-Command python.exe -ErrorAction SilentlyContinue
  if ($command -and $command.Source -notlike '*\WindowsApps\*') { return $command.Source }
  return $null
}

function Install-SystemPython {
  $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
  if (-not $winget) {
    throw '未找到 Python 3.11/3.12，且本机没有 winget。请先安装 64 位 Python 3.12 后重新运行。'
  }
  Write-Host '未找到可用 Python，正在通过 winget 安装 Python 3.12（当前用户）...'
  & $winget.Source install --id Python.Python.3.12 --exact --scope user `
    --accept-package-agreements --accept-source-agreements --silent | Out-Host
  if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 自动安装失败。' }
  $python = Find-SystemPython
  if (-not $python) { throw 'Python 已安装但当前进程尚未找到，请重新打开安装程序。' }
  return $python
}

function Find-SystemNode {
  $candidates = @(
    (Join-Path $env:ProgramFiles 'nodejs\node.exe'),
    (Join-Path ${env:ProgramFiles(x86)} 'nodejs\node.exe'),
    (Join-Path $env:LOCALAPPDATA 'Programs\nodejs\node.exe')
  )
  foreach ($candidate in $candidates) {
    if (Test-Path -LiteralPath $candidate) { return $candidate }
  }
  $command = Get-Command node.exe -ErrorAction SilentlyContinue
  if ($command -and $command.Source -notlike '*\WindowsApps\*') { return $command.Source }
  return $null
}

function Install-SystemNode {
  $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
  if (-not $winget) { throw '未找到 Node.js 20+，且本机没有 winget。请先安装 Node.js LTS 后重新运行。' }
  Write-Host '未找到 Node.js，正在通过 winget 安装 Node.js LTS（当前用户）...'
  & $winget.Source install --id OpenJS.NodeJS.LTS --exact --scope user `
    --accept-package-agreements --accept-source-agreements --silent | Out-Host
  if ($LASTEXITCODE -ne 0) { throw 'Node.js LTS 自动安装失败。' }
  $node = Find-SystemNode
  if (-not $node) { throw 'Node.js 已安装但当前进程尚未找到，请重新打开安装程序。' }
  return $node
}

function Find-PdfToPpm {
  $command = Get-Command pdftoppm.exe -ErrorAction SilentlyContinue
  if ($command) { return $command.Source }
  $roots = @(
    (Join-Path $env:ProgramFiles 'poppler'),
    (Join-Path ${env:ProgramFiles(x86)} 'poppler'),
    (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages')
  ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
  foreach ($root in $roots) {
    $found = Get-ChildItem -LiteralPath $root -Filter 'pdftoppm.exe' -File -Recurse -ErrorAction SilentlyContinue |
      Select-Object -First 1
    if ($found) { return $found.FullName }
  }
  return $null
}

function Install-Poppler {
  $existing = Find-PdfToPpm
  if ($existing) { return $existing }
  $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
  if (-not $winget) {
    Write-Warning '未找到 Poppler，扫描 PDF OCR 需要手动安装 Poppler；普通 PDF/Word/Excel 不受影响。'
    return $null
  }
  Write-Host '未找到 PDF 渲染组件，正在通过 winget 安装 Poppler...'
  & $winget.Source install --id oschwartz10612.Poppler --exact --scope user `
    --accept-package-agreements --accept-source-agreements --silent | Out-Host
  if ($LASTEXITCODE -ne 0) {
    Write-Warning 'Poppler 自动安装失败；普通文档仍可使用，扫描 PDF OCR 需要单独安装。'
    return $null
  }
  $installed = Find-PdfToPpm
  if (-not $installed) {
    Write-Warning 'Poppler 已安装但当前进程未找到 pdftoppm.exe；重新打开安装程序或重启后会自动识别。'
  }
  return $installed
}

function Initialize-DistributionEnvironment {
  if (-not (Test-Path -LiteralPath $distributionManifest) -or (Test-Path -LiteralPath $environmentPath)) {
    return
  }
  $secretBytes = New-Object byte[] 32
  [System.Security.Cryptography.RandomNumberGenerator]::Fill($secretBytes)
  $secret = [Convert]::ToHexString($secretBytes).ToLowerInvariant()
  $passwordBytes = New-Object byte[] 8
  [System.Security.Cryptography.RandomNumberGenerator]::Fill($passwordBytes)
  $password = 'Admin-' + [Convert]::ToHexString($passwordBytes) + '!'
  @(
    'APP_ENV=development',
    'AI_MODE=local_rag',
    "APP_SECRET=$secret",
    'BOOTSTRAP_ADMIN_USERNAME=admin',
    "BOOTSTRAP_ADMIN_PASSWORD=$password",
    'ALLOW_REGISTRATION=true',
    'LOCAL_EMBEDDING_PROVIDER=bge_m3',
    'LOCAL_EMBEDDING_MODEL=BAAI/bge-m3',
    'LOCAL_EMBEDDING_ALLOW_DOWNLOAD=false',
    'LOCAL_EMBEDDING_DEVICE=cpu',
    'VECTOR_BACKEND=faiss',
    'RETRIEVAL_MODE=semantic'
  ) | Set-Content -LiteralPath $environmentPath -Encoding UTF8
  @(
    '信披智审首次登录信息',
    '',
    '网址：http://127.0.0.1:8767/index.html#tasks',
    '管理员账号：admin',
    "管理员初始密码：$password",
    '',
    '首次登录后请在账号设置中修改密码。本文件随后可以删除。'
  ) | Set-Content -LiteralPath $credentialsPath -Encoding UTF8
  Write-Output "已生成独立管理员账号信息：$credentialsPath"
}

if (Test-Path -LiteralPath $venvPython) {
  $runtimePython = $venvPython
  Write-Output "复用项目独立 Python 环境：$venvPath"
} elseif (Test-Path -LiteralPath $gpuVenvPython) {
  $runtimePython = $gpuVenvPython
  Write-Output '复用项目独立 GPU Python 环境：web\runtime\gpu-venv'
} else {
  $systemPython = Find-SystemPython
  if (-not $systemPython) { $systemPython = Install-SystemPython }
  Write-Output "创建项目独立 Python 环境：$venvPath"
  & $systemPython -m venv $venvPath
  if ($LASTEXITCODE -ne 0) { throw '创建 Python 虚拟环境失败。' }
  $runtimePython = $venvPython
}

Write-Output '安装项目依赖（首次需要联网，后续由项目环境独立运行）...'
& $runtimePython -m pip install --upgrade pip
& $runtimePython -m pip install -r $requirements
if ($LASTEXITCODE -ne 0) { throw '项目依赖安装失败。' }
if (Test-Path -LiteralPath $productionRequirements) {
  & $runtimePython -m pip install -r $productionRequirements
  if ($LASTEXITCODE -ne 0) { throw '生产扩展依赖安装失败。' }
}

Initialize-DistributionEnvironment
if (Test-Path -LiteralPath $distributionManifest) {
  if (-not (Test-Path -LiteralPath $relocateScript)) { throw '安装包缺少运行路径初始化脚本。' }
  & $runtimePython $relocateScript
  if ($LASTEXITCODE -ne 0) { throw '共享知识库路径初始化失败。' }
}

try {
  $nodePath = Find-SystemNode
  if (-not $nodePath) { $nodePath = Install-SystemNode }
  Write-Output "Node.js：$nodePath"
} catch {
  $nodePath = $null
  Write-Warning "Node.js 未安装：$($_.Exception.Message)。本地审查不受影响；联网后重新运行本安装程序即可启用每日官方资料自动更新。"
}
$pdfToPpm = Install-Poppler
if ($pdfToPpm) {
  $existingEnv = if (Test-Path -LiteralPath $environmentPath) { Get-Content -LiteralPath $environmentPath -Raw } else { '' }
  if ($existingEnv -notmatch '(?m)^PDFTOPPM_PATH=') {
    Add-Content -LiteralPath $environmentPath -Value "PDFTOPPM_PATH=$pdfToPpm" -Encoding UTF8
  }
}

if (-not $SkipEmbeddingModel) {
  Write-Output '下载或校验本地 Embedding 模型...'
  $bundledModel = Join-Path $webRoot 'runtime\models\bge-m3\pytorch_model.bin'
  if (Test-Path -LiteralPath $bundledModel) {
    & $runtimePython $downloadScript --offline-check
  } else {
    & $runtimePython $downloadScript
  }
  if ($LASTEXITCODE -ne 0) { throw '本地 Embedding 模型安装失败。' }
}

if (-not $SkipInitialIndex) {
  Push-Location $projectRoot
  try {
    & $runtimePython $rebuildScript --missing-only
    if ($LASTEXITCODE -ne 0) { throw '初始 RAG 向量索引建立失败。' }
  } finally {
    Pop-Location
  }
}

if (Test-Path -LiteralPath $registerTasksScript) {
  Write-Output '设置 Windows 登录后自动启动服务和每日资料库更新...'
  & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $registerTasksScript -Install
  if ($LASTEXITCODE -ne 0) {
    Write-Warning '自动启动注册失败，但不影响当前使用。请稍后以管理员身份运行“设置信披智审开机与更新_Windows.cmd”。'
  }
}

if (Test-Path -LiteralPath $shortcutScript) {
  & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $shortcutScript
  if ($LASTEXITCODE -ne 0) { Write-Warning '桌面快捷方式创建失败，可直接双击“打开信披智审_Windows.cmd”。' }
}

Write-Output '项目独立运行环境已准备完成。以后登录 Windows 后服务会自动启动，可直接访问 http://127.0.0.1:8767/index.html#tasks。'

if ((Test-Path -LiteralPath $distributionManifest) -and -not $NoLaunch) {
  & (Join-Path $webRoot 'launch-app.ps1')
}
