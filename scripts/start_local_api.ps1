$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $projectRoot
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    throw "Virtual environment not found. Run .\start_project.ps1 first."
}

$env:PYTHONPATH = Join-Path $projectRoot "src"
$env:AI_TRADER_DB_PATH = Join-Path $projectRoot "data\audit.sqlite3"
$env:AI_TRADER_OUTPUT_DIR = Join-Path $projectRoot "data"
$env:AI_TRADER_TRADING_LOG_PATH = Join-Path $projectRoot "governance\TRADING_LOG.md"

Write-Host "[AI Trader] Local API starting on http://127.0.0.1:8765" -ForegroundColor Cyan
Write-Host "[AI Trader] Developer dashboard: http://127.0.0.1:8765/developer-dashboard" -ForegroundColor Cyan
& $venvPython -m ai_trader.cli serve-api --host 127.0.0.1 --port 8765
