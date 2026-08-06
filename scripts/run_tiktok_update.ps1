$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Script = Join-Path $PSScriptRoot "update_tiktok_followers.py"

& $Python $Script
exit $LASTEXITCODE
