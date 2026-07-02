$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

$env:PYTHONPATH = "src"
$python = "C:\Users\t_jeh\AppData\Local\Programs\Python\Python312\python.exe"

& $python -m ai_trader.cli intelligence-refresh --date (Get-Date -Format "yyyy-MM-dd") --report
