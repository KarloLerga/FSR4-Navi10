param(
    [Parameter(Mandatory=$true)] [string] $Repository,
    [Parameter(Mandatory=$true)] [string] $Sequence,
    [string] $Output = ""
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$repo = (Resolve-Path -LiteralPath $Repository).Path
$seq = (Resolve-Path -LiteralPath $Sequence).Path
if (-not $Output) { $Output = Join-Path $repo 'build\guarded-o0' }
New-Item -ItemType Directory -Path $Output -Force | Out-Null
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
        '-DFSR4N10_ENABLE_PASS_PREFIX_DIAGNOSTIC=OFF' `
        '-DFSR4N10_FORCE_GLOBAL_UAV_BARRIER=OFF' `
        "-DFSR4N10_FORCE_SCALAR_DOT4=$($v.Scalar)" `
        '-DFSR4N10_SCALAR_DOT4_PASS_SET='
    if ($LASTEXITCODE -ne 0) { throw "Configure failed: $($v.Name)" }
    & cmake --build $build --config Release --target fsr4n10_harness
    if ($LASTEXITCODE -ne 0) { throw "Build failed: $($v.Name)" }
}
$failures = 0
foreach ($v in $variants) {
    $build = Join-Path $Output ('build-' + $v.Name)
    $exe = Join-Path $build 'fsr4n10_harness.exe'
    if (-not (Test-Path -LiteralPath $exe)) { $exe = Join-Path $build 'Release\fsr4n10_harness.exe' }
    & python (Join-Path $repo 'tools\diagnostics\run_guarded_o0.py') `
        --repo $repo --harness $exe --sequence $seq `
        --output (Join-Path $Output ('audit-' + $v.Name)) --arithmetic $v.Arithmetic
    if ($LASTEXITCODE -ne 0) {
        $failures++
        Write-Warning "O0 STILL BLOCKED for $($v.Name); audit report saved"
    }
}
Write-Host "Audits: $Output"
if ($failures -gt 0) { throw "O0 gate remains closed in $failures variants. Inspect both audit summaries." }
