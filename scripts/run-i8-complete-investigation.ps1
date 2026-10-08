param(
    [Parameter(Mandatory=$true)] [string] $Repository,
    [Parameter(Mandatory=$true)] [string] $Sequence,
    [string] $Output = "",
    [int] $Repeats = 2,
    [int] $TraceFrame = 0
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$repo = (Resolve-Path -LiteralPath $Repository).Path
$seq = (Resolve-Path -LiteralPath $Sequence).Path
if (-not $Output) { $Output = Join-Path $repo 'build\i8diag' }
New-Item -Path $Output -ItemType Directory -Force | Out-Null
$numeric = Join-Path $Output 'numeric-bisector'
$hybrid = Join-Path $Output 'hybrid'
$o0 = Join-Path $Output 'guarded-o0'
$phases = @()
$measuredPass = $null
try {
    & (Join-Path $repo 'scripts\run-i8-numeric-bisector.ps1') `
      -Repository $repo -Sequence $seq -Output $numeric `
      -Repeats $Repeats -TraceFrame $TraceFrame
    $phases += @{Phase='numeric-bisector'; Passed=$true}
} catch {
    $phases += @{Phase='numeric-bisector'; Passed=$false; Error=[string]$_}
}
$analysisPath = Join-Path $numeric 'analysis.json'
if (Test-Path -LiteralPath $analysisPath) {
    $analysis = Get-Content -LiteralPath $analysisPath -Raw | ConvertFrom-Json
    if ($analysis.same_inputs -eq $true -and $analysis.within_mode_repeatable -eq $true `
        -and $null -ne $analysis.first_valid_output_pass) {
        $measuredPass = [int]$analysis.first_valid_output_pass
        if ($measuredPass -ge 1 -and $measuredPass -le 12) {
            try {
                & (Join-Path $repo 'scripts\run-i8-hybrid-probe.ps1') `
                  -Repository $repo -Sequence $seq -Pass $measuredPass `
                  -Output $hybrid -Repeats $Repeats -TraceFrame $TraceFrame
                $phases += @{Phase='one-pass-hybrid'; Passed=$true; Pass=$measuredPass}
            } catch {
                $phases += @{Phase='one-pass-hybrid'; Passed=$false; Pass=$measuredPass; Error=[string]$_}
            }
        }
    }
}
if ($null -eq $measuredPass) {
    $phases += @{Phase='one-pass-hybrid'; Passed=$false; Error='No verified first output divergence; no guessed pass substitution performed'}
}
try {
    & (Join-Path $repo 'scripts\run-guarded-o0.ps1') `
      -Repository $repo -Sequence $seq -Output $o0
    $phases += @{Phase='original-o0-oracles'; Passed=$true}
} catch {
    $phases += @{Phase='original-o0-oracles'; Passed=$false; Error=[string]$_}
}
$success = @($phases | Where-Object { $_.Passed -eq $false }).Count -eq 0
$result = [ordered]@{
    Schema = 'f4n10.i8-complete-investigation.v1'
    Repository = $repo
    Sequence = $seq
    NumericAnalysis = $analysisPath
    FirstMeasuredDifferentPass = $measuredPass
    AllPhasesPassed = $success
    ProductionOrGameQualityProven = $false
    Phases = $phases
}
$result | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $Output 'summary.json') -Encoding UTF8
Write-Host "All collected reports: $Output"
if (-not $success) { throw 'Investigation contains failing/blocked gates; see summary.json. This is NOT an approval for game use.' }
