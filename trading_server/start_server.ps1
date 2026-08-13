$ErrorActionPreference = "Stop"
$python = "$PSScriptRoot\.venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) { throw "Python-runtime niet gevonden." }
& $python "$PSScriptRoot\run_server.py"
