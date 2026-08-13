$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Security
$port = Get-NetTCPConnection -LocalPort 8787 -State Listen -ErrorAction SilentlyContinue
if ($port) {
    Write-Host "TradeMentor-server draait al op poort 8787." -ForegroundColor Green
    Start-Sleep -Seconds 3
    exit 0
}

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$tokenFile = Join-Path $PSScriptRoot ".session_token.dpapi"
if (-not (Test-Path -LiteralPath $python)) { throw "Python-runtime niet gevonden." }
if (-not (Test-Path -LiteralPath $tokenFile)) { throw "Beveiligde app-servercode ontbreekt." }

$protectedToken = [Convert]::FromBase64String((Get-Content -LiteralPath $tokenFile -Raw).Trim())
$plainToken = [Security.Cryptography.ProtectedData]::Unprotect(
    $protectedToken,
    $null,
    [Security.Cryptography.DataProtectionScope]::CurrentUser
)
$env:TRADEMENTOR_SESSION_TOKEN = [Text.Encoding]::UTF8.GetString($plainToken)
$env:TRADEMENTOR_ALLOW_LIVE = "true"

Write-Host "TradeMentor LIVE-server wordt gestart..." -ForegroundColor Cyan
Set-Location -LiteralPath $PSScriptRoot
& $python (Join-Path $PSScriptRoot "run_server.py")
