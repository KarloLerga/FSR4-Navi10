param(
    [Parameter(Mandatory = $true)][string]$Sequence,
    [string]$RepoRoot = (Get-Location).Path,
    [string]$Configuration = "Release",
    [switch]$KeepRawCaptures
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "BuildEnvironment.ps1")
Import-Fsr4Navi10ToolPath
$DxcCommand = Get-Command dxc -ErrorAction Stop
$DxcPath = $DxcCommand.Source
Initialize-Fsr4Navi10VsEnvironment
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
$Sequence = (Resolve-Path -LiteralPath $Sequence).Path
$BuildRoot = Join-Path $RepoRoot "build\fsr4-rootcause-matrix"
$DataRoot = Join-Path $BuildRoot "case-data"
$ResultsRoot = Join-Path $RepoRoot "artifacts\results\fsr4-rootcause-matrix"

function Assert-PathInside([string]$Path, [string]$Parent) {
    $parentFull = [System.IO.Path]::GetFullPath($Parent).TrimEnd('\') + '\'
    $pathFull = [System.IO.Path]::GetFullPath($Path)
    if (-not $pathFull.StartsWith($parentFull, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing path outside expected directory: $pathFull"
    }
}

Assert-PathInside $BuildRoot $RepoRoot
Assert-PathInside $ResultsRoot (Join-Path $RepoRoot "artifacts\results")
New-Item -ItemType Directory -Force -Path $BuildRoot, $DataRoot, $ResultsRoot | Out-Null

python (Join-Path $RepoRoot "tools\sequence\validate_f4seq.py") $Sequence
if ($LASTEXITCODE -ne 0) { throw "input .f4seq validation failed" }

$Cases = @(
    @{ Name = "intrinsic_literal"; Scalar = "OFF"; Stable = "OFF" },
    @{ Name = "intrinsic_stable";  Scalar = "OFF"; Stable = "ON"  },
    @{ Name = "scalar_literal";    Scalar = "ON";  Stable = "OFF" },
    @{ Name = "scalar_stable";     Scalar = "ON";  Stable = "ON"  }
)

foreach ($Case in $Cases) {
    $CaseData = Join-Path $DataRoot $Case.Name
    $CaptureRoot = Join-Path $CaseData "captures"
    $Report = Join-Path $ResultsRoot ($Case.Name + ".json")
    $ReplayReport = Join-Path $ResultsRoot ($Case.Name + "-post-replay.json")
    Assert-PathInside $CaseData $DataRoot
    if (Test-Path -LiteralPath $CaseData) {
        Remove-Item -LiteralPath $CaseData -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $CaseData, $CaptureRoot | Out-Null

    $ConfigureArgs = @(
        "-S", $RepoRoot,
        "-B", $BuildRoot,
        "-G", "Ninja",
        "-DCMAKE_BUILD_TYPE=$Configuration",
        "-DDXC_EXECUTABLE:FILEPATH=$DxcPath",
        "-DFSR4N10_FORCE_SCALAR_DOT4=$($Case.Scalar)",
        "-DFSR4N10_STABLE_POST_MATH=$($Case.Stable)"
    )
    & cmake @ConfigureArgs
    if ($LASTEXITCODE -ne 0) { throw "CMake configure failed for $($Case.Name)" }

    & cmake --build $BuildRoot --config $Configuration --target fsr4n10_harness
    if ($LASTEXITCODE -ne 0) { throw "build failed for $($Case.Name)" }

    $Harness = Join-Path $BuildRoot "fsr4n10_harness.exe"
    if (-not (Test-Path -LiteralPath $Harness)) {
        $Harness = Get-ChildItem -LiteralPath $BuildRoot -Recurse -File -Filter fsr4n10_harness.exe |
            Select-Object -First 1 -ExpandProperty FullName
    }
    if (-not $Harness) { throw "fsr4n10_harness.exe not found for $($Case.Name)" }

    if (Test-Path -LiteralPath $Report) { Remove-Item -LiteralPath $Report -Force }
    if (Test-Path -LiteralPath $ReplayReport) { Remove-Item -LiteralPath $ReplayReport -Force }
    python (Join-Path $RepoRoot "tools\sequence\run_fsr4_teacher.py") `
        $Harness $Sequence $Report --capture-root $CaptureRoot
    if ($LASTEXITCODE -ne 0) { throw "FSR4 sequence failed for $($Case.Name)" }

    $Provider = Get-Content -LiteralPath $Report -Raw | ConvertFrom-Json
    $Packages = @($Provider.audit_capture_packages | ForEach-Object {
        if ([System.IO.Path]::IsPathRooted($_.path)) { $_.path } else { Join-Path $RepoRoot $_.path }
    })
    if ($Packages.Count -eq 0) { throw "no audited .f4cap packages for $($Case.Name)" }

    $ReplayArgs = @((Join-Path $RepoRoot "tools\oracles\replay_fsr4_post.py"))
    $ReplayArgs += $Packages
    $ReplayArgs += @("--output", $ReplayReport)
    if ($Case.Stable -eq "ON") { $ReplayArgs += "--stable-transforms" }
    python @ReplayArgs
    $ReplayExitCode = $LASTEXITCODE
    if (-not (Test-Path -LiteralPath $ReplayReport)) {
        throw "POST replay did not produce a report for $($Case.Name) (exit code $ReplayExitCode)"
    }
    if ($ReplayExitCode -ne 0) {
        Write-Warning "POST replay gate failed for $($Case.Name); the report is retained for root-cause analysis."
    }

    if (-not $KeepRawCaptures) {
        Get-ChildItem -LiteralPath $CaptureRoot -Directory -Filter "frame_*" | ForEach-Object {
            Assert-PathInside $_.FullName $CaseData
            Remove-Item -LiteralPath $_.FullName -Recurse -Force
        }
    }
}

python (Join-Path $RepoRoot "tools\oracles\summarize_fsr4_rootcause_matrix.py") $ResultsRoot
if ($LASTEXITCODE -ne 0) { throw "matrix summarizer failed" }
Write-Host "Root-cause matrix complete: $(Join-Path $ResultsRoot 'summary.json')"
