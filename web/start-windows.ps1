param(
  [switch]$CheckOnly,
  [switch]$ServerOnly
)

$ErrorActionPreference = 'Stop'
$serverScript = Join-Path $PSScriptRoot 'server.py'
$projectPython = Join-Path $PSScriptRoot 'runtime\venv\Scripts\python.exe'
$gpuPython = Join-Path $PSScriptRoot 'runtime\gpu-venv\Scripts\python.exe'
$expectedServiceId = 'xinpizhishen-platform'
$port = 8767

if (-not (Test-Path -LiteralPath $serverScript)) {
  throw "Cannot find local server: $serverScript"
}

  if (Test-Path -LiteralPath $projectPython) {
    $python = $projectPython
  } elseif (Test-Path -LiteralPath $gpuPython) {
    $python = $gpuPython
  } else {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCommand -or $pythonCommand.Source -like '*\WindowsApps\*') {
      throw 'Python is required. Run 安装信披智审_Windows.cmd once to install the project runtime.'
    }
  $python = $pythonCommand.Source
}

function Test-ExpectedServer([int]$CandidatePort) {
  try {
    $candidateHealth = Invoke-RestMethod -Uri "http://127.0.0.1:$CandidatePort/api/health" -TimeoutSec 5
    return ([string]$candidateHealth.status -eq 'ok' -and
      [string]$candidateHealth.serviceId -eq $expectedServiceId -and
      [bool]$candidateHealth.lanAccess)
  } catch {
    return $false
  }
}

function Get-DeviceAddresses {
  $addresses = [System.Net.Dns]::GetHostAddresses([System.Net.Dns]::GetHostName()) |
    Where-Object {
      $_.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork -and
      -not [System.Net.IPAddress]::IsLoopback($_) -and
      -not $_.IPAddressToString.StartsWith('169.254.')
    }
  return @($addresses | ForEach-Object { $_.IPAddressToString } | Sort-Object -Unique)
}

function Test-TailscaleAddress([string]$Address) {
  $parts = $Address.Split('.')
  if ($parts.Count -ne 4) { return $false }
  $first = [int]$parts[0]
  $second = [int]$parts[1]
  return ($first -eq 100 -and $second -ge 64 -and $second -le 127)
}

function Test-PortAvailable([int]$CandidatePort) {
  $client = [System.Net.Sockets.TcpClient]::new()
  try {
    $client.Connect('127.0.0.1', $CandidatePort)
    return $false
  } catch {
    return $true
  } finally {
    $client.Dispose()
  }
}

if ($CheckOnly) {
  Write-Output "SERVER_SCRIPT: $serverScript"
  Write-Output "PYTHON: $python"
  Write-Output "PORT: $port"
  Write-Output "READY: $(Test-ExpectedServer $port)"
  exit 0
}

$healthUrl = "http://127.0.0.1:$port/api/health"
$appUrl = "http://127.0.0.1:$port/index.html#tasks"
$deviceAddresses = Get-DeviceAddresses
$tailscaleAddress = $deviceAddresses | Where-Object { Test-TailscaleAddress $_ } | Select-Object -First 1
$lanAddress = $deviceAddresses | Where-Object { -not (Test-TailscaleAddress $_) } | Select-Object -First 1
$deviceName = [System.Net.Dns]::GetHostName()
$mobileUrl = if ($lanAddress) { "http://${lanAddress}:$port/index.html#tasks" } else { '' }
$deviceUrl = if ($deviceName) { "http://${deviceName}:$port/index.html#tasks" } else { '' }
$tailscaleUrl = if ($tailscaleAddress) { "http://${tailscaleAddress}:$port/index.html#tasks" } else { '' }
$serverReady = Test-ExpectedServer $port

if (-not $serverReady) {
  if (-not (Test-PortAvailable $port)) {
    throw "Port $port is already occupied by another application."
  }
  $logDirectory = Join-Path $PSScriptRoot 'runtime\logs'
  New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
  Start-Process -FilePath $python -ArgumentList @($serverScript, '--port', $port, '--bind', '0.0.0.0') `
    -WorkingDirectory $PSScriptRoot -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $logDirectory 'server-8767.out.log') `
    -RedirectStandardError (Join-Path $logDirectory 'server-8767.err.log')
  # Loading the local FAISS metadata and the company knowledge database can take
  # longer on the first start, especially on a Windows machine with many chunks.
  # Keep the launcher open long enough to avoid reporting a false startup failure.
  for ($attempt = 0; $attempt -lt 120; $attempt++) {
    Start-Sleep -Milliseconds 500
    try {
      $health = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 5
      if ($health.status -eq 'ok' -and $health.serviceId -eq $expectedServiceId) {
        $serverReady = $true
        break
      }
    } catch {
      $serverReady = $false
    }
  }
}

if (-not $serverReady) {
  throw "Local server did not start on port $port."
}

$accessFile = Join-Path $PSScriptRoot 'runtime\access-url.txt'
$accessLines = @("Local URL: $appUrl")
if ($deviceUrl) {
  $accessLines += "Device name URL: $deviceUrl"
}
if ($mobileUrl) {
  $accessLines += "LAN URL: $mobileUrl"
}
if ($tailscaleUrl) {
  $accessLines += "Tailscale URL: $tailscaleUrl"
}
$accessLines += 'Use the LAN URL on the same trusted network. Use the Tailscale URL across different networks after signing in on both devices.'
Set-Content -LiteralPath $accessFile -Value $accessLines -Encoding UTF8
Write-Output $accessLines

if (-not $ServerOnly) {
  Start-Process $appUrl
}
