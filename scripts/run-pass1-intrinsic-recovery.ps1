param(
    [Parameter(Mandatory=$true)][string]$Repository,
    [Parameter(Mandatory=$true)][string]$Sequence,
    [string]$Output = '',
    [int]$Samples = 128,
    [int]$Repeats = 2,
    [int]$Frame = 0,
    [string[]]$Variants = @('native','native_zero','native_swap','native_swap_zero','unpack_dot','unpack_scalar','unsigned_bias_3dot')
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$repo = (Resolve-Path -LiteralPath $Repository).Path
$seq = (Resolve-Path -LiteralPath $Sequence).Path
if (-not $Output) { $Output = Join-Path $repo 'build\p1fix' }
$output = [IO.Path]::GetFullPath($Output)
. (Join-Path $repo 'scripts\BuildEnvironment.ps1')
Initialize-Fsr4Navi10VsEnvironment
$python = (& py -3.11 -c 'import sys, numpy; print(sys.executable)').Trim()
if ($LASTEXITCODE -ne 0 -or -not $python) {
    throw 'Python 3.11 with NumPy is required for the independent oracle'
}
Remove-Item Env:\MLSR-WMMA -ErrorAction SilentlyContinue
Remove-Item Env:\MLSR-WATERMARK -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $output | Out-Null
& $python (Join-Path $repo 'tools\diagnostics\run_pass1_intrinsic_recovery.py') `
    --repo $repo --sequence $seq --output $output `
    --samples $Samples --repeats $Repeats --frame $Frame --variants @Variants
if ($LASTEXITCODE -ne 0) {
    throw "Unresolved Pass1 lowering or failing evidence; inspect $output\summary.json"
}
Write-Host "Measured successful candidate(s) are recorded in $output\summary.json"
Write-Host 'No production defaults, third_party files or Git branches were changed.'
