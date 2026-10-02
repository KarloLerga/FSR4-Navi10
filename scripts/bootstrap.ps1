[CmdletBinding()]
param(
    [switch]$SkipRadeonTools,
    [switch]$SkipUpstreams,
    [switch]$NoElevation
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$RepoRoot = Split-Path -Parent $PSScriptRoot
$StateDir = Join-Path $RepoRoot '.state'
$ToolsDir = Join-Path $RepoRoot '.tools'
New-Item -ItemType Directory -Force -Path $StateDir, $ToolsDir | Out-Null

function Write-Step([string]$Message) {
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

function Test-Admin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Refresh-Path {
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = "$machine;$user"
}

function Test-Cmd([string]$Name) {
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Ensure-WingetPackage {
    param(
        [Parameter(Mandatory=$true)][string]$Id,
        [string[]]$ProbeCommands = @(),
        [string]$Override = ''
    )

    foreach ($probe in $ProbeCommands) {
        if (Test-Cmd $probe) {
            Write-Host "Already available: $Id ($probe)"
            return
        }
    }

    Write-Step "Installing $Id"
    $wingetArgs = @('install', '--id', $Id, '--exact', '--accept-package-agreements', '--accept-source-agreements', '--silent')
    if ($Override) {
        $wingetArgs += @('--override', $Override)
    }
    & winget @wingetArgs
    if ($LASTEXITCODE -ne 0) {
        throw "winget install failed for $Id with exit code $LASTEXITCODE"
    }
    Refresh-Path
}

if ($env:OS -ne 'Windows_NT') {
    throw 'This bootstrap is intentionally Windows-only.'
}

if (-not (Test-Cmd 'winget')) {
    throw 'winget is required. Install/update Windows App Installer from Microsoft Store, then rerun.'
}

if (-not $NoElevation -and -not (Test-Admin)) {
    Write-Step 'Requesting administrator elevation for toolchain installation'
    $argList = @(
        '-NoProfile',
        '-ExecutionPolicy', 'Bypass',
        '-File', ('"' + $PSCommandPath + '"')
    )
    if ($SkipRadeonTools) { $argList += '-SkipRadeonTools' }
    if ($SkipUpstreams) { $argList += '-SkipUpstreams' }
    $argList += '-NoElevation'
    $elevatedProcess = Start-Process -FilePath 'powershell.exe' -Verb RunAs -ArgumentList ($argList -join ' ') -Wait -PassThru
    exit $elevatedProcess.ExitCode
}

Write-Step 'Installing/verifying command-line prerequisites'
Ensure-WingetPackage -Id 'Git.Git' -ProbeCommands @('git')
Ensure-WingetPackage -Id 'Kitware.CMake' -ProbeCommands @('cmake')
Ensure-WingetPackage -Id 'Ninja-build.Ninja' -ProbeCommands @('ninja')
Ensure-WingetPackage -Id 'Python.Python.3.12' -ProbeCommands @('python', 'py')
Ensure-WingetPackage -Id '7zip.7zip' -ProbeCommands @('7z')
Ensure-WingetPackage -Id 'Microsoft.DirectX.ShaderCompiler' -ProbeCommands @('dxc')

Write-Step 'Installing/verifying Visual Studio 2022 Build Tools C++ workload'
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
$needsVs = $true
if (Test-Path $vswhere) {
    $installPath = & $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
    if ($installPath) { $needsVs = $false }
}
if ($needsVs) {
    $override = '--wait --passive --norestart --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended --add Microsoft.VisualStudio.Component.VC.vcpkg'
    Ensure-WingetPackage -Id 'Microsoft.VisualStudio.2022.BuildTools' -Override $override
}

Refresh-Path

function Install-GitHubReleaseAsset {
    param(
        [Parameter(Mandatory=$true)][string]$Repo,
        [Parameter(Mandatory=$true)][string]$AssetRegex,
        [Parameter(Mandatory=$true)][string]$Destination
    )
    try {
        $headers = @{ 'User-Agent' = 'FSR4-Navi10-bootstrap' }
        $release = Invoke-RestMethod -Headers $headers -Uri "https://api.github.com/repos/$Repo/releases/latest"
        $asset = $release.assets | Where-Object { $_.name -match $AssetRegex } | Select-Object -First 1
        if (-not $asset) {
            Write-Warning "No matching asset for $Repo / $AssetRegex"
            return $false
        }
        $zip = Join-Path $env:TEMP $asset.name
        Write-Host "Downloading $($asset.browser_download_url)"
        Invoke-WebRequest -Headers $headers -Uri $asset.browser_download_url -OutFile $zip
        if (Test-Path $Destination) { Remove-Item -Recurse -Force $Destination }
        New-Item -ItemType Directory -Force -Path $Destination | Out-Null
        Expand-Archive -Path $zip -DestinationPath $Destination -Force
        Remove-Item -Force $zip
        return $true
    } catch {
        Write-Warning "Optional tool download failed for $Repo: $($_.Exception.Message)"
        return $false
    }
}

if (-not $SkipRadeonTools) {
    Write-Step 'Downloading optional official AMD developer tools (best effort)'
    [void](Install-GitHubReleaseAsset -Repo 'GPUOpen-Tools/radeon_gpu_analyzer' -AssetRegex '(?i)(windows|win).*\.zip$|\.zip$' -Destination (Join-Path $ToolsDir 'rga'))
    [void](Install-GitHubReleaseAsset -Repo 'GPUOpen-Tools/radeon_gpu_profiler' -AssetRegex '(?i)RadeonDeveloperToolSuite.*\.zip$' -Destination (Join-Path $ToolsDir 'radeon-developer-suite'))
}

if (-not $SkipUpstreams) {
    Write-Step 'Fetching pinned upstream/reference repositories'
    & (Join-Path $PSScriptRoot 'fetch-upstreams.ps1')
    if ($LASTEXITCODE -ne 0) { throw 'fetch-upstreams.ps1 failed' }
}

Write-Step 'Verifying environment'
& (Join-Path $PSScriptRoot 'verify-environment.ps1')
if ($LASTEXITCODE -ne 0) { throw 'Environment verification failed' }

$stamp = [ordered]@{
    completedUtc = [DateTime]::UtcNow.ToString('o')
    computerName = $env:COMPUTERNAME
    user = $env:USERNAME
    repoRoot = $RepoRoot
}
$stamp | ConvertTo-Json -Depth 4 | Set-Content -Encoding UTF8 (Join-Path $StateDir 'bootstrap.json')

Write-Host "`nBootstrap complete." -ForegroundColor Green
