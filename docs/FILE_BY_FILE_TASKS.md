# File-by-file task map for Codex

This is a concrete checklist of files/subsystems to create. If actual implementation requires additional files, add them; do not omit responsibilities below.

## Root
- `CMakeLists.txt` — project, options, subdirs, generated targets.
- `README.md` — build/run/architecture summary.
- `PROGRESS.md` — living state.
- `DECISIONS_LOG.md` — deviations/new evidence decisions.
- `RESULTS.md` — measured final results.
- `THIRD_PARTY_NOTICES.md` — license/provenance.

## CMake
- `cmake/FindDXC.cmake`
- `cmake/FindRGA.cmake`
- `cmake/CompilerWarnings.cmake`
- `cmake/ShaderBuild.cmake`
- generated-file dependencies so changing model/generator rebuilds appropriate shaders.

## Public include
- `include/fsr4n10/api.h`
- `include/fsr4n10/types.h`
- `include/fsr4n10/version.h`

## Core
- `src/core/context.*`
- `src/core/device_caps.*`
- `src/core/dx12_helpers.*`
- `src/core/resource_allocator.*`
- `src/core/descriptor_allocator.*`
- `src/core/upload_ring.*`
- `src/core/model_manifest.*`
- `src/core/model_pack.*`
- `src/core/shader_pack.*`
- `src/core/pipeline_cache.*`
- `src/core/scheduler.*`
- `src/core/timestamps.*`
- `src/core/logging.*`
- `src/core/dred.*`

## Backends
- common backend interface/registry
- reference_i8 backend
- fp16_compat backend
- fp16_high_precision backend
- hybrid_auto backend
- tuning cache reader/writer

## Harness
- DX12 setup
- testcase generator/loader
- reference runner
- compare/dump support
- benchmark support
- JSON/CSV output
- adapter smoketest

## FSR API adapter
- DLL exports `.def` or explicit exports
- public AMD API headers isolated under upstream include path
- descriptor conversion
- query conversion
- error mapping

## Model tools
- upstream inventory/hash tool
- manifest extractor
- exact dequant/half converter
- pack writer/reader validator
- layout prepacker

## Shader tools
- operator IR
- HLSL emitter
- compiler wrapper
- DXIL manifest/packer
- RGA analyzer/parser

## Quality tools
- raw tensor reader
- metrics
- temporal stress generator
- diff image/report generator

## Scripts
Codex must complete/add:
- `scripts/validate.ps1`
- `scripts/benchmark.ps1`
- `scripts/package.ps1`
- `scripts/repro-check.ps1`
- optional `scripts/clean.ps1`

## Tests
- model pack bounds/hash tests
- half conversion tests
- quantization formula tests
- resource lifetime planner tests
- manifest parser tests
- adapter query/create/destroy tests
- deterministic synthetic sequence integration test
