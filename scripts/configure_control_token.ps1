param(
    [string]$ApiUrl = "https://trader-no0f.onrender.com",
    [switch]$ShowToken
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$rootEnvPath = Join-Path $repoRoot ".env"
$mobileEnvPath = Join-Path $repoRoot "mobile\.env.local"

function New-ControlToken {
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($bytes)
    } finally {
        $rng.Dispose()
    }
    return -join ($bytes | ForEach-Object { $_.ToString("x2") })
}

function Read-EnvValue {
    param(
        [string]$Path,
        [string]$Key
    )
    if (-not (Test-Path $Path)) {
        return $null
    }
    $line = Get-Content $Path | Where-Object { $_ -match "^$([regex]::Escape($Key))=" } | Select-Object -First 1
    if (-not $line) {
        return $null
    }
    return $line.Substring($Key.Length + 1).Trim()
}

function Set-EnvValue {
    param(
        [string]$Path,
        [string]$Key,
        [string]$Value
    )
    $dir = Split-Path -Parent $Path
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir | Out-Null
    }

    $lines = @()
    if (Test-Path $Path) {
        $lines = @(Get-Content $Path)
    }

    $found = $false
    $updated = New-Object System.Collections.Generic.List[string]
    foreach ($line in $lines) {
        if ($line -match "^$([regex]::Escape($Key))=") {
            $found = $true
            $updated.Add("$Key=$Value")
        } else {
            $updated.Add($line)
        }
    }

    if (-not $found) {
        $updated.Add("$Key=$Value")
    }

    Set-Content -Path $Path -Value $updated -Encoding UTF8
}

$token = Read-EnvValue -Path $rootEnvPath -Key "AI_TRADER_API_TOKEN"
if (-not $token -or $token -eq "replace-with-long-random-token") {
    $token = New-ControlToken
}

Set-EnvValue -Path $rootEnvPath -Key "AI_TRADER_API_TOKEN" -Value $token
Set-EnvValue -Path $mobileEnvPath -Key "EXPO_PUBLIC_AI_TRADER_API_URL" -Value $ApiUrl
Set-EnvValue -Path $mobileEnvPath -Key "EXPO_PUBLIC_AI_TRADER_API_TOKEN" -Value $token

$masked = if ($token.Length -ge 12) {
    "$($token.Substring(0, 6))...$($token.Substring($token.Length - 6))"
} else {
    "configured"
}

Write-Host "AI Trader control token configured locally."
Write-Host "Root env: $rootEnvPath"
Write-Host "Mobile env: $mobileEnvPath"
Write-Host "Token: $masked"
Write-Host ""
Write-Host "Next required hosted step:"
Write-Host "Set this same token as AI_TRADER_API_TOKEN in Render, then redeploy the Render service."
if ($ShowToken) {
    Write-Host ""
    Write-Host "Full token for copying into Render:"
    Write-Host $token
}
