[CmdletBinding()]
param(
    [switch]$SkipResearch
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot
$ConfigPath = Join-Path $RepoRoot 'config\upstreams.json'
$ThirdParty = Join-Path $RepoRoot 'third_party'
$Research = Join-Path $RepoRoot 'research'
New-Item -ItemType Directory -Force -Path $ThirdParty, $Research | Out-Null

if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw 'git not found' }
$config = Get-Content -Raw $ConfigPath | ConvertFrom-Json

function Invoke-Git([string[]]$GitArgs, [string]$WorkingDir = $RepoRoot) {
    Push-Location $WorkingDir
    try {
        & git @GitArgs
        if ($LASTEXITCODE -ne 0) { throw "git failed: git $($GitArgs -join ' ')" }
    } finally { Pop-Location }
}

function Get-Commit([string]$Path) {
    return (& git -C $Path rev-parse HEAD).Trim()
}

function Clone-PinnedObject {
    param([string]$Repo, [string]$Commit, [string]$Dest)
    if (Test-Path (Join-Path $Dest '.git')) {
        return
    }
    if (Test-Path $Dest) { Remove-Item -Recurse -Force $Dest }
    New-Item -ItemType Directory -Force -Path $Dest | Out-Null
    Invoke-Git @('init') $Dest
    Invoke-Git @('remote','add','origin',$Repo) $Dest
    Invoke-Git @('-c','protocol.version=2','fetch','--depth','1','origin',$Commit) $Dest
    Invoke-Git @('checkout','--detach','FETCH_HEAD') $Dest
}

function Clone-Ref {
    param([string]$Repo, [string]$Ref, [string]$Dest)
    if (Test-Path (Join-Path $Dest '.git')) { return }
    Invoke-Git @('clone','--depth','1','--branch',$Ref,$Repo,$Dest)
}

$src = $config.fidelityfx_fsr4_source
$fsr4Dest = Join-Path $ThirdParty 'fidelityfx-fsr4-source'
$usedFallback = $false
try {
    Write-Host "Fetching official AMD source object $($src.commit)..."
    Clone-PinnedObject -Repo $src.official_repo -Commit $src.commit -Dest $fsr4Dest
    if (-not (Test-Path (Join-Path $fsr4Dest $src.required_path))) {
        throw "Official object did not contain required path $($src.required_path)"
    }
} catch {
    Write-Warning "Official object fetch failed: $($_.Exception.Message)"
    Write-Warning 'Using documented read-only source mirror fallback. Do not execute mirror-provided scripts.'
    if (Test-Path $fsr4Dest) { Remove-Item -Recurse -Force $fsr4Dest }
    Clone-Ref -Repo $src.fallback_repo -Ref $src.fallback_ref -Dest $fsr4Dest
    if (-not (Test-Path (Join-Path $fsr4Dest $src.required_path))) {
        throw 'Fallback source does not contain expected FSR4 path.'
    }
    $usedFallback = $true
}

$currentDest = Join-Path $ThirdParty 'fidelityfx-current'
Clone-Ref -Repo $config.fidelityfx_current.repo -Ref $config.fidelityfx_current.ref -Dest $currentDest

if (-not $SkipResearch) {
    foreach ($item in $config.research) {
        $dest = Join-Path $Research $item.name
        try {
            Clone-Ref -Repo $item.repo -Ref $item.ref -Dest $dest
        } catch {
            Write-Warning "Research clone failed for $($item.name): $($_.Exception.Message)"
        }
    }
}

function Get-FileSha([string]$Path) {
    if (-not (Test-Path $Path -PathType Leaf)) { return $null }
    return (Get-FileHash -Algorithm SHA256 $Path).Hash.ToLowerInvariant()
}

$licenseCandidates = @(
    (Join-Path $fsr4Dest 'LICENSE'),
    (Join-Path $fsr4Dest 'docs\license.md')
)
$licenseInfo = @()
foreach ($p in $licenseCandidates) {
    if (Test-Path $p) {
        $licenseInfo += [ordered]@{ path = $p.Substring($RepoRoot.Length + 1); sha256 = Get-FileSha $p }
    }
}

$modelAssets = Get-ChildItem -Path (Join-Path $fsr4Dest $src.required_path) -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match 'initializers.*\.bin$|\.hlsl$|\.hlsli$' }
$assetHashes = @()
foreach ($f in $modelAssets) {
    if ($f.Name -match 'initializers.*\.bin$') {
        $assetHashes += [ordered]@{ path = $f.FullName.Substring($RepoRoot.Length + 1); bytes = $f.Length; sha256 = Get-FileSha $f.FullName }
    }
}

$lock = [ordered]@{
    generatedUtc = [DateTime]::UtcNow.ToString('o')
    fsr4Source = [ordered]@{
        requestedOfficialCommit = $src.commit
        usedFallback = $usedFallback
        repository = if ($usedFallback) { $src.fallback_repo } else { $src.official_repo }
        actualCommit = Get-Commit $fsr4Dest
        requiredPath = $src.required_path
        licenses = $licenseInfo
        modelAssets = $assetHashes
    }
    currentSdk = [ordered]@{
        repository = $config.fidelityfx_current.repo
        requestedRef = $config.fidelityfx_current.ref
        actualCommit = Get-Commit $currentDest
    }
}
$lock | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 (Join-Path $ThirdParty 'LOCK.json')
Write-Host "Upstreams fetched and locked: $(Join-Path $ThirdParty 'LOCK.json')" -ForegroundColor Green
