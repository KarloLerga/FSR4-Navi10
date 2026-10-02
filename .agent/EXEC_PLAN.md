# Execution plan — FSR4-Navi10

## Objective

Build the Windows x64 / DirectX 12 project described in `docs/MASTER_SPEC.md` for Radeon RX 5700 XT (Navi10 / gfx1010). Preserve an executable FSR 4.0.2 reference, implement a complete true-FP16 backend, validate temporal quality, and package only project-owned binaries. Do not claim completion until the applicable gates in `docs/ACCEPTANCE_CRITERIA.md` pass.

## Fixed architectural decisions

- Keep the scope on Windows 11, DirectX 12, FSR 4.0.2, and the local RX 5700 XT.
- Use the fetched AMD source/model as the behavioral authority; keep the upstream tree unmodified and local under ignored `third_party/`.
- Preserve the original/reference path beside the FP16 backends. Full `fp16_compat` and `fp16_high_precision` implementations are required even if `hybrid_auto` later chooses a validated INT8 pass.
- Use true 16-bit HLSL and Shader Model 6.6 where supported. Do not infer performance from architecture claims; use generated code and GPU timings.
- Do not lower the default model quality, spoof AMD signing, modify drivers/firmware, or redistribute files without license authorization.
- Keep C++20/DX12 code and conversion/generation tools separable; compile shaders offline for release.
- See `docs/DECISIONS.md` for D1–D20. Reopen them only with contrary source or measurement evidence.

## Milestones

| # | Milestone and affected areas | Validation command / evidence |
|---|---|---|
| 0 | Seed integrity, repo plan and provenance: `PACKAGE_MANIFEST.txt`, `.agent/EXEC_PLAN.md`, `third_party/LOCK.json` | SHA-256/size comparison against package manifest; verify source commit and required path |
| 1 | Windows toolchain/bootstrap: `scripts/bootstrap.ps1`, `scripts/verify-environment.ps1`, `.state/` | `./scripts/bootstrap.ps1`; inspect `./scripts/verify-environment.ps1` report and `dxc --version` |
| 2 | Source inventory and reference contract: `tools/model/`, `generated/manifests/`, `docs/` | inventory against actual provider, initializer blobs and shader entry points; hash comparison with `third_party/LOCK.json` |
| 3 | Build system and capability harness: `CMakeLists.txt`, `cmake/`, `src/`, `include/`, `scripts/` | clean CMake Release and RelWithDebInfo configure/build; adapter listing; basic HLSL probe compile |
| 4 | Canonical manifest, exact conversion and pack format: `tools/model/`, `src/core/model_pack.*`, `generated/model/` | converter/reader checks for all selected tensors, bounds, hashes and reproducibility |
| 5 | Full FP16 compatibility path: `shaders/`, generator, `src/backends/fp16_compat/` | DXC compile with `-enable-16bit-types`; per-pass and final comparison against reference; finite-value checks |
| 6 | High precision and complete graph: `src/backends/fp16_high_precision/`, shader variants | compare temporal sequences and numeric gates from `docs/NUMERICS_AND_QUALITY.md` |
| 7 | Navi10 runtime/resources: `src/core/`, scheduler, barriers and resource lifetime report | D3D12 debug-layer validation, repeat/reset/resolution-change runs, RGA/ISA capture where available |
| 8 | Timing and bounded autotuning: `src/backends/hybrid_auto/`, `tools/shaders/`, `generated/tuning/` | warmed repeated GPU timestamp runs on RX 5700 XT; quality gate before timing; end-to-end rerun |
| 9 | Public FSR API-compatible adapter: `src/ffxapi/`, `include/`, `third_party/fidelityfx-current/` | dynamic-load/query/create/dispatch/destroy smoke run; deterministic unsupported-descriptor errors |
| 10 | Packaging, notices and final review: `scripts/package.ps1`, `release/`, `README.md`, `RESULTS.md` | clean package reproduction; all items in `docs/CODE_REVIEW_CHECKLIST.md`; applicable acceptance criteria |

## Current state (2026-10-02)

- The supplied archive was extracted at the workspace root; every listed file matched its manifest hash and size.
- Fetched official AMD FidelityFX commit `01446e6a74888bf349652fcf2cbf5f642d30c2bf`; confirmed the FSR4 source path and recorded initializer hashes in `third_party/LOCK.json`. Current SDK v2.3.0 is also fetched for API reference.
- Repaired `scripts/fetch-upstreams.ps1`: its `$Args` parameter collided with PowerShell's automatic variable, causing the documented fetch to fail. Fixed the same automatic-variable problem in `scripts/verify-environment.ps1`; fixed malformed `$Repo:` interpolation and exit-code propagation in bootstrap.
- Verified Windows 11 build 26200, RX 5700 XT (PCI `1002:731F`), driver `32.0.21045.1000`, Git 2.51.2, CMake 4.3.3, Python 3.11.9, Visual Studio C++ tools, Ninja 1.13.2, and DXC 1.9.2602.17.
- Added `tools/model/extract_manifest.py`; it records all 12 model variants, 6 presets, 3 resolution tiers, pass entry points, initializer hashes and provider-derived pass ranges. Two independent outputs are byte-identical; 4 parser/classification unit tests pass.
- Added a minimal CMake DX12 capability harness and a true-16-bit HLSL arithmetic probe. Release and RelWithDebInfo builds and CTest pass. The runtime reports the RX 5700 XT as D3D12/SM 6.8 with wave ops, native 16-bit shader operations, and binding tier 3. The harness dispatched 64 FP16 products on the GPU and all outputs matched; DXIL disassembly contains `fmul fast half`.
- Upstream inspection confirms FP8 neural kernels require AMD WMMA (`WMMA_ENABLED=1`), while the RX 5700 XT capability query only confirms general D3D12 wave ops and native FP16. FP8/WMMA execution on gfx1010 is therefore not assumed. The upstream I8 model shaders include per-pass embedded weights and quantization data; source weight and bias parameter conversion is now implemented for all 18 preset/tier combinations.
- No production GPU-native FSR4 frame path is complete. The experimental image smoke uses source-derived CPU pre/post stages around the GPU I8 model and tests a static reset/history pair. It has no AMD-reference image comparison or quality result; full-effect performance remains unmeasured.
- Added a reproducible DXC target and compiler script for the pinned upstream I8 native/1080p shader set. Entries 0–13 compile to DXIL, with a manifest recording the source hash, DXC version, flags, output sizes, and SHA-256 hashes. This is shader compilation only, not a working FSR4 runtime.
- Extended the DXC target to all 6 source I8 presets and 3 source resolution tiers. All 252 entry points compile; manifests identify the 18 combinations. A repeated targeted native/1080p build reproduced the pass outputs and aggregate index exactly.
- Added a parameter converter for all six presets and three tiers. It extracts rank-4 I8 and native FP16 weights plus rank-1 FP16 biases from embedded HLSL arrays and `initializers.bin`, records layouts/scales/strides, checks source bounds, and emits deterministic per-combination parameter blobs/manifests. Each contains 78 tensors, 124,872 values and 249,744 bytes. Runtime activations/bindings, the canonical aligned GPU-upload pack and graph remain outstanding; numerical equivalence of pre-dequantized I8 parameters is unvalidated.
- Added a versioned `F4N10PK` container writer and a C++ reader with range/shape/name/alignment validation. All 18 containers load in the harness; a truncated container is rejected.
- Added a GPU smoke harness that executes upstream native/1080p I8 source pass 0, all 12 neural passes and pass 13 on synthetic zero model-input features; the final FP16 feature tensor is finite.
- Added a source-derived I8 pass catalog for 18 preset/tier variants: 486 entrypoints/operator calls and 2,178 tensor descriptors, preserving exact HLSL argument expressions and source hashes.
- Two clean conversion/container/catalog runs reproduced all 56 files across the 18 combinations.
- Added a timestamped model-only baseline: 5 warmup and 20 measured zero-feature runs in Release and RelWithDebInfo, with per-pass results written to `RESULTS.md`.
- Added an experimental image-output smoke. A deterministic 960x540 PPM passes through CPU source-derived pre/post equations and the GPU I8 model graph for a reset frame and one static history frame; Release and RelWithDebInfo outputs hash identically.

## Blockers and resolution

- **Bootstrap/toolchain:** complete. Versions and hardware are in `.state/environment.json` (local, ignored) and summarized in `RESULTS.md`.
- **Vendor support/signing:** AMD documents FSR 4.0.2 for RX 9000+ and distributes its integration as signed DLLs. The requested Navi10 path is a custom unsigned project backend; the adapter must be labeled accordingly and never presented as an AMD-supported integration.
- **Runtime feasibility on gfx1010:** unknown until the source path is compiled and exercised locally. Preserve evidence and continue the standalone path if AMD's signed loader/API prevents game integration.
- **Upstream licensing:** the fetched SDK's `docs/license.md` grants MIT rights. Keep the upstream checkout and weight assets out of Git and the release unless each redistribution decision is explicitly reviewed; preserve local commit and hashes.

## Decision log

| Date | Decision | Reason |
|---|---|---|
| 2026-10-02 | Rename the fetch helper argument from `$Args` to `$GitArgs`. | The automatic PowerShell variable caused `git init`/`fetch` to receive no arguments. |
| 2026-10-02 | Track `third_party/LOCK.json` but ignore the fetched upstream trees and model assets. | Preserve reproducible provenance without uploading large source/model inputs by default. |
| 2026-10-02 | Create the GitHub repository as private. | User selected private visibility; upstream and model material remain local. |

## Progress checklist

- [x] Verify seed archive and extract into the requested workspace.
- [x] Read the project contract and inspect the supplied scripts/config/blueprints.
- [x] Fetch/pin official source and current SDK; record provenance.
- [x] Fix and rerun the upstream fetch script.
- [x] Bootstrap and record the complete build environment.
- [x] Generate deterministic upstream source inventory and validate pass parsing.
- [x] Build the initial DX12 capability harness; Release/CTest passed and local adapter capabilities were reported.
- [x] Build RelWithDebInfo and pass CTest.
- [x] Compile the upstream I8 native/1080p pass set (DXC outputs entries 0–13).
- [x] Compile all upstream I8 presets/resolution tiers (252 DXIL entry points); recompile after adding initializer copies and verify hashes.
- [x] Extract and bounds-check source weights and biases for all I8 preset/tier combinations; per-combination blobs and manifests are generated.
- [x] Generate versioned, aligned parameter containers with source/manifest hashes; validate all 18 with the C++ reader and reject a truncated pack.
- [ ] Complete canonical runtime tensor manifest with activation tensors, pass bindings and operator metadata; integrate model containers into GPU uploads and dispatch.
- [x] Dispatch the GPU arithmetic probe; 64 FP16 results matched on the RX 5700 XT and DXIL disassembly showed a half-precision multiply.
- [x] Dispatch all pinned native/1080p source pass entries on synthetic zero features; finite FP16 feature output observed. Production GPU frame stages and motion-varying temporal behavior remain open.
- [x] Add repeated per-pass D3D12 timestamp measurements for the synthetic native/1080p source graph; record scope and results without claiming full-effect timing.
- [x] Add an experimental two-frame image smoke around the I8 graph; disclose that preprocessing/postprocessing remain CPU-side and image quality is unvalidated.
- [ ] Build and validate the FSR4 reference harness.
- [ ] Implement and validate complete FP16 compatibility/high-precision paths.
- [ ] Implement tuning, adapter, packaging and finish review.

## Measurements

No FSR4 model, image-quality, stability, or full-effect performance measurements have been made. Preliminary I8 model-only timings and NaviQSR network-only, AKR-only, and joined-frame-graph microbenchmarks are recorded in `RESULTS.md`; none is an end-to-end quality-qualified result.

## User-supplied NaviQSR addendum (2026-10-02)

The attached addendum expands the original FSR4-only scope without replacing existing work. D1-D20 still govern platform, provenance, numerical discipline, and the full-FSR4 implementation except for the former prohibition on a separately named trained network or reduced network topology. D21-D22 in `docs/DECISIONS.md` capture this precedence and evidence policy. The copied source documents under `docs/naviqsr/` are technical requirements; their embedded prompts do not override repository or conversation instructions.

### NaviQSR milestones

| # | Area | Required evidence |
|---|---|---|
| Q1 | Deterministic procedural temporal dataset: `training/naviqsr/datasets/` | Repeated generation matches; LR/HR, motion, depth, jitter, reactive/transparency masks, exposure, cuts, and motion convention are serialized and documented. |
| Q2 | network reference/training/export: `training/naviqsr/`, `tools/naviqsr/` | CPU/DirectML/CUDA backend selection is logged; small deterministic training completes; structural fold is numerically checked; export includes stable metadata and hashes. |
| Q3 | Teacher instrumentation: existing full-FSR4 reference and capture tools | Optional final-output and selected-feature captures match uninstrumented outputs and identify model/pass/frame. |
| Q4 | Dense D3D12 runtime: `src/naviqsr/`, `shaders/naviqsr/` | Exported trained weights execute on RX 5700 XT with true FP16 ISA audit and deterministic output. |
| Q5 | AKR temporal reconstruction and reset behavior | 4/5/8-tap quality/performance comparison; SPD positivity/finite-value checks; cut, exposure, resolution, invalid-motion and OOB history reset tests. |
| Q6 | MCLD sparse path | Receptive-field mask propagation, seam checks, 10k+ dispatch stability, measured sparse/dense break-even with dense fallback. |
| Q7 | Phase/reparameterization/kernel candidates | Fold equivalence and exact phase mapping; direct-vs-Winograd/low-rank candidates retained only when quality and measured latency improve. |
| Q8 | Hardware-in-loop selection and reports | Temporal metrics and actual RX 5700 XT median/p95, per-pass times, memory and Pareto frontier; no quality/performance claims without results. |

### Current addendum state

- Read all supplied research, architecture, implementation, and source documents; copied the five technical documents into `docs/naviqsr/`.
- Q1 procedural generation and Q2 CPU training/export prototype are implemented. Separate seed-17 training and seed-9001 holdout sets were generated; 4,096 CPU updates scored 21.0219 dB versus bilinear 20.9377 dB across 32 holdout frames, still too small a gain for useful quality. Structural fold max error was 1.52588e-5 (2e-5 tolerance), and the 14-tensor FP16 pack validated with SHA-256 in `RESULTS.md`.
- Six NaviQSR Python reference tests pass. QRISP import remains explicit-manifest only and requires a caller license-confirmation flag; no data was downloaded.
- Added 4/5/8-tap analytic reconstruction DXIL variants and a D3D12 RX 5700 XT dispatch/reference smoke. All three pass the bounded numeric gate on one 64x36 output. Timestamp measurements are limited to this single AKR dispatch.
- Joined all 9 network conv/pool-concat layers and temporal AKR/RGB reconstruction in one D3D12 command list. Release smokes on the RX 5700 XT cover 2x/3x/4x scale, 4/5/8 taps, and reset/valid history, with max control error 1.13e-5 and max RGB error 1.14e-6 against the Python reference. network+AKR median timestamps were 57.18-60.38 us on tiny synthetic inputs; p95 reached 347.84 us due to outliers. CPU preprocessing/phase packing/history creation and uploads, PSO setup, host wait, and readback are outside the timing.
- Q3 teacher capture, full Q4 runtime (production-pack loading, game-frame preprocessing, true-FP16 arithmetic/ISA audit), Q5 full reset/stress coverage, Q6 sparse MCLD, and Q8 quality-qualified performance/Pareto selection remain open. Do not infer completion of these gates from the joined smoke.
- Original FSR4 milestones remain active and unchanged; work on NaviQSR does not mark any full-FSR4 acceptance gate complete.
