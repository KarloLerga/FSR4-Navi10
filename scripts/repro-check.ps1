[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$SourceRoot = Join-Path $RepoRoot "third_party\fidelityfx-fsr4-source\Kits\FidelityFX\upscalers\fsr4"
$LockPath = Join-Path $RepoRoot "third_party\LOCK.json"
$ConverterPath = Join-Path $RepoRoot "tools\model\extract_fp16_weights.py"
$PackBuilderPath = Join-Path $RepoRoot "tools\model\build_model_packs.py"
$ContractExtractorPath = Join-Path $RepoRoot "tools\model\extract_pass_contracts.py"
$PythonCommand = Get-Command python -ErrorAction Stop

foreach ($RequiredPath in @($SourceRoot, $LockPath, $ConverterPath, $PackBuilderPath, $ContractExtractorPath)) {
    if (-not (Test-Path -LiteralPath $RequiredPath)) {
        throw "Required input is missing: $RequiredPath. Run scripts/fetch-upstreams.ps1 first."
    }
}

$VersionText = (& $PythonCommand.Source --version 2>&1 | Out-String).Trim()
if ($VersionText -notmatch "^Python 3\.(1[1-9]|[2-9][0-9])\.") {
    throw "Python 3.11 or newer is required; found '$VersionText'."
}

$RunRoot = Join-Path $RepoRoot ("build\repro-check\" + [guid]::NewGuid().ToString("N"))
$FirstOutput = Join-Path $RunRoot "first"
$SecondOutput = Join-Path $RunRoot "second"
New-Item -ItemType Directory -Path $FirstOutput -Force | Out-Null
New-Item -ItemType Directory -Path $SecondOutput -Force | Out-Null

foreach ($OutputPath in @($FirstOutput, $SecondOutput)) {
    & $PythonCommand.Source $ConverterPath `
        --fsr4-root $SourceRoot `
        --lock $LockPath `
        --output $OutputPath `
        --preset all `
        --tier all
    if ($LASTEXITCODE -ne 0) {
        throw "Parameter conversion failed with exit code $LASTEXITCODE."
    }
    & $PythonCommand.Source $PackBuilderPath --index (Join-Path $OutputPath "index.json")
    if ($LASTEXITCODE -ne 0) {
        throw "Model-pack generation failed with exit code $LASTEXITCODE."
    }
    & $PythonCommand.Source $ContractExtractorPath `
        --source-root (Join-Path $RepoRoot "third_party\fidelityfx-fsr4-source") `
        --fsr4-root $SourceRoot `
        --lock $LockPath `
        --output (Join-Path $OutputPath "i8_pass_contracts.json")
    if ($LASTEXITCODE -ne 0) {
        throw "Pass-contract extraction failed with exit code $LASTEXITCODE."
    }
}

function Get-OutputHashes([string]$Root) {
    $Hashes = @{}
    foreach ($File in Get-ChildItem -LiteralPath $Root -File -Recurse) {
        $RelativePath = $File.FullName.Substring($Root.Length).TrimStart('\', '/') -replace '\\', '/'
        $Hashes[$RelativePath] = (Get-FileHash -LiteralPath $File.FullName -Algorithm SHA256).Hash
    }
    return $Hashes
}

$FirstHashes = Get-OutputHashes $FirstOutput
$SecondHashes = Get-OutputHashes $SecondOutput
$FirstNames = @($FirstHashes.Keys | Sort-Object)
$SecondNames = @($SecondHashes.Keys | Sort-Object)
if (Compare-Object -ReferenceObject $FirstNames -DifferenceObject $SecondNames) {
    throw "The two conversions produced different file lists. Outputs are under $RunRoot"
}

$Differences = @(
    foreach ($Name in $FirstNames) {
        if ($FirstHashes[$Name] -ne $SecondHashes[$Name]) {
            [pscustomobject]@{ File = $Name; First = $FirstHashes[$Name]; Second = $SecondHashes[$Name] }
        }
    }
)
if ($Differences.Count -gt 0) {
    $Differences | Format-Table -AutoSize | Out-String | Write-Error
    throw "The two conversions differ. Outputs are under $RunRoot"
}

Write-Output "Reproducible parameter packs and pass contracts verified for $($FirstNames.Count) files."
Write-Output "Outputs: $RunRoot"
