# Build and bootstrap contract

## Intended user experience
The user should be able to unzip the handoff pack, open the folder in VS Code, give Codex local terminal/network access, paste the start prompt, and approve UAC when Windows requires it. Everything else that can be automated should be automated.

## Required tools
- Windows 11 x64
- Git
- Visual Studio 2022 Build Tools with MSVC x64/x86 C++ workload and a recent Windows 10/11 SDK
- CMake
- Ninja
- Python 3.x
- DirectX Shader Compiler (DXC)
- Radeon GPU Analyzer CLI if available
- Radeon Developer Tool Suite/RGP for final profiling if available

## Bootstrap behavior
`scripts/bootstrap.ps1` must:
1. Validate Windows/x64.
2. Elevate itself only if required for package installation.
3. Install missing common tools through winget.
4. Install VS Build Tools with the C++ workload non-interactively where possible.
5. Refresh PATH.
6. Locate `vswhere.exe`, `VsDevCmd.bat`, MSVC, Windows SDK and DXC.
7. Download/extract official Radeon tools when possible; absence of RGP GUI must not block compilation.
8. Call `fetch-upstreams.ps1`.
9. Call `verify-environment.ps1`.
10. Save machine-readable state under `.state/`.

If an installer requires reboot, finish all possible work first and write `.state/REBOOT_REQUIRED.txt` containing the exact command to resume. Do not pretend the run can bypass a mandatory reboot.

## Build layout
Use out-of-tree builds:
- `build/debug`
- `build/release`
- `build/generated-shaders`
- `generated/model`
- `artifacts/results`
- `release/`

Prefer CMake + Ninja for deterministic command-line builds. Use MSVC toolchain.

## Root targets
The final CMake project should expose at least:
- `fsr4n10_core`
- `fsr4n10_harness`
- `fsr4n10_ffxapi`
- `generate_model_pack`
- `generate_shaders`
- `compile_shaders`
- `validate_reference`
- `validate_fp16`
- `benchmark_backends`
- `package_release`

Where custom targets make more sense than native CMake targets, wrap them consistently.

## Reproducible commands
The final repo must support roughly:

```powershell
./scripts/bootstrap.ps1
./scripts/configure.ps1 -Configuration Release
./scripts/build.ps1 -Configuration Release
./scripts/validate.ps1 -Configuration Release
./scripts/benchmark.ps1 -Configuration Release
./scripts/package.ps1
```

Codex may refine exact CLI, but keep it one-command per operation and document it.
