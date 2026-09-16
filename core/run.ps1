$ErrorActionPreference = "Stop"
$coreRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $coreRoot

if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
    py -3.11 -m venv .venv
    & ".venv\Scripts\python.exe" -m pip install --upgrade pip
    & ".venv\Scripts\python.exe" -m pip install -r requirements.txt
}

& ".venv\Scripts\python.exe" -m jarvis_core.main
