$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$mobileRoot = Join-Path $projectRoot "mobile"
$apiUrl = "http://127.0.0.1:8765"

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    throw "Node.js is not available on PATH. Install Node.js before starting Expo."
}

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "npm is not available on PATH. Install Node.js/npm before starting Expo."
}

if (-not (Test-Path (Join-Path $mobileRoot "node_modules"))) {
    Write-Host "[AI Trader] Installing mobile dependencies..." -ForegroundColor Cyan
    Set-Location $mobileRoot
    npm install
}

try {
    Invoke-WebRequest -UseBasicParsing "$apiUrl/status" -TimeoutSec 3 | Out-Null
} catch {
    Write-Host "[AI Trader] Local API is not responding at $apiUrl." -ForegroundColor Yellow
    Write-Host "[AI Trader] Start it first with scripts\start_local_api.ps1 or .\start_project.ps1." -ForegroundColor Yellow
}

$lanIp = (Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object { $_.IPAddress -notlike "127.*" -and $_.PrefixOrigin -ne "WellKnown" } |
    Select-Object -First 1 -ExpandProperty IPAddress)

Set-Location $mobileRoot
$env:EXPO_PUBLIC_AI_TRADER_API_URL = $apiUrl

Write-Host "[AI Trader] Starting Expo on port 8082." -ForegroundColor Cyan
Write-Host "[AI Trader] Expo will display the QR code in this terminal." -ForegroundColor Cyan
if ($lanIp) {
    Write-Host "[AI Trader] For a physical phone, set EXPO_PUBLIC_AI_TRADER_API_URL to http://$lanIp`:8765 if localhost cannot reach the laptop." -ForegroundColor Cyan
}

npx expo start --port 8082
