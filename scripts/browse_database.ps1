$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$url = "http://127.0.0.1:8770"

if (-not (Test-Path $venvPython)) {
    throw "Virtual environment not found. Run .\start_project.ps1 first."
}

$env:PYTHONPATH = Join-Path $projectRoot "src"
$env:AI_TRADER_DB_PATH = Join-Path $projectRoot "data\audit.sqlite3"

Write-Host "[AI Trader] Starting read-only SQLite browser at $url" -ForegroundColor Cyan
Start-Process $url
& $venvPython -m ai_trader.db_browser
