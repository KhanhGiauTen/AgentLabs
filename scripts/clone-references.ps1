param([string]$DestinationRoot=(Split-Path -Parent (Split-Path -Parent $PSScriptRoot)))
$ErrorActionPreference='Stop'
$repositoryRoot=Split-Path -Parent $PSScriptRoot
$pins=Get-Content -LiteralPath (Join-Path $repositoryRoot 'upstreams.lock.json') -Raw | ConvertFrom-Json
New-Item -ItemType Directory -Force -Path $DestinationRoot | Out-Null
foreach($property in $pins.PSObject.Properties){
    $pin=$property.Value
    $destination=Join-Path $DestinationRoot $pin.directory
    if(Test-Path -LiteralPath $destination){
        $head=(& git -C $destination rev-parse HEAD)
        if($LASTEXITCODE -ne 0 -or $head -ne $pin.commit){ throw "Existing checkout differs; preserve it and inspect manually: $destination" }
        Write-Output "Pinned checkout already exists: $destination"
        continue
    }
    & git clone --filter=blob:none --no-checkout --depth 1 $pin.repository $destination
    if($LASTEXITCODE -ne 0){ throw 'Clone failed' }
    & git -C $destination fetch --depth 1 origin $pin.commit
    if($LASTEXITCODE -ne 0){ throw 'Pinned fetch failed' }
    & git -C $destination checkout --detach $pin.commit
    if($LASTEXITCODE -ne 0){ throw 'Pinned checkout failed' }
    Write-Output "Pinned reference ready: $destination"
}
