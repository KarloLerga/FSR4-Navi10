# Execution plan â€” FSR4-Navi10

## Objective

Build the Windows x64 / DirectX 12 project described in `docs/MASTER_SPEC.md` for Radeon RX 5700 XT (Navi10 / gfx1010). Preserve an executable FSR 4.0.2 reference, implement a complete true-FP16 backend, validate temporal quality, and package only project-owned binaries. Do not claim completion until the applicable gates in `docs/ACCEPTANCE_CRITERIA.md` pass.

## Fixed architectural decisions

- Keep the scope on Windows 11, DirectX 12, FSR 4.0.2, and the local RX 5700 XT.
- Use the fetched AMD source/model as the behavioral authority; keep the upstream tree unmodified and local under ignored `third_party/`.
- Preserve the original/reference path beside the FP16 backends. Full `fp16_compat` and `fp16_high_precision` implementations are required even if `hybrid_auto` later chooses a validated INT8 pass.
- Use true 16-bit HLSL and Shader Model 6.6 where supported. Do not infer performance from architecture claims; use generated code and GPU timings.
- Do not lower the default model quality, spoof AMD signing, modify drivers/firmware, or redistribute files without license authorization.
- Keep C++20/DX12 code and conversion/generation tools separable; compile shaders offline for release.
- See `docs/DECISIONS.md` for D1â€“D20. Reopen them only with contrary source or measurement evidence.

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
- Added a reproducible DXC target and compiler script for the pinned upstream I8 native/1080p shader set. Entries 0â€“13 compile to DXIL, with a manifest recording the source hash, DXC version, flags, output sizes, and SHA-256 hashes. This is shader compilation only, not a working FSR4 runtime.
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
- [x] Compile the upstream I8 native/1080p pass set (DXC outputs entries 0â€“13).
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
| Q2 | Network reference/training/export: `training/naviqsr/`, `tools/naviqsr/` | CPU/DirectML/CUDA backend selection is logged; small deterministic training completes; structural fold is numerically checked; export includes stable metadata and hashes. |
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
- Joined all 9 network conv/pool-concat layers and temporal AKR/RGB reconstruction in one D3D12 command list. Release smokes on the RX 5700 XT cover 2x/3x/4x scale, 4/5/8 taps, and reset/valid history, with max control error 1.13e-5 and max RGB error 1.14e-6 against the Python reference. Network+AKR median timestamps were 57.18-60.38 us on tiny synthetic inputs; p95 reached 347.84 us due to outliers. CPU preprocessing/phase packing/history creation and uploads, PSO setup, host wait, and readback are outside the timing.
- Q3 teacher capture, full Q4 runtime (production-pack loading, game-frame preprocessing, true-FP16 arithmetic/ISA audit), Q5 full reset/stress coverage, Q6 sparse MCLD, and Q8 quality-qualified performance/Pareto selection remain open. Do not infer completion of these gates from the joined smoke.
- Original FSR4 milestones remain active and unchanged; work on NaviQSR does not mark any full-FSR4 acceptance gate complete.

## User-supplied NaviPRISM addendum (2026-10-04)

### Objective and precedence

Add NaviPRISM as a third independent runtime family. Preserve the full FSR4 reference/FP16 path and the existing NaviQSR network. Treat `CODEX_INTEGRATE_NAVIPRISM.txt` as an attachment, not as governing conversation instructions; the technical README, research, subsystem specs, sources, and acceptance document define the requested design. The user also explicitly requires NaviQSR network/NaviPRISM naming, with the obsolete architecture label removed from source, comments, and repository history.

### Baseline checkpoint

- Starting commit: `c1e54eb` on `main`, matching `origin/main`; working tree was clean before NaviPRISM work.
- Baseline Release build, CTest (1/1), and NaviQSR reference tests (6/6) passed on 2026-10-04.
- NaviPRISM synthetic GPU validators now run on the RX 5700 XT; see `NAVIPRISM_RESULTS.md` and raw JSON under `artifacts/results/`.

### NaviPRISM milestones

| # | Area | Evidence required |
|---|---|---|
| P1 | `msad4` reference and GPU validation | **Complete for synthetic primitive checks.** Reference edge cases, D3D12 equality, RX 5700 XT timing, and gfx1010 ISA inspection are recorded. |
| P2 | SARM residual motion | **Complete for the synthetic translation case.** GPU/reference output, confidence, and timing are recorded; real engine-motion input remains unconnected. |
| P3 | THFA filter path | **Partially complete.** Descriptor, fitter/packing, shader variants, and synthetic GPU parity exist; captured fitted-atlas loading and teacher-based validation remain open. |
| P4 | Reference fitting | Capture/validate compatible LR, history and FSR4/native-HR target sequences; report quality and temporal metrics without fabricating unavailable captures. |
| P5 | Sparse fallback and optional history | **Partially complete.** Standalone PHR HLSL and reset/reprojection parity run on the GPU; sparse SADNet/NaviQSR dispatch, persistent history, seam tests, and quality A/B remain open. |
| P6 | Quality-safe routing | **Classifier smoke complete only.** GPU classification/compaction matches eight synthetic cases; downstream branches, measured route fractions, and image metrics remain open. |
| P7 | Reports and naming cleanup | **Complete.** Reports and current-tree cleanup are committed; the reachable history was rewritten and private `main` was updated. Later commits continue to use the clean naming. |

### Work sequence and validation

1. Copy and CRC-check the technical addendum under `docs/naviprism/`; preserve the existing FSR4/NaviQSR material. **Complete.**
2. Build scalar `msad4` reference/tests and HLSL variants, then run target GPU timing and inspect DXIL. Resolve RGA/ISA tooling availability before making any hardware-instruction claim. **Complete for the measured primitive.**
3. Implement SARM against deterministic synthetic motion/search cases; validate both math and temporal reset/bounds behavior. **Complete for the synthetic translation case.**
4. Add the THFA reference fitter, packed atlas, runtime lookup/filter shader and D3D12 dispatch; compare to deterministic teacher targets only when valid captures exist. **Primitive path complete; teacher comparison remains open.**
5. Add hard-tile routing, selected fallback, optional PHR experiments, then quality/performance reporting. Do not enable a path whose measurement loses. **Classifier and standalone PHR checks complete; fallback and A/B gates remain open.**
6. Rebuild all old and new paths, run relevant C++/Python/GPU checks, and update reports. **Current checks and reports complete for implemented paths.**
7. Rewrite commit messages and historical text/path snapshots to remove obsolete names; force-update the private `main` branch only after the rewritten local history verifies cleanly. **Complete; subsequent commits preserve the clean naming.**

### NaviPRISM evidence and open gates

- `msad4`, SARM residual matching, THFA filter variants, tile classification, and phase-history reprojection/reset have RX 5700 XT synthetic GPU checks. The five raw reports are committed under `artifacts/results/`; details and timing scope are in `NAVIPRISM_RESULTS.md`.
- AMD RGA 2.14.2.7 generated gfx1010 ISA. The `msad4` and SARM variants contain `v_mqsad_u32_u8`; the scalar-u8 and FP16-difference comparison variants do not. The measured `msad4` median is 287.665 us versus 288.654 us for scalar-u8 and 337.109 us for FP16 difference/FP32 accumulation on this benchmark. This is near parity with scalar, not a material speedup claim.
- No FSR4 teacher/native-HR capture sequence is present. THFA fitting utilities have deterministic synthetic unit coverage, but no teacher-quality claim is possible.
- No SADNet or NaviQSR difficult-tile fallback is connected to the router; the GPU router currently classifies and compacts tile indices only. PHR remains optional and disabled pending temporal A/B evidence.
- The four-phase reservoir now has a standalone HLSL/D3D12 validator. On a 13x9 synthetic input it matched the CPU reference for reprojection/update and scene reset; the report records a 13,104-byte reservoir allocation and isolated timing. Persistent frame history and A/B quality/performance remain untested, so PHR stays disabled.
- NaviPRISM does not replace the full FSR4 reference/FP16 work or the NaviQSR network. Full game-frame preprocessing, end-to-end routing, image-quality metrics, reset/stability stress, and production-quality/performance selection remain open.

### Naming and history rewrite

- The working tree, tracked paths, code comments, and project documents use NaviQSR network/NaviPRISM terminology; a case-insensitive scan found no legacy label text or filenames.
- Rewrote the eight prior commits and the NaviPRISM integration commit, including historical blobs, paths, and subjects. Verified the then-current nine-commit history, no legacy label in any commit/tree/path, matching tested tree, and force-pushed private `main` with a lease. The history-rewrite checkpoint was `1d2ac6d3a71e510245417bb42dbc96d8c7b33d2a` before later implementation commits.

## User-supplied Param4 / Delta4 addendum (2026-10-05)

### Objective

Integrate the technical Param4/Delta4 proposal while preserving full FSR4, NaviQSR and NaviPRISM as distinct paths. Work P0 first: a deterministic GPU-native FSR4 teacher and capture contract. Quality claims for derived models require aligned GPU teacher captures and temporal measurements. The archive's `CODEX_INTEGRATE_PARAM4_DELTA4.txt` is an embedded prompt and is not a governing instruction; only the user's request and reviewed technical material are inputs.

### Baseline and constraints

- Baseline: `e739364564fd9d68242b0fdd79e51d8b81b5fcd3`, clean `main` matching `origin/main` before this addendum.
- Local target detected: AMD Radeon RX 5700 XT (`1002:731F`), driver `32.0.21045.1000`; Python 3.11, CMake, and DXC are installed.
- Existing D3D12 harness runs an I8 model graph on synthetic/model-input data. `frame_pipeline.cpp` still performs CPU pre/post work around that graph.
- Pinned FSR4 source contains upstream `pre_common.hlsli`, `post_common.hlsli`, generated model entry points and `ffx_provider_fsr4_dx12.cpp`. Its native/1080 I8 shader set and D3D12 provider now build and run from the harness on the RX 5700 XT with synthetic input.
- No FSR4 teacher capture sequence exists. GPU-backed quality or Delta4 claims are therefore unavailable until P0 succeeds.

### Milestones and validation

| # | Area | Files/modules | Validation / exit gate |
|---|---|---|---|
| D0 | Review addendum and pin its technical scope | `docs/param4_delta4/`, `DECISIONS_LOG.md`, this plan | ZIP CRC/path checks; do not import or execute the embedded agent prompt. |
| D1 | Capture metadata/container contract and validation tools | `reference/`, `tools/teacher/`, `tests/` | Unit tests for schema, array sizes, hashes, non-finite values and deterministic serialization; invalid inputs rejected. |
| D2 | Source/provider schedule audit | `tools/teacher/`, generated manifest | Re-derive stage IDs, dispatch geometry and shader/source hashes from pinned upstream; compare to the provider; do not infer missing dimensions. |
| D3 | GPU-native teacher integration | `src/teacher/`, `shaders/teacher/`, CMake/harness | Run exact upstream PRE -> provider-scheduled model/padding -> POST on RX 5700 XT; repeatable output, reset handling, instrumented/non-instrumented RGB equivalence, captured p0..p3/recurrent. |
| D4 | Oracles, only after valid captures | `tools/param4/`, `docs/PARAM4_ORACLE_RESULTS.md`, `artifacts/results/` | Control-grid, recurrent quantization, kernel/codebook and Delta4 basis reports must use paired real teacher/FSR3 captures and final RGB/temporal metrics. |
| D5 | Param4/Delta4 runtime paths, only after the oracle gate | `src/param4/`, `shaders/param4/`, training, results docs | Recurrent rollout, true FP16 audit if advertised, RX 5700 XT quality and full-resolution timings. |
| D6 | Release/review synchronization | `RESULTS.md`, `PROGRESS.md`, `DECISIONS_LOG.md`, this plan | Full relevant build/unit/GPU checks pass; docs state every still-open gate plainly; commit and update private `origin/main`. |

### Fixed decisions carried forward

- Windows 11 + DX12 and RX 5700 XT/gfx1010 remain first target; no generic-platform detours.
- The pinned upstream FSR4 source/provider defines numerical semantics, resource bindings and dispatch scheduling. No unsupported ISA assumptions or silent quality reduction.
- Full FSR4, NaviQSR, NaviPRISM, Param4 and Delta4 remain clearly separated. A synthetic or CPU-side smoke is not a teacher capture.
- Do not run unreviewed attachment code or vendor research implementations. Preserve source/license provenance.

### Decision log

- Param4/Delta4 is an additional experimental architecture family, not a rename or replacement of existing paths.
- Reviewed technical documents may be retained under `docs/param4_delta4/`; the embedded agent prompt is excluded. Technical assertions remain proposals until checked against pinned source or measurements.
- The exact provider-framegraph execution and capture-tap plumbing now run with synthetic input. A valid synthetic `.f4cap` proves the extraction/packaging path, not a representative teacher sequence. The remaining P0 gate is a supported input path for real captured frames plus valid real-scene captures. Do not advance to teacher-dependent training/oracles until real captures exist.
- Raw logits from the synthetic frame exceed the FP32 exponential range. The `.f4cap` physical-controls field therefore uses stable mathematical equivalents of the pinned tanh/sigmoid transforms, with the choice recorded in metadata; those taps are detached from reconstruction.

### Progress checklist

- [x] Verify archive contents/CRC and ensure safe paths; inspect technical scope without executing archive code.
- [x] Confirm baseline commit, clean worktree, local GPU/compiler environment and absence of GPU teacher captures.
- [x] Integrate reviewed technical docs and record decisions.
- [x] Implement strict deterministic capture contract and validator with unit coverage.
- [x] Audit provider scheduling and create source-hashed stage manifest.
- [x] Add capture-only taps for PRE source/semantic inputs and POST raw parameters; read recurrent state, history and RGB from provider resources.
- [x] Emit, package and validate a deterministic 10-array synthetic `.f4cap`; compare instrumented output against ordinary provider output and repeat all taps.
- [ ] Add a versioned real-frame input path and emit a representative real-scene teacher sequence on the RX 5700 XT. No such frame sequence was supplied; the synthetic provider smoke is not a teacher-quality capture.
- [x] Run Release build, provider GPU smoke, `.f4cap` validator, CTest (1/1), and Python unit suite (44/44); update implementation docs.
- [x] Commit implementation and measured report, then push both to the private remote.

### Measured results

- The pinned provider completed two instrumented and one ordinary synthetic 1920x1080 reset dispatch on the RX 5700 XT. All output hashes match at `304bc89ba22b08e4ab12b2d27458179b6cf7af4cc7d4a35e5ccfe864edaa7813`; raw parameter, control, semantic and recurrent taps are deterministic across instrumented resets.
- The generated `.f4cap` passed validation with 10 arrays and 211,507,200 array bytes; sequence hash `85f8c4b9f91fd8aac7c7bbc83007738f8116b5ae178c731827e7dfab52dc826b`. Capture is synthetic and remains under ignored `build/release/`.
- No real-scene Param4/Delta4 sequence, FSR3 pairing, image-quality metric or teacher timing has been generated.
- The prior I8 graph timings in `RESULTS.md` remain synthetic model-only measurements and are not a full FSR4 effect baseline.

## User-supplied DeltaControl V2 addendum (2026-10-05)

### Objective

Integrate the reviewed DeltaControl V2 research and enable reproducible stateful FSR4/FSR3 runs from one versioned `.f4seq`. Keep DeltaControl, Param4, Delta4, NaviQSR, NaviPRISM, and full FSR4 as separate paths. A procedural sequence is pipeline validation only; quality conclusions require representative rendered content.

### Baseline and fixed inputs

- Baseline: `73193bd34dc0e7f8e060e2ebee902b70d6779570`, clean `main` matching `origin/main`.
- FSR4 source/provider commit: `01446e6a74888bf349652fcf2cbf5f642d30c2bf`.
- Local FidelityFX SDK source commit: `60f4ea81909200d8542eca14dccb2628b763a9a3`; its FSR3 upscaler header identifies version 3.1.5.
- Reviewed technical documents live in `docs/delta_control_v2/`; the archive's embedded Codex prompt is excluded and is not project authority.
- No representative rendered `.f4seq` or paired quality dataset was supplied. The locally generated FSR3 captures are paired to synthetic frames and lack the exact accumulation-site C/H basis signals.

### Milestones

| # | Work | Files/modules | Validation / exit gate |
|---|---|---|---|
| V0 | Review, hash and retain technical addendum | `docs/delta_control_v2/`, `DECISIONS_LOG.md`, this plan | ZIP CRC, safe paths and every listed length/SHA-256 match; exclude embedded prompt. |
| V1 | Versioned sequence container, deterministic procedural generator and validator | `tools/sequence/`, `docs/delta_control_v2/F4SEQ_FORMAT.md`, `tests/` | Round-trip, malformed bounds/hash/non-finite rejection, stable serialization and per-frame metadata/content hashes. |
| V2 | Stateful GPU FSR4 provider sequence input | `include/fsr4n10/`, `src/sequence/`, `src/teacher/`, harness/CMake | Multiple frames in one provider context; honor jitter/delta/reset; instrumented and ordinary output byte equality per frame; reset/cut handling; deterministic rerun. |
| V3 | FSR3.1.5 aligned provider/capture | `src/teacher/fsr3_reference_runtime.cpp`, CMake, `tools/sequence/` | Same `.f4seq`; source-confirmed taps, normal/instrumented RGB equality, provider GPU time, and exact accumulation-site C/H signals before Delta4 use. |
| V4 | Exact POST replay and DeltaControl oracle ladder | `tools/oracles/`, reports, `artifacts/results/` | O0 requires final RGB within tolerance **and finite source-equation intermediates**; do not run teacher-derived analysis when O0 fails. |
| V5 | Architecture selection and runtime candidates | `src/deltacontrol/`, `shaders/deltacontrol/`, training | Implement only candidates justified by oracle results; no default change without quality, stability and end-to-end timing gates. |
| V6 | Synchronize release evidence and private remote | `RESULTS.md`, `PROGRESS.md`, `DECISIONS_LOG.md`, this plan | Relevant Release build/unit/GPU checks pass; limitations and open gates remain explicit; commit and push. |

### Current blockers

- The local provider is compiled for native/1080 only. Preset/tier permutation support must be audited before any 1440p or 4K runs.
- The deterministic `.f4seq` reader/generator, stateful FSR4 sequence dispatch, pinned FSR3.1.5 sequence runner, and aligned 8-frame synthetic provider reports now exist. They validate the plumbing only.
- FSR4 O0 RGB replay agrees within 1e-3 on audit frames 0, 4, and 7, but fails numerical validity: source-equation intermediates are non-finite at 2,073,600 / 2,073,600 pixels on frames 0 and 4 and 2,073,528 / 2,073,600 on frame 7. The captured FSR4 RGB is entirely black on frames 0 and 4 and 99.9965% zero on frame 7. Matching black output does not clear O0.
- The current FSR3 taps do not include exact `C` and `H` at the accumulation site; the existing `internal_upscaled_color_after_accumulate` tap is after blending and cannot substitute. Do not run the Delta4 basis oracle until those capture-only taps exist.
- No representative rendered scene input exists. Synthetic data cannot clear O0-O13 teacher-quality gates or justify DeltaControl training/runtime selection.

### Decision log and progress

- V0 complete: ZIP CRC and source manifest hashes/sizes verified; 16 reviewed README/technical documents retained with archive hash in `docs/delta_control_v2/ADDENDUM_SOURCE_MANIFEST.json`; embedded prompt deliberately excluded.
- V1 complete for format, deterministic generator, validator, and Python coverage. V2 complete for the native/1080 synthetic multi-frame provider path, reset/cut handling, input hashes, exposure/mask bindings, timing, and instrumented/ordinary per-frame equality.
- V3 partially complete: pinned FSR3.1.5 consumes the same eight frames and reports aligned input hashes, source-confirmed resource taps, timing, and instrumented/ordinary output equality. Exact accumulation-site C/H remain missing.
- V4 replay tool is implemented. The synthetic captures reproduce their final RGB within 1e-3, but O0 fails its finite-intermediate requirement because the raw teacher controls overflow the source POST exponent formulas and produce nearly all-black output. Do not start O1-O13 or V5 until a representative, numerically valid capture set passes O0.
- Current measurements and limitations are recorded in `RESULTS.md` and `artifacts/results/`. Do not claim real-scene quality or speed from generated fixtures.
