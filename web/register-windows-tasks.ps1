param(
  [switch]$Install,
  [switch]$Uninstall,
  [switch]$Status,
  [switch]$InstallFirewall
)

$ErrorActionPreference = 'Stop'
$webRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $webRoot
$startScript = Join-Path $webRoot 'start-windows.ps1'
$updateScript = Join-Path $webRoot 'auto-update.ps1'
$taskPrefix = '信披智审'
$serverTaskName = "$taskPrefix - 开机启动服务"
$updateTaskName = "$taskPrefix - 每日更新资料库"
$startupValueName = "$taskPrefix - 登录启动服务"
$runKeyPath = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'

function New-TaskAction([string]$ScriptPath, [string]$ExtraArgument) {
  $arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`" $ExtraArgument"
  return New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arguments -WorkingDirectory $projectRoot
}

function Install-Firewall {
  $ruleName = "$taskPrefix 8767（专用网络）"
  $existing = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
  if (-not $existing) {
    New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Protocol TCP -LocalPort 8767 `
      -Action Allow -Profile Private -RemoteAddress LocalSubnet -Description '仅允许可信专用网络访问信披智审。' | Out-Null
    Write-Output "已创建专用网络防火墙规则：$ruleName"
  } else {
    Write-Output "专用网络防火墙规则已存在：$ruleName"
  }
}

function Install-CurrentUserStartup {
  # HKCU\Run does not require administrator rights and is the fallback when
  # Windows Task Scheduler registration is restricted by local policy.
  if (-not (Test-Path -LiteralPath $runKeyPath)) {
    New-Item -Path $runKeyPath -Force | Out-Null
  }
  $command = "powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$startScript`" -ServerOnly"
  Set-ItemProperty -Path $runKeyPath -Name $startupValueName -Value $command -Type String
  Write-Output "已设置当前用户登录启动项：$startupValueName"
}

function Remove-CurrentUserStartup {
  Remove-ItemProperty -Path $runKeyPath -Name $startupValueName -ErrorAction SilentlyContinue
}

if ($Uninstall) {
  Unregister-ScheduledTask -TaskName $serverTaskName -Confirm:$false -ErrorAction SilentlyContinue
  Unregister-ScheduledTask -TaskName $updateTaskName -Confirm:$false -ErrorAction SilentlyContinue
  Remove-CurrentUserStartup
  Write-Output '已取消信披智审开机启动、登录启动项和每日更新任务。'
  exit 0
}

if ($Install) {
  $taskInstalled = $false
  try {
    $currentUser = "$env:USERDOMAIN\$env:USERNAME"
    $principal = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType Interactive -RunLevel Limited
    $serverTrigger = New-ScheduledTaskTrigger -AtLogOn -User $currentUser
    $serverSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 12)
    Register-ScheduledTask -TaskName $serverTaskName -Action (New-TaskAction $startScript '-ServerOnly') `
      -Trigger $serverTrigger -Principal $principal -Settings $serverSettings -Description '登录 Windows 后启动本机证券合规服务。' -Force | Out-Null

    $updateTrigger = New-ScheduledTaskTrigger -Daily -At '09:00'
    $updateSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 8)
    Register-ScheduledTask -TaskName $updateTaskName -Action (New-TaskAction $updateScript '-Once') `
      -Trigger $updateTrigger -Principal $principal -Settings $updateSettings -Description '每日检查公告、规则并补建本地 RAG 向量。' -Force | Out-Null
    $taskInstalled = $true
    Write-Output '已注册计划任务：登录后自动启动服务；每天 09:00 自动更新资料库并检查 RAG。'
  } catch {
    Write-Output "计划任务注册受系统权限或策略限制，将使用当前用户登录启动项：$($_.Exception.Message)"
  }

  try {
    if (-not $taskInstalled) {
      Install-CurrentUserStartup
      Write-Output '当前用户登录后将自动启动本机服务（无需管理员权限）。'
    }
  } catch {
    throw "无法设置自动启动：计划任务和当前用户启动项均失败。$($_.Exception.Message)"
  }
}

if ($InstallFirewall) { Install-Firewall }

if ($Status -or (-not $Install -and -not $Uninstall -and -not $InstallFirewall)) {
  Get-ScheduledTask -TaskName $serverTaskName, $updateTaskName -ErrorAction SilentlyContinue |
    Select-Object TaskName, State, @{Name='LastRun';Expression={$_.LastRunTime}}, @{Name='NextRun';Expression={$_.NextRunTime}}
  $startup = Get-ItemProperty -Path $runKeyPath -Name $startupValueName -ErrorAction SilentlyContinue
  if ($startup) {
    [PSCustomObject]@{ TaskName = $startupValueName; State = 'Enabled (HKCU Run)'; LastRun = $null; NextRun = $null }
  }
}
