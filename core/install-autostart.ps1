$ErrorActionPreference = "Stop"
$coreRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$runScript = Join-Path $coreRoot "run.ps1"
$powershell = (Get-Command powershell.exe).Source
$action = New-ScheduledTaskAction -Execute $powershell -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$runScript`""
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName "JARVIS Core" -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description "Connects the local JARVIS Core to its authenticated gateway" -Force
Write-Host "JARVIS Core will start when $env:USERNAME signs in."
