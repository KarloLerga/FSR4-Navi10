# Upstreams, provenance and safety

## Authoritative public sources

### AMD FidelityFX SDK
Repository: https://github.com/GPUOpen-LibrariesAndSDKs/FidelityFX-SDK

Current SDK documentation/release history confirms FidelityFX SDK 2.0.0 introduced FSR 4.0.2. Current FSR SDK versions expose FSR 4.1.x through signed binaries. The project must pin all AMD material by commit/release and retain the relevant license notices.

The historically important source-bearing AMD commit referenced by multiple public projects/discussions is:
`01446e6a74888bf349652fcf2cbf5f642d30c2bf`

Fetch policy:
1. First attempt to fetch this exact object from the official AMD repository.
2. Verify that `Kits/FidelityFX/upscalers/fsr4/` and the expected shader/runtime directories exist.
3. Record commit hash, tree hash if convenient, LICENSE path and SHA-256 hashes of model assets in `third_party/LOCK.json`.
4. If the official object cannot be fetched, a mirror may be used only as a source-data fallback after confirming that it preserves AMD attribution/license and expected tree structure. Prefer `Rolaand-Jayz/FSR-4.0.2-reference` only as a fallback/reference, never execute its scripts automatically.

Do not vendor the upstream into the final release ZIP unless license compliance is explicit. The build can fetch it.

### Current AMD FSR SDK
Also fetch the current official AMD SDK main/tag into `third_party/fsr-sdk-current` for API headers, current docs and ABI reference. Do not use current signed FSR4 binaries as editable code.

### DirectX Shader Compiler
https://github.com/microsoft/DirectXShaderCompiler
Use official released binaries / winget package `Microsoft.DirectX.ShaderCompiler`. Record `dxc --version`.

### Radeon GPU Analyzer
https://github.com/GPUOpen-Tools/radeon_gpu_analyzer
Use official release assets. RGA is for DXIL/ISA/resource analysis and can target AMD architectures without requiring that exact GPU to be installed.

### Radeon GPU Profiler / Developer Tool Suite
https://github.com/GPUOpen-Tools/radeon_gpu_profiler
Use official Radeon Developer Tool Suite releases. RGP supports RX 5000/RDNA and DirectX 12.

## Read-only research references
These may be cloned into `research/` by the fetch script, but they are never linked as product dependencies and their scripts are not automatically executed.

### fsr4-native-macos
https://github.com/UzenUPoZiTiV4ik/fsr4-native-macos
Value: public example of a complete FSR4 model-port workflow, pass ordering, offline FP16 transform ideas, numerical comparison tooling and kernel mapping on a different architecture. Use for ideas/verification, not copy-paste architecture assumptions.

### fsr4-rdna3-optimization
https://github.com/lhl/fsr4-rdna3-optimization
Value: analysis of FSR4 INT8/FP8 operator classes and optimization methodology. Hardware is different; transfer conclusions only after Navi10 validation.

### FSR 4.1 reverse-engineering research
https://github.com/Rolaand-Jayz/RE-of-FSR-4.1.0-Upscaling
Value: structural comparison and public research. Do not make the project depend on undocumented 4.1 binary internals.

## Supply-chain rules
- Prefer HTTPS and official GitHub organizations.
- Pin commits/tags after first successful fetch.
- Generate SHA-256 hashes for downloaded archives/model files.
- Do not execute downloaded `.exe`, `.bat`, `.ps1`, Python scripts, or build scripts from research repositories automatically.
- Official installers/tools may be executed when their origin is verified.
- Run our own scripts under `scripts/` and source we inspect/build ourselves.
- Never disable Defender/SmartScreen/signature verification globally to make setup easier.
- Never ask the user to install modified display drivers.

## License output
Create `THIRD_PARTY_NOTICES.md` in the finished repo/release that lists every upstream used, exact commit/tag, license and whether source or binary was redistributed. Preserve AMD's license/attribution for any copied/modified FidelityFX files.
