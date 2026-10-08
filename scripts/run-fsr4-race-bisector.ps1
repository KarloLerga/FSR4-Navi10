param(
    [Parameter(Mandatory=$true)] [string] $Repository,
    [Parameter(Mandatory=$true)] [string] $Sequence,
    [string] $Output = "",
    [int] $MaxPass = 12,
    [switch] $IncludeBarrierBuild
)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$repo = (Resolve-Path -LiteralPath $Repository).Path
$seq = (Resolve-Path -LiteralPath $Sequence).Path
if (-not $Output) { $Output = Join-Path $repo "build\fsr4n10-race-bisector" }
New-Item -ItemType Directory -Path $Output -Force | Out-Null
$campaign = Join-Path $repo "tools\diagnostics\run_prefix_campaign.py"
$analyzer = Join-Path $repo "tools\diagnostics\analyze_scratch_campaign.py"
. (Join-Path $repo "scripts\BuildEnvironment.ps1")
Initialize-Fsr4Navi10VsEnvironment
$env:MLSR_WMMA = ""
Remove-Item Env:\MLSR-WMMA -ErrorAction SilentlyContinue
Remove-Item Env:\MLSR-WATERMARK -ErrorAction SilentlyContinue

# Use dedicated build trees; never alter existing build/release settings.
$variants = @(@{ Name = "standard"; Barrier = "OFF" })
if ($IncludeBarrierBuild) { $variants += @{ Name = "global-barrier"; Barrier = "ON" } }
foreach ($variant in $variants) {
    $name = $variant.Name
    $build = Join-Path $Output ("build-" + $name)
    $results = Join-Path $Output ("results-" + $name)
    Write-Host "Building diagnostic variant $name (global barrier $($variant.Barrier))"
    & cmake -S $repo -B $build -G Ninja `
      -DCMAKE_BUILD_TYPE=Release `
      -DFSR4N10_FORCE_SCALAR_DOT4=ON `
      -DFSR4N10_STABLE_POST_MATH=OFF `
      -DFSR4N10_ENABLE_PASS_PREFIX_DIAGNOSTIC=ON `
      "-DFSR4N10_FORCE_GLOBAL_UAV_BARRIER=$($variant.Barrier)"
    if ($LASTEXITCODE -ne 0) { throw "Configure failed: $name" }
    & cmake --build $build --config Release --target fsr4n10_harness
    if ($LASTEXITCODE -ne 0) { throw "Build failed: $name" }

    $exe = Join-Path $build "fsr4n10_harness.exe"
    if (-not (Test-Path -LiteralPath $exe)) {
        $exe = Join-Path $build "Release\fsr4n10_harness.exe"
    }
    if (-not (Test-Path -LiteralPath $exe)) { throw "Cannot locate built harness: $build" }
    & python $campaign --harness $exe --sequence $seq --output $results `
      --seeds off zero a5 --max-pass $MaxPass --repeats 2 --variant $name
    $campaignExit = $LASTEXITCODE
    if (-not (Test-Path -LiteralPath (Join-Path $results "campaign.json"))) {
        throw "Campaign report missing for $name"
    }
    & python $analyzer (Join-Path $results "campaign.json") `
       --output (Join-Path $results "analysis.json")
    $analyzeExit = $LASTEXITCODE
    Write-Host "Campaign ${name}: run exit=$campaignExit analysis exit=$analyzeExit"
    if ($analyzeExit -ne 0) { throw "Unable to analyze campaign $name" }
    if ($campaignExit -ne 0) { throw "Campaign $name had failed runs; inspect $results\campaign.json and its per-run logs" }
}
if ($IncludeBarrierBuild) {
    $comparison = Join-Path $repo "tools\diagnostics\compare_campaign_variants.py"
    & python $comparison `
      --standard (Join-Path $Output "results-standard\campaign.json") `
      --barrier (Join-Path $Output "results-global-barrier\campaign.json") `
      --output (Join-Path $Output "variant-comparison.json")
    if ($LASTEXITCODE -ne 0) { throw "Cross-variant input validation/comparison failed" }
}
Write-Host "Diagnostic campaign completed. Output directory: $Output"
Write-Host "Do NOT unlock O0/O1-O13 without full provider parity and run-to-run repeatability."
