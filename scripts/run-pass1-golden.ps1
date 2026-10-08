param(
  [Parameter(Mandatory=$true)][string]$Repository,
  [Parameter(Mandatory=$true)][string]$Sequence,
  [string]$Stages = 'final,acc0_0,q0,acc1_0,q1lo,acc2_0',
  [switch]$AllStages,
  [int]$Samples = 128,
  [int]$Frame = 0,
  [string]$Output = ''
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$repo = (Resolve-Path -LiteralPath $Repository).Path
$sequence = (Resolve-Path -LiteralPath $Sequence).Path
if (-not $Output) { $Output = Join-Path $repo 'build\p1' }
$output = [IO.Path]::GetFullPath($Output)
New-Item -ItemType Directory -Force -Path $output | Out-Null

if ($AllStages) {
  $Stages = 'final,q0,q1lo,q1hi,acc0_0,acc0_1,acc0_2,acc0_3,' +
    'acc1_0,acc1_1,acc1_2,acc1_3,acc1_4,acc1_5,acc1_6,acc1_7,acc2_0,acc2_1,acc2_2,acc2_3'
}
$stageList = @($Stages.Split(',') | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne '' })
if ($stageList.Count -eq 0 -or ($stageList | Select-Object -Unique).Count -ne $stageList.Count) {
  throw 'Stages must be nonempty and unique'
}
$scriptEnv = Join-Path $repo 'scripts\BuildEnvironment.ps1'
. $scriptEnv
Initialize-Fsr4Navi10VsEnvironment
$python = (& py -3.11 -c "import sys, numpy; print(sys.executable)").Trim()
if ($LASTEXITCODE -ne 0 -or -not $python) {
  throw 'Pass1 CPU oracle requires Python 3.11 with NumPy available'
}
$source = Join-Path $repo 'third_party\fidelityfx-fsr4-source\Kits\FidelityFX\upscalers\fsr4\internal\shaders\fsr4_model_v07_i8_native\passes_1080.hlsl'

$reports = New-Object 'System.Collections.Generic.List[string]'
$steps = New-Object 'System.Collections.Generic.List[object]'
foreach ($stage in $stageList) {
  Write-Host "=== Pass1 independent oracle stage $stage ==="
  # Short paths are essential for pinned FidelityFX_SC include resolution.
  $stageId = $stage.Replace('_','')
  $buildI = Join-Path $output "bi$stageId"
  $buildS = Join-Path $output "bs$stageId"
  $campI = Join-Path $output "ci$stageId"
  $campS = Join-Path $output "cs$stageId"
  $failure = $null
  try {
    foreach ($arithmetic in @('intrinsic','scalar')) {
      $isScalar = $arithmetic -eq 'scalar'
      $build = if ($isScalar) { $buildS } else { $buildI }
      $scalarFlag = if ($isScalar) { 'ON' } else { 'OFF' }
      $cmArgs = @('-S', $repo, '-B', $build, '-G', 'Ninja',
        "-DPython3_EXECUTABLE:FILEPATH=$python",
        '-DFSR4N10_ENABLE_PASS_PREFIX_DIAGNOSTIC=ON',
        '-DFSR4N10_PASS11_BOUNDS_GUARD=ON',
        "-DFSR4N10_FORCE_SCALAR_DOT4=$scalarFlag",
        '-DFSR4N10_SCALAR_DOT4_PASS_SET=',
        '-DFSR4N10_STABLE_POST_MATH=OFF',
        "-DFSR4N10_PASS1_PROBE_STAGE=$(if ($stage -eq 'final') { '' } else { $stage })")
      & cmake @cmArgs
      if ($LASTEXITCODE -ne 0) { throw "CMake configure failed: $arithmetic/$stage" }
      & cmake --build $build --config Release
      if ($LASTEXITCODE -ne 0) { throw "Build failed: $arithmetic/$stage" }
      $harness = Join-Path $build 'fsr4n10_harness.exe'
      $camp = if ($isScalar) { $campS } else { $campI }
    & $python (Join-Path $repo 'tools\diagnostics\run_i8_numeric_bisector.py') `
        --harness $harness --sequence $sequence --output $camp `
        --variant "$stage-$arithmetic" --arithmetic $arithmetic `
        --stages 0 1 --seeds zero --repeats 2 --trace-frame $Frame
      if ($LASTEXITCODE -ne 0) { throw "GPU scratch campaign failed: $arithmetic/$stage" }
    }
    $report = Join-Path $output "oracle-$stage.json"
    & $python (Join-Path $repo 'tools\diagnostics\pass1_golden.py') `
      --source $source --scalar-campaign (Join-Path $campS 'campaign.json') `
      --intrinsic-campaign (Join-Path $campI 'campaign.json') `
      --stage $stage --samples $Samples --output $report
    if (-not (Test-Path -LiteralPath $report)) { throw "Missing CPU oracle report: $stage" }
    $reports.Add($report)
    if ($LASTEXITCODE -ne 0) { Write-Warning "Oracle stage $stage is unresolved; retaining its report" }
  } catch {
    $failure = [string]$_
  }
  $steps.Add(@{ Stage=$stage; Passed=($null -eq $failure); Error=$failure })
  if ($null -ne $failure) { Write-Warning "$stage : $failure" }
}

# The same compiled shader now tests the EXACT scalar fallback macro, not only
# a separate branch-safe scalar reference.
$dot4Report = Join-Path $output 'dot4-three-way.json'
if ($stageList.Count -gt 0) {
  $dot4Build = Join-Path $output ('bi' + $stageList[0].Replace('_',''))
  $harness = Join-Path $dot4Build 'fsr4n10_harness.exe'
  if (Test-Path -LiteralPath $harness) {
    & $harness --run-dot4-conformance $dot4Report
    if ($LASTEXITCODE -ne 0) { Write-Warning 'DOT4 three-way conformance failed; inspect report' }
  }
}
$validReports = @($reports | Where-Object { Test-Path -LiteralPath $_ })
if ($validReports.Count -gt 0) {
  $summaryArgs = @('--reports') + @($validReports) + @('--output', (Join-Path $output 'summary.json'))
  & $python (Join-Path $repo 'tools\diagnostics\summarize_pass1_golden.py') @summaryArgs
  if ($LASTEXITCODE -ne 0) { Write-Warning 'Summary tool returned an error' }
}
$stepFile = Join-Path $output 'step_results.json'
@{ schema='f4n10.pass1-golden-runner.v1'; BaseCommit='98657b4'; Steps=@($steps);
   ProductionApproved=$false } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $stepFile -Encoding UTF8
Write-Host "Independent Pass1 evidence is in $output"
if (@($steps | Where-Object { -not $_.Passed }).Count -gt 0) {
  throw 'One or more Pass1 diagnostic stages failed; inspect step_results.json'
}
