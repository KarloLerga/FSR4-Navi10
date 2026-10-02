[CmdletBinding()]
param()
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
& (Join-Path $PSScriptRoot 'bootstrap.ps1')
& (Join-Path $PSScriptRoot 'configure.ps1') -Configuration Release
& (Join-Path $PSScriptRoot 'build.ps1') -Configuration Release
if (Test-Path (Join-Path $PSScriptRoot 'validate.ps1')) { & (Join-Path $PSScriptRoot 'validate.ps1') -Configuration Release }
if (Test-Path (Join-Path $PSScriptRoot 'benchmark.ps1')) { & (Join-Path $PSScriptRoot 'benchmark.ps1') -Configuration Release }
if (Test-Path (Join-Path $PSScriptRoot 'package.ps1')) { & (Join-Path $PSScriptRoot 'package.ps1') }
