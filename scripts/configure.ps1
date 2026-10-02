[CmdletBinding()]
param([ValidateSet('Debug','RelWithDebInfo','Release')][string]$Configuration='Release')
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'BuildEnvironment.ps1')
Import-Fsr4Navi10ToolPath
$dxcCommand = Get-Command dxc -ErrorAction Stop
$dxcPath = $dxcCommand.Source
if (-not $dxcPath) { throw 'The DXC executable path could not be resolved.' }
Initialize-Fsr4Navi10VsEnvironment
$Root=Split-Path -Parent $PSScriptRoot
$Build=Join-Path $Root ("build\"+$Configuration.ToLowerInvariant())
New-Item -ItemType Directory -Force -Path $Build | Out-Null
& cmake -S $Root -B $Build -G Ninja "-DCMAKE_BUILD_TYPE:STRING=$Configuration" "-DDXC_EXECUTABLE:FILEPATH=$dxcPath"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
