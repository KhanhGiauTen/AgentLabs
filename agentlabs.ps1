param(
  [Parameter(Position=0)]
  [ValidateSet('setup','install','start','validate','status','agents','dashboard','budget','repo-add','repo-list')]
  [string]$Action='start',
  [ValidateSet('lean','hybrid','free')]
  [string]$Mode='lean',
  [switch]$RefreshContracts,
  [string]$RepoName,
  [string]$RepoPath
)
$ErrorActionPreference='Stop'
Set-Location -LiteralPath $PSScriptRoot
$pythonPath=Join-Path (Split-Path -Parent $PSScriptRoot) 'work\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { $pythonPath=Join-Path $PSScriptRoot '.venv\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Run setup-native.ps1 first.' }
$nativeArgs=@($Action,'--mode',$Mode)
if ($RefreshContracts) { $nativeArgs+='--refresh-contracts' }
if ($RepoName) { $nativeArgs+=@('--repo-name',$RepoName) }
if ($RepoPath) { $nativeArgs+=@('--repo-path',$RepoPath) }
& $pythonPath (Join-Path $PSScriptRoot 'scripts\native_lab.py') @nativeArgs
if ($LASTEXITCODE -ne 0) { throw "AgentLabs native command failed: $Action" }
