[CmdletBinding()]
param([ValidateSet('Debug','RelWithDebInfo','Release')][string]$Configuration='Release')
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$Root=Split-Path -Parent $PSScriptRoot
$Build=Join-Path $Root ("build\"+$Configuration.ToLowerInvariant())
New-Item -ItemType Directory -Force -Path $Build | Out-Null
cmake -S $Root -B $Build -G Ninja -DCMAKE_BUILD_TYPE=$Configuration
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
