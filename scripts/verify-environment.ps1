[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot
$StateDir = Join-Path $RepoRoot '.state'
New-Item -ItemType Directory -Force -Path $StateDir | Out-Null

function Find-VsDevCmd {
    $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
    if (-not (Test-Path $vswhere)) { return $null }
    $path = (& $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath).Trim()
    if (-not $path) { return $null }
    $cmd = Join-Path $path 'Common7\Tools\VsDevCmd.bat'
    if (Test-Path $cmd) { return $cmd }
    return $null
}

function Version-Output([string]$Exe, [string[]]$Args) {
    $cmd = Get-Command $Exe -ErrorAction SilentlyContinue
    if (-not $cmd) { return $null }
    try { return ((& $Exe @Args 2>&1 | Select-Object -First 4) -join "`n").Trim() } catch { return $_.Exception.Message }
}

$checks = [ordered]@{
    git = Version-Output 'git' @('--version')
    cmake = Version-Output 'cmake' @('--version')
    ninja = Version-Output 'ninja' @('--version')
    python = Version-Output 'python' @('--version')
    dxc = Version-Output 'dxc' @('--version')
    vsDevCmd = Find-VsDevCmd
}

$gpu = @()
try {
    $gpu = Get-CimInstance Win32_VideoController | Select-Object Name, PNPDeviceID, DriverVersion, AdapterRAM
} catch {}

$result = [ordered]@{
    generatedUtc = [DateTime]::UtcNow.ToString('o')
    tools = $checks
    gpus = $gpu
    os = Get-CimInstance Win32_OperatingSystem | Select-Object Caption, Version, BuildNumber, OSArchitecture
    cpu = Get-CimInstance Win32_Processor | Select-Object Name, NumberOfCores, NumberOfLogicalProcessors
}

$result | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 (Join-Path $StateDir 'environment.json')
$result | ConvertTo-Json -Depth 8

$missing = @()
foreach ($name in @('git','cmake','ninja','python','dxc')) {
    if (-not $checks[$name]) { $missing += $name }
}
if (-not $checks.vsDevCmd) { $missing += 'Visual Studio C++ Build Tools' }
if ($missing.Count -gt 0) {
    throw "Missing required tools: $($missing -join ', ')"
}

$hasTarget = $false
foreach ($adapter in $gpu) {
    if ($adapter.Name -match '5700\s*XT|Radeon.*5700') { $hasTarget = $true }
}
if (-not $hasTarget) {
    Write-Warning 'RX 5700 XT was not identified by Win32_VideoController. Codex must inspect adapters with DXGI before final tuning.'
}
