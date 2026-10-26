param([int]$Port=8765)
$ErrorActionPreference='Stop'
Set-Location -LiteralPath $PSScriptRoot
$tempPath=Join-Path (Split-Path -Parent $PSScriptRoot) 'work\tmp'
New-Item -ItemType Directory -Force -Path $tempPath | Out-Null
$env:TEMP=$tempPath
$env:TMP=$tempPath
$pythonPath=Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { $pythonPath=Join-Path (Split-Path -Parent $PSScriptRoot) 'work\.venv\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Run setup.ps1 first.' }
if (-not (Test-Path -LiteralPath 'frontend\dist\index.html')) { throw 'Build frontend first: cd frontend; npm ci; npm run build' }
Write-Output "AgentLabs: http://127.0.0.1:$Port (Ctrl+C to stop)"
& $pythonPath -m uvicorn backend.app:app --host 127.0.0.1 --port $Port
