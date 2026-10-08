param(
    [Parameter(Mandatory=$true)] [string] $Repository,
    [Parameter(Mandatory=$true)] [string] $Sequence,
    [string] $Output = "",
    [string[]] $Seeds = @('zero'),
    [int] $Repeats = 2,
    [int] $TraceFrame = 0
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$repo = (Resolve-Path -LiteralPath $Repository).Path
$sequencePath = (Resolve-Path -LiteralPath $Sequence).Path
if (-not $Output) { $Output = Join-Path $repo 'build\i8-numeric-bisector' }
New-Item -Path $Output -ItemType Directory -Force | Out-Null
. (Join-Path $repo 'scripts\BuildEnvironment.ps1')
Initialize-Fsr4Navi10VsEnvironment
Remove-Item Env:\MLSR-WMMA -ErrorAction SilentlyContinue
Remove-Item Env:\MLSR-WATERMARK -ErrorAction SilentlyContinue
$variants = @(
    @{Name='guard_intrinsic'; Scalar='OFF'; Arithmetic='intrinsic'},
    @{Name='guard_scalar'; Scalar='ON'; Arithmetic='scalar'}
)
foreach ($v in $variants) {
    $build = Join-Path $Output ('build-' + $v.Name)
    & cmake -S $repo -B $build -G Ninja '-DCMAKE_BUILD_TYPE=Release' `
        '-DFSR4N10_PASS11_BOUNDS_GUARD=ON' `
        '-DFSR4N10_STABLE_POST_MATH=OFF' `
        '-DFSR4N10_ENABLE_PASS_PREFIX_DIAGNOSTIC=ON' `
        '-DFSR4N10_FORCE_GLOBAL_UAV_BARRIER=OFF' `
        "-DFSR4N10_FORCE_SCALAR_DOT4=$($v.Scalar)" `
        '-DFSR4N10_SCALAR_DOT4_PASS_SET='
    if ($LASTEXITCODE -ne 0) { throw "Configure failed: $($v.Name)" }
    & cmake --build $build --config Release --target fsr4n10_harness
    if ($LASTEXITCODE -ne 0) { throw "Build failed: $($v.Name)" }
}
& python (Join-Path $repo 'tools\diagnostics\i8_tensor_layout.py') `
    --repo $repo --output (Join-Path $Output 'tensor_contracts.json')
if ($LASTEXITCODE -ne 0) { throw 'HLSL output tensor contract extraction failed' }
foreach ($v in $variants) {
    $build = Join-Path $Output ('build-' + $v.Name)
    $exe = Join-Path $build 'fsr4n10_harness.exe'
    if (-not (Test-Path -LiteralPath $exe)) { $exe = Join-Path $build 'Release\fsr4n10_harness.exe' }
    if (-not (Test-Path -LiteralPath $exe)) { throw "Missing compiled harness: $exe" }
    & python (Join-Path $repo 'tools\diagnostics\run_i8_numeric_bisector.py') `
        --harness $exe --sequence $sequencePath `
        --output (Join-Path $Output ('results-' + $v.Name)) `
        --variant $v.Name --arithmetic $v.Arithmetic `
        --stages 0 1 2 3 4 5 6 7 8 9 10 11 12 full `
        --seeds @Seeds --repeats $Repeats --trace-frame $TraceFrame
    if ($LASTEXITCODE -ne 0) { throw "Incomplete prefix campaign: $($v.Name)" }
}
& python (Join-Path $repo 'tools\diagnostics\analyze_i8_numeric_bisector.py') `
    --repo $repo `
    --left (Join-Path $Output 'results-guard_intrinsic\campaign.json') `
    --right (Join-Path $Output 'results-guard_scalar\campaign.json') `
    --output (Join-Path $Output 'analysis.json') `
    --csv (Join-Path $Output 'summary.csv')
if ($LASTEXITCODE -ne 0) { throw 'Invalid provenance, run-to-run repeatability, or aligned inputs' }
Write-Host "Numeric bisector results: $Output\analysis.json"
Write-Host 'Do not infer arithmetic correctness from a difference without an independent per-pass oracle.'
