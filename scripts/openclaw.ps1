param([ValidateSet('setup','install','start','status','validate','version')][string]$Action='start')
$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
$pythonPath=Join-Path (Split-Path -Parent $projectRoot) 'work\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { $pythonPath=Join-Path $projectRoot '.venv\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Run setup.ps1 first.' }
& $pythonPath (Join-Path $PSScriptRoot 'openclaw.py') $Action
exit $LASTEXITCODE
