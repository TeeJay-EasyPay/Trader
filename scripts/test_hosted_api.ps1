$ErrorActionPreference = "Stop"

param(
    [Parameter(Mandatory = $true)]
    [string]$BaseUrl,

    [Parameter(Mandatory = $true)]
    [string]$ApiToken
)

$headers = @{ Authorization = "Bearer $ApiToken" }

Write-Host "[AI Trader] Testing hosted API: $BaseUrl" -ForegroundColor Cyan
$status = Invoke-WebRequest -UseBasicParsing "$BaseUrl/status" -Headers $headers -TimeoutSec 20 | ConvertFrom-Json
$companies = Invoke-WebRequest -UseBasicParsing "$BaseUrl/intelligence/companies" -Headers $headers -TimeoutSec 20 | ConvertFrom-Json
$themes = Invoke-WebRequest -UseBasicParsing "$BaseUrl/intelligence/themes" -Headers $headers -TimeoutSec 20 | ConvertFrom-Json
$bench = Invoke-WebRequest -UseBasicParsing "$BaseUrl/benchmark-traders" -Headers $headers -TimeoutSec 20 | ConvertFrom-Json

Write-Host "System Status: $($status.system_status)"
Write-Host "Paper / Live Mode: $($status.paper_live_mode)"
Write-Host "Companies: $($companies.companies.Count)"
Write-Host "Themes: $($themes.themes.Count)"
Write-Host "Benchmark Traders: $($bench.benchmark_traders.Count)"
