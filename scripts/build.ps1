[CmdletBinding()]
param([ValidateSet('Debug','RelWithDebInfo','Release')][string]$Configuration='Release')
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$Root=Split-Path -Parent $PSScriptRoot
$Build=Join-Path $Root ("build\"+$Configuration.ToLowerInvariant())
if (-not (Test-Path (Join-Path $Build 'build.ninja'))) { & (Join-Path $PSScriptRoot 'configure.ps1') -Configuration $Configuration }
cmake --build $Build --parallel
exit $LASTEXITCODE
