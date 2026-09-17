$ErrorActionPreference = "Stop"
$coreRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $coreRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Run core/run.ps1 once to create the virtual environment before installing autostart."
}
$action = New-ScheduledTaskAction -Execute $python -Argument "-m jarvis_core.main" -WorkingDirectory $coreRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName "JARVIS Core" -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description "Connects the local JARVIS Core to its authenticated gateway" -Force
Write-Host "JARVIS Core will start when $env:USERNAME signs in."
