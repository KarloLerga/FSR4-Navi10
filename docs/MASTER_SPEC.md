# MASTER SPECIFICATION — FSR4-Navi10

## 0. Purpose

Build a complete DirectX 12 implementation of AMD FSR 4.0.2 targeted specifically at Radeon RX 5700 XT / Navi10 / gfx1010. Preserve the full FSR4 implementation as the correctness reference, quality teacher, and dense safety fallback. In parallel, add the separately named NaviQSR network family described in `docs/naviqsr/`; it may become a production candidate only after temporal quality, stability, and measured Navi10 break-even gates pass.

This is not a project to create a generic AI upscaler, not a project to improve FSR3, and not a project to inject game-specific shaders. The NaviQSR path is a project-specific research network trained against FSR4 and temporal ground truth; it must never be mislabeled as AMD FSR4. The goal remains the best measured image-quality/performance result on RX 5700 XT.

## 1. Required documents
Before implementing a subsystem, read the relevant documents:
- `docs/DECISIONS.md` — fixed architectural decisions.
- `docs/UPSTREAMS_AND_LICENSE.md` — allowed upstream acquisition/provenance.
- `docs/BUILD_AND_BOOTSTRAP.md` — setup/build rules.
- `docs/MODEL_PIPELINE.md` — model extraction, conversion, packing and shader generation.
- `docs/NAVI10_BACKEND.md` — shader/runtime optimization design.
- `docs/NUMERICS_AND_QUALITY.md` — correctness and quality preservation.
- `docs/ACCEPTANCE_CRITERIA.md` — exact completion gates.
- `docs/CODE_REVIEW_CHECKLIST.md` — mandatory final correctness/performance review.
- `docs/FAILURE_MODES.md` — recovery behavior; do not stop prematurely.

## 2. User-facing goal
The user should end with a release folder that can run the optimized FSR4 path on the local RX 5700 XT in a standalone DX12 harness and expose an FSR API-compatible adapter for later game integration work.

The release must be self-describing and contain:
- `fsr4n10_harness.exe`
- `fsr4n10_core.dll` (or static core if architecturally better, but the harness/adapter must share one implementation)
- `fsr4n10_ffxapi.dll`
- optimized DXIL shader pack(s)
- generated FP16 model pack(s)
- config/default profile
- `README.md`
- `RESULTS.md`
- `THIRD_PARTY_NOTICES.md`
- build metadata (git revision, DXC version, upstream commit hashes, driver/GPU information)

## 3. Non-goals for this run
Do NOT spend time on:
- KCD2/Witcher-specific integration
- OptiScaler integration
- frame generation
- Radeon driver/VBIOS modification
- Vulkan
- Linux
- macOS
- GUI configuration application
- generic support for every Radeon architecture
- unrelated generic upscalers or game-specific injection

The 2026-10-02 user-supplied QSSR addendum supersedes only the two earlier non-goals about training and topology reduction. It does not remove the full-FSR4 path or relax the quality, licensing, and measurement rules below. See `docs/naviqsr/README_QSSR_ADDENDUM.md` and `DECISIONS_LOG.md`.

## 4. Architecture overview

The final architecture consists of six layers:

### 4.1 Upstream reference layer
A pinned local copy of the source-bearing FSR 4.0.2 FidelityFX tree. Keep it unmodified under `third_party/` whenever practical. If changes are needed for buildability, create a patch series under `patches/upstream-reference/` rather than editing provenance invisibly.

### 4.2 Model extraction/conversion layer
A deterministic toolchain that reads the upstream FSR4 model/shader assets and emits:
- canonical model manifest
- original asset hashes
- FP16-converted weights
- optional quantization metadata required by compat mode
- prepacked/tiled variants for Navi10 shaders
- C/C++ metadata headers
- generated HLSL shader sources or compile definitions

### 4.3 Core DX12 runtime
Owns:
- D3D12 device feature discovery
- per-context persistent resources/history
- descriptor heaps
- upload/constant buffers
- PSOs/root signatures
- dispatch scheduling
- resource barriers
- GPU timestamp queries
- backend selection
- debug/intermediate capture

### 4.4 Neural backend families
All backends implement the exact same logical model contract:
- `reference_i8` — faithful source/reference path used for correctness and baseline timing.
- `fp16_compat` — complete FP16 arithmetic path preserving important original quantization semantics.
- `fp16_high_precision` — complete FP16 path with unnecessary quant/dequant round trips removed only after compatibility is established.
- `hybrid_auto` — production selector using the fastest validated shader implementation for each pass on this exact GPU.

Full FP16 implementations MUST exist even if `hybrid_auto` selects some INT8 passes.

### 4.5 Standalone harness
Creates a DX12 device and runs deterministic multi-frame sequences through all backends. It supports reference comparison, intermediate dumps, image output and performance runs without requiring any game.

### 4.6 FSR API compatibility adapter
Exports the FSR API-compatible surface needed for later integration, translating FSR API context/query/dispatch descriptors into the core runtime. It must remain separate from AMD signed DLLs and clearly identify itself as an experimental unsigned project build.

## 5. Repository layout to converge toward

```text
/
  AGENTS.md
  CMakeLists.txt
  README.md
  PROGRESS.md
  DECISIONS_LOG.md
  RESULTS.md
  THIRD_PARTY_NOTICES.md
  .agent/
    PLANS.md
    EXEC_PLAN.md
  cmake/
  config/
  docs/
  include/fsr4n10/
    api.h
    backend.h
    context.h
    model.h
    telemetry.h
    version.h
  src/
    core/
      context.cpp
      device_caps.cpp
      descriptors.cpp
      resources.cpp
      scheduler.cpp
      timestamps.cpp
      model_pack.cpp
      pipeline_cache.cpp
      backend_registry.cpp
    backends/
      reference_i8/
      fp16_compat/
      fp16_high_precision/
      hybrid_auto/
    ffxapi/
      exports.cpp
      context_adapter.cpp
      query_adapter.cpp
      resource_adapter.cpp
    harness/
      main.cpp
      dx12_app.cpp
      testcase.cpp
      compare.cpp
      image_io.cpp
      benchmark.cpp
  shaders/
    common/
    reference/
    generated/
    runtime/
  tools/
    model/
      extract_manifest.py
      convert_weights.py
      prepack_weights.py
      validate_pack.py
    shaders/
      generate_hlsl.py
      compile_hlsl.py
      analyze_isa.py
    quality/
      compare_frames.py
      temporal_metrics.py
    package/
  third_party/
  research/
  generated/
    model/
    shaders/
    manifests/
  artifacts/
    captures/
    diffs/
    isa/
    results/
  scripts/
```

Codex may adjust file names but not collapse these responsibilities into an unmaintainable monolith.

## 6. Upstream acquisition and source truth

### 6.1 Fetch strategy
Run `scripts/fetch-upstreams.ps1`. Attempt to fetch exact AMD FidelityFX object `01446e6a74888bf349652fcf2cbf5f642d30c2bf` first. Confirm FSR4 directories exist. If the official object is inaccessible, use an allowed mirror only as documented in `UPSTREAMS_AND_LICENSE.md`, retaining exact provenance.

### 6.2 Never invent model constants
Tensor dimensions, weight offsets, pass names, dispatch dimensions, scale factors, exact quantization formulas, constant-buffer fields and shader bindings must come from fetched source, generated headers or verified provider behavior. If this master spec describes an expected structure and upstream differs, upstream wins; record the difference in `DECISIONS_LOG.md`.

### 6.3 Current 4.1 reference
Clone current official SDK for API headers/docs and compare public 4.1 docs. Do not make runtime depend on reverse-engineered signed-binary implementation details.

## 7. Toolchain and compiler

### 7.1 C++
- C++20 minimum.
- MSVC on Windows.
- Warnings high; project code warnings treated as errors in CI/local validation, excluding untouched upstream.
- RAII for COM and resources (`Microsoft::WRL::ComPtr` or equivalent).
- No exceptions across public DLL ABI.
- Explicit HRESULT/error propagation plus structured logging.

### 7.2 HLSL
Production FP16 compute shader baseline flags:
```text
-T cs_6_6
-HV 2021
-O3
-enable-16bit-types
```
Add `-Zi/-Qembed_debug` only for development profiling variants. Do not ship debug-heavy DXIL as the default release pack.

Use real `float16_t`, `int16_t`, etc. where true 16-bit behavior is required; do not assume legacy `min16float` gives the same storage/arithmetic guarantees.

### 7.3 Shader permutations
Do not compile a combinatorial explosion blindly. Enumerate the real permutations required by upstream model presets/resolution tiers/input flags. Generate a machine-readable shader manifest containing:
- logical pass
- preset
- output-resolution tier
- compile defines
- wave size
- backend
- DXIL SHA-256
- compiler version
- resource binding signature
- optional RGA statistics

## 8. Device capability discovery

At runtime record:
- adapter LUID/name/vendor/device ID
- dedicated VRAM
- driver version if available
- D3D feature level
- shader model supported
- wave lane min/max
- native 16-bit shader ops support
- enhanced barriers support (if used)
- relevant resource binding tier

Refuse optimized path if requirements are not met and emit a clear diagnostic. For the target machine, verify that the adapter is RX 5700 XT/Navi10/gfx1010 as best as can be established from PCI ID/name/tooling.

Do not use architecture-name folklore as proof of instruction selection. Generated ISA and measured pass timing are authoritative.

## 9. FSR4 logical pipeline fidelity

The reference implementation must mirror the upstream provider's frame semantics exactly:
- persistent history across frames
- reset handling
- jitter convention
- motion vector scaling and optional low-resolution MV handling
- depth inversion convention
- exposure/pre-exposure state
- reactive/transparency inputs if present in the upstream contract
- render and display sizes
- alignment requirements
- RCAS behavior
- optional auto-exposure/SPD behavior

Expected public reference implementations describe `SPD (optional) -> pre -> model passes -> post -> RCAS (optional)`. Confirm exact source behavior before implementation.

All optimized backends must consume/produce the same logical resources as the reference path.

## 10. Model conversion strategy

Detailed in `MODEL_PIPELINE.md`; required principles:

### 10.1 Canonical manifest
Create one canonical JSON/binary manifest generated from upstream assets. It must describe every tensor/weight/scale/bias needed by each preset and resolution tier. Never maintain a hand-copied table as the only source of truth.

### 10.2 Preserve original assets
Never destructively rewrite original initializers. Generated FP16 packs are new files with a header containing:
- magic/version
- source model identifier
- source asset SHA-256
- conversion-tool version/git hash
- preset/tier
- tensor count
- offset/size/alignment per tensor
- data type/layout
- optional scale/zero-point metadata

### 10.3 Offline dequantization
Where original weights are INT8 or FP8, convert to FP16 offline so production shaders do not pay weight decode/dequant cost every frame unless a hybrid path specifically proves compressed storage faster.

Conversion must reproduce the exact upstream dequant formula. Add unit tests using known sample tensors comparing host conversion to upstream shader/reference math.

### 10.4 Multiple pack layouts
Generate at least:
- canonical contiguous FP16 pack
- channel-blocked/vectorized pack suitable for `half2`/`float16_t2` access
- any per-operator transposed/pre-swizzled pack shown to reduce address math or improve coalescing

Do not duplicate every tensor unnecessarily; emit only layouts actually consumed by compiled production variants.

## 11. Full FP16 backend design

The complete neural network must execute without `dot4add_i8packed` in the FP16 backends.

### 11.1 Arithmetic
Use FP16 operands and FP16/FP32 accumulation based on each operator's numerical needs:
- start with FP32 accumulation where reference error is sensitive
- allow FP16 accumulation only after quality gates pass and it materially improves end-to-end time
- exploit packed FP16/vector operations through natural HLSL vectorization and true 16-bit types

Do not rely on unsupported WMMA/wave-matrix features on Navi10.

### 11.2 Compatibility semantics
For `fp16_compat`, preserve original per-layer quantization/clamp/saturation boundaries logically. It is acceptable to implement the quantization operation mathematically in FP16/FP32 rather than physically storing INT8 if that avoids memory traffic while producing the same subsequent values within tolerance.

This is important: compatibility does not require writing an INT8 scratch tensor if the next operator can consume the equivalent quantized value in registers/LDS. Fuse the semantic boundary, not necessarily the physical storage.

### 11.3 High precision semantics
After `fp16_compat` passes, `fp16_high_precision` may carry FP16 values across boundaries where the original model quantizes and immediately dequantizes. Retain all clamps/nonlinearities needed for stable behavior. Compare temporally over long sequences, not just one frame.

## 12. Operator specialization

Do not implement a generic runtime operator loop as the final fast path. Implement/generate specialized kernels for each model pass/operator graph.

For each fused block:
- constants known at build time become compile-time constants
- channel counts and kernel sizes are fixed
- loops with small fixed trip counts may be unrolled only when instruction size/VGPR pressure remains beneficial
- remove generic tensor stride calculations when layout is fixed
- precompute weight offsets
- vectorize loads/stores
- use coalesced access patterns
- use LDS only when reuse pays for barriers/bank pressure
- fuse activation/bias/residual/scale operations into producer/consumer kernels when this avoids round trips

Do not assume more fusion is always faster. Large fused kernels may increase VGPRs and reduce occupancy. Generate split and fused variants for high-impact blocks and let end-to-end tuning select.

## 13. Navi10 optimization priorities

In priority order:
1. Eliminate inefficient per-element INT8 unpack/dequant in full FP16 path.
2. Reduce global scratch traffic between neural operators.
3. Reduce dispatch/UAV-barrier count without violating dependencies.
4. Reduce address arithmetic and dynamic control.
5. Keep VGPR usage below occupancy cliffs.
6. Use coalesced 16-bit vector loads/stores where practical.
7. Evaluate wave32 vs wave64 per pass.
8. Evaluate group size variants around upstream geometry, respecting image/tensor mapping.
9. Evaluate LDS tiling only where there is enough data reuse.
10. Avoid code-size explosion that harms driver compile/PSO creation or instruction cache.

RGA ISA/resource stats are required for selected production shaders when possible.

## 14. Scratch/resource lifetime optimization

Construct an explicit lifetime graph for all intermediate tensors/resources per frame.

Implement:
- persistent resources only for history/state that crosses frames
- transient resource pool for frame-local intermediates
- memory aliasing for non-overlapping lifetimes when D3D12 aliasing rules are satisfied
- descriptor reuse
- stable resource dimensions rounded to upstream-required alignment

Track each logical tensor with:
```text
name
format
width/height/channels or byte size
producer pass
consumer passes
first use
last use
persistent/transient
alias group
```

Generate a visualization/table into `artifacts/model/resource_lifetimes.md`.

## 15. Barrier/scheduling strategy

Start correct and conservative. Then optimize barriers based on exact producer-consumer relationships.

Requirements:
- UAV barrier only when needed for ordering/visibility across passes using the same/related UAV data.
- Resource transition barriers only on actual state changes.
- Batch barriers when legal.
- If Enhanced Barriers are used, keep a fallback or clearly require the supported D3D12 feature level.
- Never remove barriers solely because a benchmark appears to work once.

Use PIX/RGP-like reasoning and stress loops to validate absence of intermittent corruption.

## 16. Root signatures/descriptors/constants

Prefer one or a very small number of root signatures shared by pass families.
- Preallocate descriptor heaps.
- Prefer descriptor tables and fixed binding conventions.
- Avoid rebuilding descriptor heaps or root signatures per dispatch.
- Use persistently mapped upload memory/ring buffers for constants.
- Respect 256-byte CBV alignment.
- Reuse static samplers where applicable.

Generate bindings from a manifest to keep host/HLSL definitions synchronized.

## 17. Pipeline creation/cache

Build one PSO per selected shader permutation during context creation or from a serialized cache. Normal frame dispatch must not invoke DXC.

Persist a cache key based on:
- GPU adapter/device ID
- driver version where accessible
- DXC version
- shader pack hash
- project build version

If cache loading fails, rebuild safely.

## 18. Autotuning

The project must fully implement all required backends, then select the fastest validated production variant automatically.

Autotuning is internal automation, not a request for the user to manually run experiments.

### 18.1 Candidate dimensions
Per high-cost pass consider:
- `fp16_compat` vs `fp16_high_precision` when outputs qualify
- FP16 canonical vs prepacked layout
- wave32 vs wave64
- conservative vs fused operator form
- selected threadgroup size variants
- original INT8 reference shader if it compiles and is valid on gfx1010

Do NOT create hundreds of meaningless permutations. Use RGA/resource data and model structure to bound the search.

### 18.2 Selection
For each candidate:
1. Correctness gate first.
2. Warm up.
3. GPU timestamp repeated dispatches.
4. Use median/trimmed distribution, not one sample.
5. Reject unstable/device-removal candidates.
6. Record measured micro timing.

Then benchmark complete end-to-end frames using combinations. A locally faster pass may hurt global cache/occupancy/synchronization; end-to-end result is final authority.

Write selected map to:
`generated/tuning/gfx1010_<deviceid>_<driver>.json`

Release can include that map plus safe fallback defaults.

## 19. Standalone harness

The harness is a first-class deliverable, not disposable test code.

Capabilities:
- enumerate/select adapter
- create DX12 device/queue/command allocators/lists/fence
- load deterministic multi-frame testcase from disk
- generate synthetic testcase if no captured real one is available
- run any backend by name
- warmup N frames
- run M measured frames/iterations
- GPU timestamp each logical pass and total dispatch
- dump output as FP16/EXR-equivalent or lossless format supported by chosen image library/tool
- dump intermediate tensors/resources for selected pass/frame
- compare against reference output
- export JSON/CSV metrics
- run reset/non-reset sequences
- support common output sizes (1080p, 1440p, 4K where source supports tiering)
- support Quality/Balanced/Performance/UltraPerformance/Native/DRS variants actually present upstream

Do not make benchmark numbers dependent on CPU file I/O; load inputs before timing.

## 20. Golden/reference data

Create deterministic golden outputs from the faithful reference path on the local GPU/WARP where appropriate.

Store small legal/generated test data inside repo; large captures in `artifacts/` ignored by Git.

For each validation sequence record:
- input dimensions
- output dimensions
- preset
- jitter sequence
- motion vector convention
- depth convention
- exposure
- reset frames
- checksums of inputs
- backend build hash

## 21. Numerical comparison

Implement:
- per-channel max absolute error
- mean absolute error
- RMSE
- PSNR
- SSIM if feasible/reliable
- percentile absolute errors
- NaN/Inf count
- signed bias
- spatial heatmap/diff image

For temporal sequences also compute:
- frame-to-frame error delta vs reference
- temporal variance error in static regions
- history stability after reset
- ghost trail proxy around moving high-contrast objects in synthetic sequence

Exact gates are in `NUMERICS_AND_QUALITY.md`.

## 22. Performance instrumentation

Use D3D12 timestamp queries around:
- optional SPD
- pre
- each model pass
- post
- optional RCAS
- total effect

Convert ticks using queue timestamp frequency. Avoid measuring command-list submission/CPU waiting as GPU execution time.

Also log CPU-side overhead separately:
- descriptor updates
- command recording
- PSO lookup
- upload writes

RGA/RGP should be used to inspect selected bottlenecks, but automated runtime timestamps remain the objective selection basis.

## 23. FSR API-compatible adapter

Implement a DLL exporting the public FSR API functions needed by SDK 2.x compatibility:
- `ffxCreateContext`
- `ffxDestroyContext`
- `ffxDispatch`
- `ffxQuery`
- `ffxConfigure`

Use the public AMD headers matching the chosen API version. Build an internal adapter that:
- recognizes upscaling context descriptors
- maps D3D12 backend/device/command list/resource descriptors
- handles quality-ratio queries
- reports a distinct custom provider/project version where the API permits it
- routes FSR4 requests to `fsr4n10_core`
- returns correct API error codes for unsupported features rather than crashing

Do not forge an AMD digital signature. Do not claim the DLL is AMD-signed. Name the produced binary `fsr4n10_ffxapi.dll` by default.

Add a small `ffxapi_smoketest.exe` that dynamically loads this DLL and exercises query/create/dispatch/destroy on the standalone testcase.

## 24. Logging/diagnostics

Use structured log levels: error/warn/info/debug/trace.
Each run should print/build-record:
- project version/git hash
- GPU/driver info
- selected backend and pass variants
- model pack hash
- shader pack hash
- output size/preset
- whether RCAS/autoexposure enabled

Device removed errors must print DRED information when possible.

## 25. Error handling

Fail closed on:
- model hash mismatch
- missing shader permutation
- unsupported DX12 features
- invalid input resource dimensions/formats
- inconsistent render/display sizes
- bad motion-vector scale metadata
- stale/incompatible tuning cache

Never silently fall back to a lower-quality non-FSR4 algorithm. A fallback to another FSR4 backend is acceptable and must be logged.

## 26. Security/safety boundaries

The project must not:
- patch kernel drivers
- patch VBIOS
- disable code integrity/Defender/SmartScreen globally
- require test-signing Windows
- inject into unrelated processes in this run
- download/execute unknown binary mods

This is user-mode DX12 software only.

## 27. Build configurations

### Debug
- validation enabled
- D3D12 debug layer when available
- GPU-based validation optional because of high overhead
- shader debug info where needed
- assertions
- intermediate dumps

### RelWithDebInfo
- optimized host code
- symbol files retained
- useful for RGP/DRED

### Release
- fully optimized
- no runtime DXC dependency for normal operation
- no expensive validation unless requested
- precompiled DXIL/model pack

## 28. Required command-line interface

At minimum:

```text
fsr4n10_harness.exe --list-adapters
fsr4n10_harness.exe --backend reference_i8 --testcase <path>
fsr4n10_harness.exe --backend fp16_compat --testcase <path>
fsr4n10_harness.exe --backend fp16_high_precision --testcase <path>
fsr4n10_harness.exe --backend hybrid_auto --testcase <path>
fsr4n10_harness.exe --compare reference_i8 fp16_compat --testcase <path>
fsr4n10_harness.exe --benchmark-all --testcase <path> --json <out>
fsr4n10_harness.exe --dump-pass <N> --frame <N> ...
```

Exact syntax can improve, but equivalent functionality is mandatory.

## 29. Development sequence

Codex must execute this sequence autonomously in one long run when possible:

### Milestone 1 — Environment/upstream
Bootstrap tools, fetch/pin source, write lock metadata, inspect actual FSR4 source tree, update any assumptions.

### Milestone 2 — Reference build
Build/port faithful reference provider/model into project-owned harness. Get deterministic output and per-pass timestamps.

### Milestone 3 — Canonical model manifest
Generate and validate manifest of model tensors/passes/weights for all target presets/tiers.

### Milestone 4 — FP16 pack generator
Produce deterministic FP16 weights and host-side validator.

### Milestone 5 — Generic complete FP16 path
Implement every model pass correctly with true FP16 path before aggressive specialization. No missing pass allowed.

### Milestone 6 — Differential correctness
Compare each pass and final output against reference; repair numerical/model/binding errors.

### Milestone 7 — Generated Navi10 kernels
Replace generic FP16 kernels with specialized code-generated variants; preserve generic FP16 as fallback/debug.

### Milestone 8 — Runtime optimization
Resource lifetime, barriers, descriptor reuse, PSO caching, scheduling, scratch layout.

### Milestone 9 — High precision path
Remove redundant quantization boundaries where safe; evaluate quality and speed.

### Milestone 10 — Autotuner/hybrid
Build bounded variants, ISA analysis and end-to-end selection on local RX 5700 XT.

### Milestone 11 — FSR API adapter
Complete compatibility adapter/smoketest around the same core.

### Milestone 12 — Final validation/package
Run long temporal/stability/quality/perf suite, package release and document measured results.

Do not stop after any milestone merely to report progress unless the harness/environment imposes an unavoidable external user action.

## 30. Quality-over-speed tie breaking
When two implementations differ by less than approximately measurement noise/end-to-end 1%, choose the one with better numerical/reference stability, lower complexity and fewer driver-sensitive tricks. Do not trade visible temporal stability for a tiny benchmark win.

## 31. Performance-over-code-size policy
When a specialization produces a real end-to-end speedup without quality regression, larger source/generated shader size is acceptable. However, reject huge code growth if the actual end-to-end gain is negligible or PSO/driver behavior worsens.

## 32. Final reporting
`RESULTS.md` must contain measured, not estimated:
- system info
- driver/DXC versions
- upstream hashes
- selected backend per pass
- total GPU ms by resolution/preset
- reference vs optimized speedup
- per-pass timing table
- quality metrics
- known visual/numerical differences
- stability duration/iterations
- remaining known limitations

If the optimized result is not faster than reference at a particular resolution/preset, say so and ship the faster validated backend automatically rather than falsifying success.

## 33. The most important rule
This project succeeds only if the final output is a faithful FSR4 implementation that is materially more usable on the RX 5700 XT. Clever-looking shader code is not the deliverable. A working, measured, quality-preserving end-to-end runtime is.
