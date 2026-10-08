param(
    [Parameter(Mandatory=$true)] [string] $Repository,
    [Parameter(Mandatory=$true)] [string] $Sequence,
    [string] $Output = "",
    [int] $Repeats = 3
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$repo = (Resolve-Path -LiteralPath $Repository).Path
$seq = (Resolve-Path -LiteralPath $Sequence).Path
if (-not $Output) { $Output = Join-Path $repo 'build\pass11-guard-campaign' }
New-Item -ItemType Directory -Path $Output -Force | Out-Null
. (Join-Path $repo 'scripts\BuildEnvironment.ps1')
Initialize-Fsr4Navi10VsEnvironment
Remove-Item Env:\MLSR-WMMA -ErrorAction SilentlyContinue
Remove-Item Env:\MLSR-WATERMARK -ErrorAction SilentlyContinue

$variants = @(
    @{ Name='baseline_scalar'; Guard='OFF'; Scalar='ON'; Expected='off' },
    @{ Name='guard_scalar'; Guard='ON'; Scalar='ON'; Expected='on' },
    @{ Name='guard_intrinsic'; Guard='ON'; Scalar='OFF'; Expected='on' }
)
# Survey the other pinned I8 model variants as a forward-compatibility audit.
& python (Join-Path $repo 'tools\diagnostics\audit_i8_pass11_coverage.py') `
    --fsr4-root (Join-Path $repo 'third_party\fidelityfx-fsr4-source\Kits\FidelityFX\upscalers\fsr4') `
    --output (Join-Path $Output 'i8_pass11_all_variants_audit.json')
if ($LASTEXITCODE -ne 0) { throw 'Native I8 source contract survey failed' }
# Build all variants BEFORE experiments; an unused shader override can
# invalidate an expensive 72-process campaign, so verify compiled artifacts first.
foreach ($variant in $variants) {
    $name = $variant.Name
    $build = Join-Path $Output ('build-' + $name)
    Write-Host "Configuring $name (bounds guard=$($variant.Guard), scalar=$($variant.Scalar))"
    & cmake -S $repo -B $build -G Ninja `
        '-DCMAKE_BUILD_TYPE=Release' `
        '-DFSR4N10_ENABLE_PASS_PREFIX_DIAGNOSTIC=ON' `
        '-DFSR4N10_FORCE_GLOBAL_UAV_BARRIER=OFF' `
        '-DFSR4N10_STABLE_POST_MATH=OFF' `
        "-DFSR4N10_PASS11_BOUNDS_GUARD=$($variant.Guard)" `
        "-DFSR4N10_FORCE_SCALAR_DOT4=$($variant.Scalar)"
    if ($LASTEXITCODE -ne 0) { throw "CMake configure failed: $name" }
    & cmake --build $build --config Release --target fsr4n10_harness
    if ($LASTEXITCODE -ne 0) { throw "CMake build failed: $name" }
}

& python (Join-Path $repo 'tools\diagnostics\verify_shader_diff.py') `
    --baseline (Join-Path $Output 'build-baseline_scalar\teacher\provider_i8_native_1080\manifest.json') `
    --guard (Join-Path $Output 'build-guard_scalar\teacher\provider_i8_native_1080\manifest.json') `
    --output (Join-Path $Output 'compiled_shader_diff.json')
if ($LASTEXITCODE -ne 0) { throw 'Compiled Pass 11 artifact/include verification failed; GPU campaign was not run' }

foreach ($variant in $variants) {
    $name = $variant.Name
    $build = Join-Path $Output ('build-' + $name)
    $results = Join-Path $Output ('results-' + $name)
    $exe = Join-Path $build 'fsr4n10_harness.exe'
    if (-not (Test-Path -LiteralPath $exe)) { $exe = Join-Path $build 'Release\fsr4n10_harness.exe' }
    if (-not (Test-Path -LiteralPath $exe)) { throw "Harness not found: $exe" }
    & python (Join-Path $repo 'tools\diagnostics\run_pass11_guard_campaign.py') `
      --harness $exe --sequence $seq --output $results `
      --seeds zero a5 --passes 10 11 12 full --repeats $Repeats `
      --trace-frame 0 --variant $name --expected-guard $variant.Expected
    if ($LASTEXITCODE -ne 0) { throw "GPU run failed: $name; partial results in $results" }
    & python (Join-Path $repo 'tools\diagnostics\analyze_pass11_alias.py') `
      --campaign (Join-Path $results 'campaign.json') `
      --output (Join-Path $results 'alias_map.json')
    if ($LASTEXITCODE -ne 0) { throw "Alias analysis failed: $name" }
}
& python (Join-Path $repo 'tools\diagnostics\evaluate_pass11_guard.py') `
    --baseline (Join-Path $Output 'results-baseline_scalar\campaign.json') `
    --guard-scalar (Join-Path $Output 'results-guard_scalar\campaign.json') `
    --guard-intrinsic (Join-Path $Output 'results-guard_intrinsic\campaign.json') `
    --output (Join-Path $Output 'pass11_guard_evaluation.json')
if ($LASTEXITCODE -ne 0) { throw 'Guard comparison failed' }
Write-Host "Complete; inspect $Output\pass11_guard_evaluation.json"
Write-Host 'IMPORTANT: O0 remains CLOSED until its separate acceptance suite passes.'
