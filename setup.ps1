$ErrorActionPreference='Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:PIP_CACHE_DIR=Join-Path (Split-Path -Parent $PSScriptRoot) 'work\pip-cache'
$env:npm_config_cache=Join-Path (Split-Path -Parent $PSScriptRoot) 'work\npm-cache'
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) { python -m venv .venv; if ($LASTEXITCODE) { throw 'Python venv failed' } }
& '.venv\Scripts\python.exe' -m pip install -r requirements.txt
if ($LASTEXITCODE) { throw 'Python dependency installation failed' }
Push-Location frontend
try { npm ci --no-audit --no-fund; if ($LASTEXITCODE) { throw 'npm ci failed' }; npm run build; if ($LASTEXITCODE) { throw 'Frontend build failed' } } finally { Pop-Location }
if (-not (Test-Path -LiteralPath '.env')) { Copy-Item -LiteralPath '.env.example' -Destination '.env' }
Write-Output 'Setup complete. Start with .\start.ps1; configure API keys in .env when ready.'
