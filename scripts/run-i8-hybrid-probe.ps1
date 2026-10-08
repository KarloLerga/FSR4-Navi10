param(
    [Parameter(Mandatory=$true)] [string] $Repository,
    [Parameter(Mandatory=$true)] [string] $Sequence,
    [Parameter(Mandatory=$true)] [ValidateRange(1, 12)] [int] $Pass,
    [string] $Output = "",
    [int] $Repeats = 2,
    [int] $TraceFrame = 0
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$repo = (Resolve-Path -LiteralPath $Repository).Path
$seq = (Resolve-Path -LiteralPath $Sequence).Path
if (-not $Output) { $Output = Join-Path $repo ("build\i8-hybrid-pass-$Pass") }
New-Item -ItemType Directory -Path $Output -Force | Out-Null
. (Join-Path $repo 'scripts\BuildEnvironment.ps1')
Initialize-Fsr4Navi10VsEnvironment
Remove-Item Env:\MLSR-WMMA -ErrorAction SilentlyContinue
Remove-Item Env:\MLSR-WATERMARK -ErrorAction SilentlyContinue
$variants = @(
    @{Name='guard_intrinsic'; PassSet=''; Arithmetic='intrinsic'},
    @{Name='hybrid'; PassSet=[string]$Pass; Arithmetic='hybrid'}
)
foreach ($v in $variants) {
    $build = Join-Path $Output ('build-' + $v.Name)
    & cmake -S $repo -B $build -G Ninja '-DCMAKE_BUILD_TYPE=Release' `
        '-DFSR4N10_PASS11_BOUNDS_GUARD=ON' `
        '-DFSR4N10_FORCE_SCALAR_DOT4=OFF' `
        '-DFSR4N10_STABLE_POST_MATH=OFF' `
        '-DFSR4N10_FORCE_GLOBAL_UAV_BARRIER=OFF' `
        '-DFSR4N10_ENABLE_PASS_PREFIX_DIAGNOSTIC=ON' `
        "-DFSR4N10_SCALAR_DOT4_PASS_SET=$($v.PassSet)"
    if ($LASTEXITCODE -ne 0) { throw "Configure failed: $($v.Name)" }
    & cmake --build $build --config Release --target fsr4n10_harness
    if ($LASTEXITCODE -ne 0) { throw "Build failed: $($v.Name)" }
}
& python (Join-Path $repo 'tools\diagnostics\verify_hybrid_shader.py') `
    --native (Join-Path $Output 'build-guard_intrinsic\teacher\provider_i8_native_1080\manifest.json') `
    --hybrid (Join-Path $Output 'build-hybrid\teacher\provider_i8_native_1080\manifest.json') `
    --pass $Pass --output (Join-Path $Output 'shader_payload_validation.json')
if ($LASTEXITCODE -ne 0) { throw 'The binary payload change was NOT isolated to one model pass' }
$previous = $Pass - 1
foreach ($v in $variants) {
    $build = Join-Path $Output ('build-' + $v.Name)
    $exe = Join-Path $build 'fsr4n10_harness.exe'
    if (-not (Test-Path -LiteralPath $exe)) { $exe = Join-Path $build 'Release\fsr4n10_harness.exe' }
    $args = @('--harness', $exe, '--sequence', $seq, '--output',
      (Join-Path $Output ('results-' + $v.Name)), '--variant', $v.Name,
      '--arithmetic', $v.Arithmetic, '--stages', [string]$previous, [string]$Pass,
      'full', '--seeds', 'zero', '--repeats', [string]$Repeats,
      '--trace-frame', [string]$TraceFrame)
    if ($v.Arithmetic -eq 'hybrid') { $args += @('--selected-passes', [string]$Pass) }
    & python (Join-Path $repo 'tools\diagnostics\run_i8_numeric_bisector.py') @args
    if ($LASTEXITCODE -ne 0) { throw "Hybrid campaign failed for $($v.Name)" }
}
& python (Join-Path $repo 'tools\diagnostics\analyze_i8_numeric_bisector.py') `
    --repo $repo `
    --left (Join-Path $Output 'results-guard_intrinsic\campaign.json') `
    --right (Join-Path $Output 'results-hybrid\campaign.json') `
    --output (Join-Path $Output 'analysis.json') --csv (Join-Path $Output 'summary.csv')
if ($LASTEXITCODE -ne 0) { throw 'Hybrid run evidence/provenance invalid' }
Write-Host "One-pass hybrid analysis at $Output\analysis.json"
