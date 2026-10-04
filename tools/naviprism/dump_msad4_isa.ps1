[CmdletBinding()]
param(
    [string]$BuildDirectory = "build/release",
    [string]$RgaPath = ".tools/rga/rga.exe",
    [string]$OutputDirectory = "artifacts/isa/naviprism"
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$buildPath = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $BuildDirectory))
$rga = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $RgaPath))
$outputPath = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $OutputDirectory))

if (-not (Test-Path -LiteralPath $rga -PathType Leaf)) {
    throw "AMD RGA not found at '$rga'. Pass -RgaPath with the installed rga.exe path."
}
if (-not (Test-Path -LiteralPath $buildPath -PathType Container)) {
    throw "Build directory not found at '$buildPath'. Build Release first."
}
New-Item -ItemType Directory -Force -Path $outputPath | Out-Null

$variants = @(
    @{ Name = "msad4"; Shader = "naviprism_msad4.dxil" },
    @{ Name = "scalar_u8"; Shader = "naviprism_msad4_scalar.dxil" },
    @{ Name = "fp16_difference_fp32_sum"; Shader = "naviprism_msad4_fp16.dxil" },
    @{ Name = "sarm_residual"; Shader = "naviprism_sarm_residual.dxil" },
    @{ Name = "thfa_4tap"; Shader = "naviprism_thfa_4tap.dxil" },
    @{ Name = "thfa_5tap"; Shader = "naviprism_thfa_5tap.dxil" },
    @{ Name = "thfa_8tap"; Shader = "naviprism_thfa_8tap.dxil" },
    @{ Name = "thfa_9tap"; Shader = "naviprism_thfa_9tap.dxil" },
    @{ Name = "thfa_descriptors"; Shader = "naviprism_thfa_descriptors.dxil" },
    @{ Name = "quality_router"; Shader = "naviprism_quality_router.dxil" }
    @{ Name = "phase_reservoir"; Shader = "naviprism_phase_reservoir.dxil" }
)

foreach ($variant in $variants) {
    $shaderPath = Join-Path $buildPath $variant.Shader
    if (-not (Test-Path -LiteralPath $shaderPath -PathType Leaf)) {
        throw "Compiled shader is missing: '$shaderPath'. Build the NaviPRISM variants first."
    }

    $isaPath = Join-Path $outputPath "$($variant.Name).isa.txt"
    $analysisPath = Join-Path $outputPath "$($variant.Name).analysis.txt"
    $binaryPath = Join-Path $outputPath "$($variant.Name).elf"
    $elfPath = Join-Path $outputPath "$($variant.Name).elf-dis.txt"
    Write-Host "Analyzing $($variant.Name) for gfx1010..."
    & $rga -s dx12 -c gfx1010 --cs-blob $shaderPath -b $binaryPath `
        --isa $isaPath -a $analysisPath --elf-dis $elfPath
    if ($LASTEXITCODE -ne 0) {
        throw "RGA failed for $($variant.Name) with exit code $LASTEXITCODE."
    }
    $isaPath = Join-Path $outputPath "gfx1010_$($variant.Name).isa_comp.txt"
    if (-not (Test-Path -LiteralPath $isaPath -PathType Leaf)) {
        throw "RGA completed but produced no ISA file for $($variant.Name)."
    }
    $instructionMatches = Select-String -LiteralPath $isaPath -Pattern '\bv_mqsad_[a-z0-9_]*_u8\b'
    if ($instructionMatches) {
        Write-Host "$($variant.Name): found native masked SAD instruction(s):"
        $instructionMatches | ForEach-Object { Write-Host "  $($_.Line.Trim())" }
    } else {
        Write-Host "$($variant.Name): no native masked SAD instruction found"
    }
}

Write-Host "RGA reports written under '$outputPath'."
