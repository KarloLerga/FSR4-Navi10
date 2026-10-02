function Import-Fsr4Navi10ToolPath {
    $machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    $segments = @($machinePath, $userPath, $env:Path) -join ';' -split ';'
    $unique = @()
    foreach ($segment in $segments) {
        if ($segment -and $unique -notcontains $segment) {
            $unique += $segment
        }
    }
    $env:Path = $unique -join ';'
}

function Initialize-Fsr4Navi10VsEnvironment {
    Import-Fsr4Navi10ToolPath

    $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
    if (-not (Test-Path -LiteralPath $vswhere)) {
        throw 'vswhere.exe was not found; Visual Studio C++ tools are required.'
    }

    $installPath = (& $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath).Trim()
    if (-not $installPath) {
        throw 'No Visual Studio installation with the x64/x86 C++ tools was found.'
    }

    $devCmd = Join-Path $installPath 'Common7\Tools\VsDevCmd.bat'
    if (-not (Test-Path -LiteralPath $devCmd)) {
        throw "VsDevCmd.bat was not found: $devCmd"
    }

    $command = 'call "' + $devCmd + '" -arch=x64 -host_arch=x64 >nul && set'
    $environment = & $env:ComSpec /d /c $command
    if ($LASTEXITCODE -ne 0) {
        throw "VsDevCmd.bat failed with exit code $LASTEXITCODE."
    }

    foreach ($entry in $environment) {
        $separator = $entry.IndexOf('=')
        if ($separator -gt 0) {
            $name = $entry.Substring(0, $separator)
            $value = $entry.Substring($separator + 1)
            [Environment]::SetEnvironmentVariable($name, $value, 'Process')
        }
    }

    if (-not (Get-Command cl.exe -ErrorAction SilentlyContinue)) {
        throw 'The Visual Studio environment loaded, but cl.exe is still unavailable.'
    }
}
