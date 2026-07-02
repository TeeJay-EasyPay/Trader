$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$runner = Join-Path $repoRoot "scripts\run_daily_intelligence_refresh.ps1"
$taskName = "AI Trader Investment Intelligence Daily Refresh"

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$runner`""
$trigger = New-ScheduledTaskTrigger -Daily -At 7:00am
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Description "Runs the local AI Trader Investment Intelligence Engine refresh." -Force

Write-Output "Registered scheduled task: $taskName"
