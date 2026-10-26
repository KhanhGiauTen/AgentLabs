param([ValidateSet('lean','hybrid','free')][string]$Mode='lean')
$ErrorActionPreference='Stop'
Set-Location -LiteralPath $PSScriptRoot
$workRoot=Join-Path (Split-Path -Parent $PSScriptRoot) 'work'
New-Item -ItemType Directory -Force -Path $workRoot | Out-Null
$env:PIP_CACHE_DIR=Join-Path $workRoot 'pip-cache'
$env:npm_config_cache=Join-Path $workRoot 'npm-cache'
$env:TEMP=Join-Path $workRoot 'tmp'
$env:TMP=$env:TEMP
New-Item -ItemType Directory -Force -Path $env:TEMP | Out-Null
$pythonPath=Join-Path $workRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
  python -m venv (Join-Path $workRoot '.venv')
  if ($LASTEXITCODE) { throw 'Python 3.11+ virtual environment creation failed.' }
}
& $pythonPath -m pip install -r requirements-native.txt
if ($LASTEXITCODE) { throw 'Native Python dependencies failed.' }
if (-not (Test-Path -LiteralPath '.env')) { Copy-Item -LiteralPath '.env.example' -Destination '.env' }
# The runtime helper enforces OpenClaw's pinned Node version and own local profile.
& $pythonPath scripts/native_lab.py install --mode $Mode
if ($LASTEXITCODE) { throw 'Pinned official OpenClaw runtime installation failed.' }
$nodePath=(& $pythonPath -c "from scripts.openclaw import node_binary; print(node_binary())")
if ($LASTEXITCODE) { throw 'Compatible Node runtime not found.' }
Push-Location native/plugin
try {
  $npmCommand=(Get-Command npm.cmd).Source
  $npmCli=Join-Path (Split-Path -Parent $npmCommand) 'node_modules\npm\bin\npm-cli.js'
  & $nodePath $npmCli ci --ignore-scripts --no-audit --no-fund
  if ($LASTEXITCODE) { throw 'Native research plugin dependencies failed.' }
  & $nodePath $npmCli run build:ui
  if ($LASTEXITCODE) { throw 'Native chat UI build failed.' }
} finally { Pop-Location }
& $pythonPath scripts/native_lab.py setup --mode $Mode
if ($LASTEXITCODE) { throw 'Native profile setup failed.' }
Write-Output 'AgentLabs native installed. Edit .env locally, run .\agentlabs.ps1 start, then .\agentlabs.ps1 dashboard in another terminal.'
