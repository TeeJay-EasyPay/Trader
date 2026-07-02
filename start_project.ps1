$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$activate = Join-Path $projectRoot ".venv\Scripts\Activate.ps1"
$apiUrl = "http://127.0.0.1:8765"
$dashboardUrl = "$apiUrl/developer-dashboard"

function Write-Info($message) {
    Write-Host "[AI Trader] $message" -ForegroundColor Cyan
}

function Test-Port($port) {
    $connection = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
    return $null -ne $connection
}

Write-Info "Starting local developer environment..."

if (-not (Test-Path $venvPython)) {
    $systemPython = "C:\Users\t_jeh\AppData\Local\Programs\Python\Python312\python.exe"
    if (-not (Test-Path $systemPython)) {
        throw "Python 3.12 was not found at $systemPython. Install Python 3.12 or update start_project.ps1."
    }
    Write-Info "Creating .venv..."
    & $systemPython -m venv (Join-Path $projectRoot ".venv")
}

. $activate

$env:PYTHONPATH = Join-Path $projectRoot "src"
$env:AI_TRADER_DB_PATH = Join-Path $projectRoot "data\audit.sqlite3"
$env:AI_TRADER_OUTPUT_DIR = Join-Path $projectRoot "data"
$env:AI_TRADER_TRADING_LOG_PATH = Join-Path $projectRoot "governance\TRADING_LOG.md"

Write-Info "Python: $(& $venvPython --version)"
Write-Info "Interpreter: $venvPython"

& $venvPython -m pip show ai-trading-assistant *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Info "Installing project into .venv..."
    & $venvPython -m pip install -e .
}

Write-Info "Initializing local SQLite knowledge tables..."
& $venvPython -m ai_trader.cli intelligence-init --report | Out-Null
& $venvPython -m ai_trader.cli benchmark-init --report | Out-Null

$apiJob = $null
if (Test-Port 8765) {
    Write-Info "Local API already appears to be running on port 8765."
} else {
    Write-Info "Starting Local API on $apiUrl..."
    $apiJob = Start-Job -Name "AITraderLocalApi" -ArgumentList $projectRoot, $venvPython -ScriptBlock {
        param($projectRoot, $venvPython)
        Set-Location $projectRoot
        $env:PYTHONPATH = Join-Path $projectRoot "src"
        $env:AI_TRADER_DB_PATH = Join-Path $projectRoot "data\audit.sqlite3"
        $env:AI_TRADER_OUTPUT_DIR = Join-Path $projectRoot "data"
        $env:AI_TRADER_TRADING_LOG_PATH = Join-Path $projectRoot "governance\TRADING_LOG.md"
        & $venvPython -m ai_trader.cli serve-api --host 127.0.0.1 --port 8765
    }

    for ($i = 0; $i -lt 10; $i++) {
        if (Test-Port 8765) { break }
        Start-Sleep -Seconds 1
    }
}

Write-Info "Useful URLs:"
Write-Host "  API:                 $apiUrl"
Write-Host "  Developer Dashboard: $dashboardUrl"
Write-Host "  SQLite Browser:      run scripts\browse_database.ps1"
Write-Host "  Mobile App:          run scripts\start_mobile_app.ps1"

try {
    $status = Invoke-WebRequest -UseBasicParsing "$apiUrl/developer-status" -TimeoutSec 5
    Write-Info "Developer status endpoint responded: HTTP $($status.StatusCode)"
    try {
        Start-Process $dashboardUrl
    } catch {
        Write-Host "[AI Trader] Open this URL manually: $dashboardUrl" -ForegroundColor Yellow
    }
} catch {
    Write-Host "[AI Trader] API did not respond yet. Run scripts\start_local_api.ps1 in this terminal to see details." -ForegroundColor Yellow
    if ($apiJob) {
        Receive-Job $apiJob
    }
}

if ($apiJob) {
    Write-Info "Ready. Local API is running in this startup session. Press Ctrl+C to stop it."
    try {
        while ($apiJob.State -eq "Running") {
            Start-Sleep -Seconds 2
            Receive-Job $apiJob
        }
    } finally {
        Stop-Job $apiJob -ErrorAction SilentlyContinue
        Remove-Job $apiJob -ErrorAction SilentlyContinue
    }
} else {
    Write-Info "Ready."
}
