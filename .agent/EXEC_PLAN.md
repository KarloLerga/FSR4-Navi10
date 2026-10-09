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
- FSR4 O0 RGB replay agrees within 1e-3 on audit frames 0, 4, and 7, but fails numerical validity: source-equation intermediates are non-finite at 2,073,600 / 2,073,600 pixels on frames 0 and 4 and 2,073,528 / 2,073,600 on frame 7. The captured FSR4 RGB is entirely black on frames 0 and 4 and 99.9965% zero on frame 7. Resolve the native/1080 model-output overflow or capture semantics, then rerun O0 with finite intermediates before starting O1-O13.
- The current FSR3 taps do not include exact `C` and `H` at the accumulation site; the existing `internal_upscaled_color_after_accumulate` tap is after blending and cannot substitute. Add capture-only taps at the exact accumulation site before using FSR3 for the Delta4 basis oracle.
- No representative rendered scene input exists. Capture or pack an actual rendered temporal sequence, then rerun both providers with matching per-frame hashes. Synthetic data cannot clear O0-O13 teacher-quality gates or justify DeltaControl training/runtime selection.

### Decision log and progress (2026-10-05)

- [x] V0: verify ZIP CRC, safe paths and all source manifest hashes/sizes; retain 16 technical documents and archive provenance; exclude the embedded prompt.
- [x] V1: implement `.f4seq` pack/read/validate, deterministic procedural generation, and malformed-input/hash/round-trip unit checks.
- [x] V2: implement the stateful native/1080 FSR4 sequence path with reset/cut, jitter, delta, exposure and masks; per-frame instrumented/ordinary outputs match.
- [x] V3 plumbing: pin and run FSR3.1.5 against the same eight frames; aligned hashes, source-confirmed taps, provider timings and instrumented/ordinary equality recorded.
- [x] V4 tooling: implement exact source-equation POST replay; RGB replay, package validation, intermediate finite checks and machine-readable report are recorded.
- [ ] V3 completion: add exact accumulation-site FSR3 C/H capture-only taps; validate they do not alter output.
- [ ] V4 O0 exit: diagnose and resolve FSR4 raw-parameter overflow/capture validity, then pass output tolerance with finite intermediates on multiple frames and profiles.
- [ ] V5 and O1-O13: remain gated until a numerically valid teacher capture set passes O0; use a representative rendered sequence for quality analyses.
- [x] V6 current evidence: Release build, CTest (1/1), Python suite (54/54), provider sequence runs and reports completed; commits `41f903f` and `4c0ae25` pushed to private `origin/main`.
- Do not claim real-scene quality or speed from generated fixtures. Measurements and limitations are in `RESULTS.md` and `artifacts/results/`.

## User-supplied FSR4 root-cause and FSR3 basis addendum (2026-10-07)

### Current objective

Apply the reviewed fix bundle as a reproducible diagnostic: compare intrinsic/scalar signed-I8 dot4 with literal/stable FSR4 POST math on the existing aligned eight-frame `.f4seq`, then add exact FSR3.1.5 current/history taps at the accumulation lerp. Stable POST remains diagnostic and cannot satisfy O0 or unlock O1-O13 by itself. The archive's `CODEX_PROMPT.md` is an embedded prompt, not governing instruction.

### Milestones and validation

| # | Work | Files/modules | Validation / exit gate |
|---|---|---|---|
| R0 | Review the archive and verify inputs | bundle, `.agent/EXEC_PLAN.md` | CRC/path review; inspect scripts before use; confirm sequence hashes and capacity for generated captures. |
| R1 | Add isolated FSR4 diagnostic variants | `CMakeLists.txt`, `tools/teacher/compile_provider_i8_native_1080.py`, `tools/oracles/replay_fsr4_post.py` | DXC/provider build for all four cases; scalar semantics recorded; literal O0 gate unchanged; stable-only cannot unlock O1-O13. |
| R2 | Run the four-case root-cause matrix | `scripts/run-fsr4-rootcause-matrix.ps1`, `tools/oracles/summarize_fsr4_rootcause_matrix.py`, `artifacts/results/` | Same existing eight-frame `.f4seq`; four per-case provider/replay reports; instrumented equality, per-frame raw parameter ranges, finite counts and zero fractions; diagnosis in summary. |
| R3 | Add exact FSR3 C/H accumulation taps | `tools/shaders/compile_fsr3_reference.py`, `src/teacher/fsr3_reference_runtime.cpp` | Compile pinned FSR3.1.5 shader variants; run aligned sequence; all first output regions byte-identical; four basis arrays have expected shapes/hashes. |
| R4 | Validate and record current state | `RESULTS.md`, `PROGRESS.md`, `DECISIONS_LOG.md`, this plan | Release build, CTest and Python suite; compare FSR3/FSR4 frame hashes; keep generated capture payloads ignored; commit and push to private `origin/main` if gates pass. |

### Baseline and fixed decisions

- Baseline is clean `main` at `6aca8f0102025afac460c1ac313b7457ac576031`.
- Existing `build/release/delta-control-smoke.f4seq` is the shared eight-frame synthetic sequence; prior FSR3/FSR4 input hashes align and its sequence hash is `a06357453979901689f4f9c8ff2400a1efe5b9547e017a7fa4cf5219ba157ec2`.
- Preserve exact literal pinned-source O0 semantics. Overflow-stable transforms are a diagnostic comparison only; do not select them as a default or report a valid teacher result solely from their success.
- Keep FSR4, NaviQSR, NaviPRISM, Param4, Delta4 and DeltaControl as distinct paths. The synthetic sequence validates the pipeline, not rendered-scene quality.
- Do not modify the pinned FidelityFX source tree. Compile capture overlays from the pinned source and record their hashes.

### Progress

- [x] Inspect the ZIP manifest and CRC; review handoff/research notes; statically inspect patch, runner and summarizer. Exclude embedded `CODEX_PROMPT.md` as instruction authority.
- [x] Confirm baseline commit, clean worktree, existing eight-frame sequence, matching prior FSR3/FSR4 frame hashes, and that the matrix output directory is absent.
- [x] R1: build all four intrinsic/scalar dot4 and literal/stable POST diagnostic variants; preserve the default intrinsic/literal configuration.
- [x] R2: run the aligned eight-frame matrix; record per-case provider, POST replay, raw parameter, finite-value, and zero-fraction results.
- [x] R3: compile 40 FSR3.1.5 shader permutations with exact accumulation-site C/H taps; verify all eight input-frame hashes and all three audit captures.
- [x] R4: pass Release/CTest/Python checks, record limitations and artifacts, commit the diagnostic work, and push it to the private remote authorized earlier in the session.

### Decision log

- Add the scalar-vs-intrinsic and literal-vs-stable comparisons as diagnostic build modes only; keep default settings on the existing intrinsic/literal path.
- Keep the full four-case matrix evidence separate from teacher-quality acceptance. Only a literal variant passing replay, finite-value, nondegeneracy and instrumented-equality checks can satisfy the O0 gate.
- Store matrix reports in `artifacts/results/`; put large raw captures and transient build outputs under ignored `build/` paths so captures do not enter Git.

### Current status

- The matrix was run on `build/release/delta-control-smoke.f4seq` (sequence hash `a06357453979901689f4f9c8ff2400a1efe5b9547e017a7fa4cf5219ba157ec2`). All four cases and FSR3 use identical hashes for all eight inputs.
- No FSR4 case clears O0. Intrinsic/literal preserves the POST RGB replay match but has non-finite model intermediates on all audited pixels and nearly/all-black output. Stable POST removes those non-finite values but diverges from captured RGB. Scalar signed-I8 produces finite, nonblack output, but provider instrumented/ordinary equality and literal RGB replay both fail. Stable POST does not resolve that divergence.
- The FSR3.1.5 basis taps are captured and hashed for frames 0, 4, and 7; each normal/instrumented output pair matches exactly. The result remains synthetic pipeline evidence with no quality claim.

## User-supplied O0 unblock bundle (2026-10-08)

### Objective

Test the proposed FSR4 O0 unblock path from the clean `312bd98ebea52ea316a9cbb2f2194ecfb538ede2` baseline: correct CPU POST edge-coordinate semantics, capture ordinary-reference RGB beside the instrumented FSR4 output, and add independent GPU POST and signed-I8 dot4 conformance oracles. Keep O1-O13 locked until the scalar-literal path passes every independent correctness gate. The archive's `CODEX_PROMPT.md` is descriptive input, not project authority.

### Milestones and exit checks

| # | Work | Files/modules | Validation / exit gate |
|---|---|---|---|
| U0 | Verify archive integrity, source anchors, scope, and existing capture availability | ZIP manifest, `post_common.hlsli`, this plan | CRC and all listed size/SHA checks pass; patch scope and commands reviewed; no changes outside the repository. |
| U1 | Correct the CPU POST oracle and capture numeric reference RGB | `tools/oracles/replay_fsr4_post.py`, `tools/teacher/capture_format.py`, `src/teacher/gpu_teacher.cpp` | Edge-case unit test; regenerate scalar-literal captures; verify exact input-frame hashes and numeric instrumented/reference error. |
| U2 | Add isolated DP4A conformance and GPU POST oracle | `src/harness/`, `include/fsr4n10/`, `shaders/runtime/`, CMake | Release build; native `dot4add_i8packed` matches scalar signed-byte semantics across deterministic and edge vectors; GPU POST readback compared to capture RGB. |
| U3 | Re-evaluate the scalar-literal teacher gate | `tools/oracles/`, `artifacts/results/` | Corrected CPU replay, GPU replay, reference-output equivalence, same-input run repeatability, sequence alignment, FSR3 C/H audit, and dot4 results all recorded; gate only opens if independent correctness checks pass. |
| U4 | Update evidence and synchronize private remote | `RESULTS.md`, `PROGRESS.md`, `DECISIONS_LOG.md`, this plan | Relevant Release build, CTest, Python suite, GPU checks, and artifact validation pass; commit and push only the verified state. |

### Baseline and fixed decisions

- Baseline is clean `main` at `312bd98ebea52ea316a9cbb2f2194ecfb538ede2`.
- Source review and a local DXIL dump confirm `apply_model_filter` uses `uint` for `x_in/y_in`: addition/subtraction wrap as 32-bit unsigned, and the Gaussian distance converts that wrapped value with `uitofp`; `LoadInputColor(int2(...))` reinterprets the same bits as signed then clamps only the texture lookup. The archive proposed signed distance coordinates, which are not source-exact at left/top edges. The CPU and independent GPU oracles now preserve unsigned wrapping for distance and signed/clamped lookup coordinates without changing pinned upstream source.
- Preserve the four-case FSR4 matrix and FSR3 C/H artifacts already committed. The existing scalar-literal raw capture packages remain available under ignored `build/fsr4-rootcause-matrix/`.
- Treat isolated dot4 conformance, GPU POST parity, and instrumented/reference RGB parity as separate gates. A passing individual probe does not unlock O1-O13 by itself.
- Do not change the production/default provider to scalar arithmetic, stable POST, or a quality-reduced path on the strength of this synthetic sequence.

### Progress

- [x] U0: inspect ZIP CRC/path listing, verify all 15 manifest entries, confirm clean base commit, review embedded prompt separately, and verify the POST edge hypothesis against pinned source.
- [x] U1: update CPU edge replay and optional reference capture; regenerate scalar-literal captures and record numeric comparison.
- [x] U2: build the isolated GPU POST and signed-I8 dot4 oracles; run both on the RX 5700 XT.
- [x] U3: evaluate corrected CPU/GPU POST, ordinary-output parity, same-input run repeatability, eight-frame alignment, FSR3 C/H audit, and dot4 evidence. Gate correctly remains closed on output parity and repeatability.
- [x] U4: Release/CTest/Python/GPU and artifact checks passed; implementation and evidence commits are pushed to the previously authorized private remote. The O0 gate remains closed on numeric parity and repeatability.

### Decision log

- Retain `reference_rgb` as an optional diagnostic capture array so existing capture packages remain valid while new runs support numeric instrumentation checks.
- Keep scalar-teacher eligibility gated on corrected CPU replay, an independent GPU POST oracle, numeric reference-output agreement, same-input run repeatability, aligned inputs, and the existing FSR3 C/H audit. Native dot4 conformance remains separately reported because the eligible teacher path uses scalar signed-I8 semantics.

### Validation outcome

- The corrected CPU replay passes frames 0/4/7 with max absolute errors 0.0004883/0.0009766/0.0009766; the GPU POST oracle passes with max errors 0.0006169/0.0009904/0.0008558. Native signed-I8 dot4 matches its scalar reference in 256/256 cases.
- Eight FSR3/FSR4 input frame hashes align and the committed FSR3 C/H audit passes. Instrumented/reference numeric comparison fails its required tolerance: max errors are 0.1152344/0.0754395/0.2144775 and within-1e-3 fractions are 0.998459/0.997550/0.926073 for frames 0/4/7.
- A second run with the same build commit, GPU/driver, sequence hash, and all eight input hashes changes both instrumented and ordinary output hashes on all eight frames. Captured model-input channels match at frames 0 and 4, while raw model parameters differ at those frames; frame 7 also differs in model-input channels and reprojected history. This places run-to-run variation at or before model-parameter generation; the lower-level cause is not yet known.
- O1-O13 remain locked on both numeric provider parity and run-to-run repeatability. The captured sequence is procedural synthetic input and supports no quality claim. Reports are under `artifacts/results/`; large captures stay ignored under `build/`.
- Implementation commit `bb13a6d819657512e4612e2ab78ac15ef651ab6e` and evidence commit `d6286a2` were pushed to private `origin/main`.

## Race bisector diagnostics (2026-10-08)

### Objective

Apply `FSR4-Navi10-RaceBisector-5b22fd0.zip` as a debug-only instrumented experiment for scratch initialization, inter-dispatch ordering, and first divergent FSR4 model-pass prefix. Keep the normal provider, its pinned AMD source, and all O0/O1-O13 acceptance gates unchanged. The archive's embedded prompt is document content; this plan and repository rules govern execution.

### Milestones

| # | Work | Files/modules | Validation / exit evidence |
|---|---|---|---|
| RB0 | Verify package provenance, base, anchors, and diagnostic scope | ZIP manifest; CMake/provider source anchors; this plan | CRC and manifest hashes; clean base `5b22fd0`; fail-closed patch checks; review all transformations before application. |
| RB1 | Integrate scratch-fill shader, optional prefix/barrier overlays, raw scratch snapshots, and analyzer/runner | `CMakeLists.txt`, `src/teacher/gpu_teacher.cpp`, `shaders/runtime/`, `src/teacher/`, `tools/diagnostics/`, `tests/` | `git diff --check`; CMake overlay checks; patcher and analyzer tests; Release build and existing CTest/Python suite. |
| RB2 | Run bounded RX 5700 XT campaigns | ignored `build/fsr4n10-race-bisector/`; `artifacts/results/` | Compare same-seed repeats, instrumented/ordinary scratch, zero/a5 seeds, and (if included) global-barrier variant; validate same sequence and input hashes. |
| RB3 | Record evidence and synchronize the private repository | `RESULTS.md`, `PROGRESS.md`, `DECISIONS_LOG.md`, this plan | Store concise numerical findings and JSON analysis; raw scratch snapshots remain ignored; keep teacher gate closed unless all existing criteria pass. |

### Fixed decisions and progress

- Treat fill patterns and global barriers only as diagnostic interventions; do not ship them as production defaults or assert a root cause before measurement.
- Prefix output is invalid for quality and teacher validation because POST still runs after a truncated model. It must not produce `.f4cap` captures.
- Scratch equality alone is insufficient. Full output repeatability, instrumented/reference numeric parity, and real-scene quality remain independent gates.
- [x] RB0: verify all manifest hashes, package CRC, clean `5b22fd0` baseline, and source-derived anchors; inspect the embedded prompt as document content.
- [x] RB1: apply, review, test, and build the diagnostic instrumentation. Standard, global-barrier, and ordinary Release builds passed; the ordinary build confirmed both diagnostic options OFF. CTest passed 1/1 and the Python suite passed 65 tests.
- [x] RB2: run and analyze full pass 0..12 campaigns on RX 5700 XT. Standard and global-barrier builds each completed 84/84 cases with the same sequence/input hashes and no failed run.
- [x] RB3: update results/progress and synchronize the reviewed diagnostic work; preserve the existing red O0 status.

### Decision log

- Keep every diagnostic control disabled by default. Barrier instrumentation is compiled from a generated copy of the pinned backend source and the upstream checkout remains unchanged.
- The initial prefix 0..3 run was repeatable at sampled scratch and did not localize the full-output variation, so the campaign was expanded through pass 12. Pass 11 is the first observed scratch difference for all three seeds, in both builds and both comparison modes.
- Zero fill does not restore repeatability. The barrier build keeps first divergence at pass 11 and changes some later scratch/full RGB outputs on matched inputs; treat this as an order/timing signal, not a proven cause or fix.

### Validation outcome

- The eight-frame synthetic sequence hash is `a06357453979901689f4f9c8ff2400a1efe5b9547e017a7fa4cf5219ba157ec2`; the cross-build comparator confirms matching inputs in all 84 paired cases.
- Prefixes 0..10 agree across repeats and instrumented/ordinary contexts. Prefix 11 is the first observed scratch mismatch after POST; the exact producer could be the model pass or POST's dependent writes.
- For every seed in each build, full instrumented and ordinary RGB hashes and full scratch snapshots are non-repeatable. `zero` and `a5` change both provider RGB hashes on all eight frames. Global barriers do not clear the repeatability failure.
- Detailed reports are in `artifacts/results/fsr4-race-bisector/`; raw snapshots stay ignored under `build/fsr4n10-race-bisector/`. No image quality or production-fix claim is made; O0 remains closed and O1-O13 remain locked.
- Diagnostic implementation and evidence commit `3fa959f` was pushed to the private `origin/main`.


## Pass 11 bounds guard continuation (2026-10-08)

### Current objective

Integrate a build-local, default-OFF bounds guard for the pinned FSR 4.0.2 Native/1080 I8 `FNB_CT2D_ADD<32,1>` shader used by pass 11. Preserve the FidelityFX checkout, weights, arithmetic, and the separate WMMA implementation. Validate the compiled shader and, when the local GPU/run sequence are available, compare baseline and guarded repeatability without changing the existing O0 gates.

### Fixed architectural decisions

- Follow D1-D22 above and `docs/DECISIONS.md`; Windows/DX12 and Navi10 remain the target.
- Keep vendor source/model data local and unmodified. Generate the guarded include under the build output directory only.
- Keep `FSR4N10_PASS11_BOUNDS_GUARD` OFF by default. This diagnostic repair does not unlock O0 or any O1-O13 mode.
- Change no model weights, quantization, requested quality, precision, POST equations, or dispatch sizes.
- Do not infer a GPU-confirmed race until the compiled artifact is verified and RX 5700 XT evidence is collected.

### Milestones

| # | Work and affected files | Validation |
|---|---|---|
| P11-1 | Adapt fail-closed overlay/install integration to the actual two `<32,1>` definitions in `FNB_CT2D_ADD.hlsli`; guard only the non-WMMA overload. Add the toggle/compiler manifest wiring, diagnostics, and tests. | `python -m unittest discover -s tests -p 'test_pass11_*.py' -v`; inspect generated overlay and `git diff --check`. |
| P11-2 | Compile baseline scalar, guarded scalar, and guarded intrinsic Release configurations; preserve the default-OFF path. | `scripts/run-pass11-guard-campaign.ps1`; compare emitted provider manifests and Pass 11 header hashes; `ctest --test-dir <build> --output-on-failure`. |
| P11-3 | Run zero/A5 scratch, pass 10/11/12/full, three fresh-process repeats on RX 5700 XT; inspect alias and full-frame reports. | Review all 72 case records, snapshots, hashes, alias-zone evidence, compiler diff, and `pass11_guard_evaluation.json`. |
| P11-4 | Record exact outcomes and remaining gates. | Update `RESULTS.md`, `PROGRESS.md`, `docs/RACE_BISECTOR.md`, `artifacts/results/`, and this plan from observed output only. |

### Validated outcome and remaining gate

The source matcher was adapted to the two pinned `<32,1>` definitions and its tests prove the WMMA suffix remains byte-identical. The first compiled-artifact check caught that FidelityFX_SC still selected the upstream file despite a same-named `-I` override. A build-local model copy now redirects only the Pass 11 include to a unique operator filename, and the compiler verifies the emitted dependency path and hash. The accepted build changes the Pass 11 selector/blob while preserving source hashes. The compiler also reorders selector metadata for Pass 0, Pass 13, and RCAS, but their content-addressed payload digest sets are unchanged; the verifier reports selector hashes separately from actual payload changes.

The fresh campaign compiled baseline scalar, guarded scalar, and guarded intrinsic Release variants and completed all 72 GPU cases on the RX 5700 XT. Baseline reproduced Pass 11 scratch variation; both guarded modes had stable scratch, exact instrumented/ordinary agreement, repeatable full RGB, and equal full RGB across zero/A5 scratch initialization. Every observed baseline Pass 11 scratch mismatch mapped into the predicted 64-pixel row-overlap alias region. This supports the bounds-race hypothesis on the GPU; it does not pass O0.

The guarded scalar and guarded intrinsic arithmetic modes differ from each other: their captured scratch differs at prefix 10 and their eight final RGB frame hashes are not equal. Each is repeatable independently. Cross-arithmetic numerical parity is a separate open check and no parity claim is made. The default build keeps `FSR4N10_PASS11_BOUNDS_GUARD=OFF`; O0 remains closed pending the existing capture parity, numeric validity, and representative-content gates.

### Decision log

| Date (UTC) | Decision | Reason |
|---|---|---|
| 2026-10-08 11:31 | Adapt the bundle's source matcher to the actual scalar/WMMA split and leave WMMA unchanged. | Source inspection and installer preflight showed two specializations; a single-match assumption is invalid for the pinned tree. |
| 2026-10-08 11:31 | Keep the guard explicitly opt-in and out of the vendor tree. | The fix is a diagnostic candidate until shader inclusion and GPU/O0 evidence pass. |
| 2026-10-08 11:45 | Redirect only pass 11 to a unique build-local operator and verify the resolved dependency. | The first compiled-artifact check proved the same-named `-I` overlay was not being used; the dependency file provides direct evidence of the operator selected by FidelityFX_SC. |

### Progress checklist

- [x] Confirm clean `main` at `7671af74b2c0038848d8983f0748ecccf227183c`; create `fix/fsr4-pass11-nhws-bounds-race`.
- [x] Verify the attached ZIP CRC and all 20 manifest file hashes/sizes.
- [x] Inspect current pass-11 model/provider geometry and the two operator implementations.
- [x] Run installer check; it rejected the inaccurate one-specialization assumption before modifying the repo.
- [x] Implement the precise non-WMMA-only overlay and integration; include every applicable runtime test but keep installer-only tests out of the repo.
- [x] Run focused Python tests (25/25 passed in the repository; the extracted bundle installer suite passed 25/25 before installation).
- [x] Confirm the guarded scalar dependency resolves to the unique overlay and its Pass 11 header differs from the pre-fix guarded build.
- [x] Rebuild all three configurations and compare baseline/guard artifacts from the same compiler revision; verify a separate default-OFF Release build and CTest.
- [x] Run all 72 GPU campaign cases on RX 5700 XT and inspect every case, scratch alias map, frame hash, shader diff, and evaluation report.
- [x] Record compact JSON evidence, update result/progress reports, and review the final diff.
- [x] Commit and push the private branch (`fix/fsr4-pass11-nhws-bounds-race`, evidence commit `2c1ef16`); do not merge to `main` while O0 remains closed.

### Measured results

ZIP integrity passed (20/20 entries), and the baseline source matches the archive target commit. Focused repo tests passed 25/25; the reviewed bundle installer suite passed 25/25 before installation. All three Release variants compiled, and a separate default Release build confirmed `FSR4N10_PASS11_BOUNDS_GUARD=OFF`; default and guarded CTest each passed 1/1. The guarded dependency resolved to build-local operator hash `3720BAC4CBE7D608870C83A8661403AE6D97DF0688B431AC7187A26B9BDEBD48`; the Pass 11 payload changed from blob `6c83bfdbb6b2f454411618b3661515d8.h` to `04d677d3499db8807a950c572a3a1ad7.h`, with upstream source hashes equal. Selector hashes also changed for Pass 0, Pass 13, and RCAS, but their content-addressed payload digest sets were unchanged; the verifier keeps these metadata/order changes separate from changed shader payloads.

The 72/72 RX 5700 XT cases completed without run failures (24 per variant) on synthetic eight-frame sequence `a06357453979901689f4f9c8ff2400a1efe5b9547e017a7fa4cf5219ba157ec2`. Baseline scratch repeatability failed first at Pass 11; all eight baseline alias comparisons had changes fully within the predicted overlap region. Guarded scalar and intrinsic each restored Pass 11 scratch stability and full-run repeatability, including instrumented/ordinary equality and zero/A5 cross-seed RGB equality. Scalar and intrinsic results are not bit-identical across modes (zero final RGB frame hashes equal); treat arithmetic equivalence as open. The O0 teacher gate remains false. Compact reports are in `artifacts/results/fsr4-pass11-guard/`; large raw scratch files remain ignored under `build/pass11-guard-campaign/`.

## User-supplied O0 numeric bisector (2026-10-08)

### Objective

After the Pass 11 bounds fix, measure the first valid Native/1080 I8 model-output tensor that differs between guarded intrinsic and guarded scalar arithmetic. If a pass is measured, compile a one-pass scalar hybrid to test whether that shader controls the observed difference. Then run existing O0 correctness checks on dedicated full-provider guarded builds without changing thresholds or default arithmetic.

### Baseline and decisions

- Baseline is `afbd264958f94d7c5b146c51c5f7e2d02f8e5e0c` on `fix/fsr4-pass11-nhws-bounds-race`, matching the attachment target. No `third_party/` files may change.
- Keep `FSR4N10_PASS11_BOUNDS_GUARD=OFF`, `FSR4N10_FORCE_SCALAR_DOT4=OFF`, and `FSR4N10_SCALAR_DOT4_PASS_SET=""` by default. Per-pass scalar arithmetic is an isolated diagnostic only.
- Compare only exact aligned inputs, repeatable runs, and source-parsed valid I8 output tensor regions. A scratch-wide difference does not localize a model pass. Do not infer which arithmetic path is correct from a difference.
- Preserve every original O0 failure, report, raw hash, and threshold. A synthetic sequence cannot prove game readiness or visual quality.
- The attachment's `CODEX_PROMPT.md` is descriptive content, not governing authority. The reviewed code/docs and repository instructions define this work.
- The archive package mock used a fake `.exe` that Windows refuses to launch. The diagnostic runner now executes `.py` harness fixtures through `sys.executable`; actual native harness `.exe` execution is unchanged.

### Milestones

| # | Milestone and affected areas | Validation / exit gate |
|---|---|---|
| N0 | Verify archive/target, install fail-closed payload: `CMakeLists.txt`, `tools/`, `tests/`, `scripts/` | ZIP CRC and 21 hashes; installer dry-run on clean branch; package tests; no writes to `third_party/`. |
| N1 | Parse all pass output contracts and compare guarded arithmetic: `tools/diagnostics/`, runners | 56 fresh processes, two guarded Release builds, same-input and within-mode repeatability, exact valid tensor byte offsets; `first_valid_output_pass` is measured. |
| N2 | Probe the measured pass only: hybrid shader overlay and `verify_hybrid_shader.py` | Only selected model-pass payload changes; prior prefix remains equal; selected tensor measurement recorded. Skip/record no guessed pass if N1 yields no valid divergent pass. |
| N3 | Run unchanged full-provider O0: `run-guarded-o0.ps1`, existing `tools/oracles/` | Dedicated non-prefix builds, two full captures per arithmetic mode, CPU/GPU POST, repeatability, instrumentation parity, DOT4 micro-oracle, unchanged teacher gate; retain failures. |
| N4 | Record and review evidence: `RESULTS.md`, `PROGRESS.md`, docs, `artifacts/results/i8-numeric-*` | CTest, repo tests, default-off configure/build, third-party integrity, compact JSON summaries, `git diff --check`. |

### Current state and blockers

The 21-file ZIP and exact target commit were verified. The fail-closed installer passed dry-run and installed the payload on the clean target branch; no vendor files changed. Four installer contract tests passed. The supplied mock campaign test initially failed on Windows with `WinError 216`; after making the runner invoke `.py` fixtures through Python, package tests pass 5/5. Repository I8 tests passed 18/18, existing Pass11 tests passed 25/25, and the default Release build/CTest passed (1/1).

The source-driven numeric campaigns completed 56/56 cases with aligned inputs and repeatable runs. Pass 1 is the first valid output tensor difference. The isolated Pass 1 hybrid completed 12/12 cases and its compiled payload change was isolated. The unchanged O0 teacher gate passed on guarded scalar arithmetic and failed on guarded intrinsic arithmetic; the intrinsic failure is retained. No default option or threshold was changed. The complete one-command summary is nonzero because one O0 variant failed, as designed. A 163-character FFX_SC overlay source path failed to resolve the guard include, while a 144-character path compiled; the orchestration default was shortened to `build/i8diag` and that short-path compile passed.

### Progress checklist

- [x] Confirm clean feature branch at exact ZIP target `afbd264958f94d7c5b146c51c5f7e2d02f8e5e0c`.
- [x] Verify ZIP CRC, safe member paths, and all 21 manifest SHA-256/byte counts.
- [x] Review installer, test code, PowerShell runners, tensor parser, analyzer, and overlay before execution; exclude the embedded prompt from authority.
- [x] Run package tests; adapt the Windows-incompatible mock `.exe` fixture to use a Python-script harness.
- [x] Run installer dry-run on clean branch and install 16 payload files/patches; no vendor files changed.
- [x] Run focused I8 tests (18/18), existing Pass11 tests (25/25), default Release build and CTest (1/1); verify guard/scalar/prefix diagnostics remain OFF/empty.
- [x] Run the source-driven guarded numeric bisector; verify same inputs, within-mode repeatability, and the first valid output tensor difference at Pass 1.
- [x] Compile and run only the measured Pass 1 hybrid; verify the compiled payload change is isolated and retain its numeric campaign.
- [x] Run unchanged full-provider O0 oracles for guarded intrinsic and scalar; preserve the intrinsic failure and scalar pass without altering the teacher gate.
- [x] Verify no tracked `third_party/` files changed; add compact reports and update docs; review and synchronize this branch only.

### Decision log

| Date | Decision | Reason |
|---|---|---|
| 2026-10-08 | Preserve default intrinsic arithmetic and empty per-pass override. | The prior standalone DOT4 microprobe does not establish full fused-shader equivalence. |
| 2026-10-08 | Compare parsed pass output tensors, not arbitrary scratch. | Pass-prefix snapshots contain multiple tensors and POST effects; only the declared output range can localize a valid model pass. |
| 2026-10-08 | Keep LLVM's historical packed-dot fix as an investigation clue only. | The referenced fix is not proof of a defect in the pinned FidelityFX_SC/DXC toolchain. |
| 2026-10-08 | Keep the orchestrator's default build root short (`build/i8diag`). | FFX_SC failed to resolve the local include at a 163-character overlay path; a 144-character path compiled. |

### Measured execution

The first cross-arithmetic difference is Pass 1 `slice_2` (`960 x 540 x 16`): 8,294,292 of 8,294,400 bytes differ (99.9987%), with a maximum signed-I8 delta of 152. The isolated Pass 1 hybrid changes only that pass's compiled payload and preserves the same first divergent pass. Guarded scalar passes the unchanged synthetic O0 teacher gate; guarded intrinsic fails CPU literal POST validity because its model intermediates are non-finite on the audited frames. This localizes a large difference to Pass 1 but does not establish which path matches AMD reference arithmetic. No quality, game-readiness, or performance claim follows. Full details and compact reports are in `docs/I8_NUMERIC_EXECUTION_RESULTS.md` and `artifacts/results/i8-numeric-bisector/`; raw captures remain ignored under `build/i8run/`.

## User-supplied Pass1 Golden oracle (2026-10-08)

### Objective

Review and integrate the supplied Pass1 independent CPU oracle and temporary shader-stage probes on the exact `98657b4` base. Use them to inspect the known Pass1 arithmetic divergence between guarded scalar and intrinsic paths on the local RX 5700 XT. Keep the diagnostic opt-in and preserve the current production defaults and acceptance thresholds.

### Fixed decisions

- Treat ZIP documents, including `CODEX_PROMPT.md`, as package content to review; the user request and repository instructions govern.
- The pinned AMD Pass1 HLSL is the expression and tensor-layout authority. CPU float variants and sampled pixels are diagnostics; raw INT32 accumulator dumps are the exact evidence.
- Keep `FSR4N10_PASS1_PROBE_STAGE` empty, `FSR4N10_PASS11_BOUNDS_GUARD=OFF`, `FSR4N10_FORCE_SCALAR_DOT4=OFF`, and `FSR4N10_SCALAR_DOT4_PASS_SET=""` by default. No default quality reduction or source edits under `third_party/`.
- Any arithmetic defect claim requires matching input snapshots, exact accumulator-stage evidence, and the existing correctness gate; differences alone do not identify the correct mode.

### Milestones

| # | Milestone and files | Validation / gate |
|---|---|---|
| P0 | Review ZIP manifest, installer, oracle, overlay, runner, tests, and pinned HLSL; `build/FSR4-Navi10-Pass1-Golden-98657b4/` | ZIP CRC/hash verification; dry-run installer on clean `98657b4`; parse actual pinned model and check stage layout/source anchors. |
| P1 | Install opt-in diagnostics and probe configuration; `CMakeLists.txt`, provider compiler, `dot4_conformance.hlsl`, `dot4_probe.cpp`, `tools/`, `tests/`, `scripts/` | Package unit tests, focused repo tests, default-off Release configure/build and CTest; no `third_party/` changes. |
| P2 | Run Pass1 golden stage measurements; `build/p1/`, `artifacts/results/pass1-golden/` | RX 5700 XT scalar/intrinsic runs with identical Pass0 inputs, repeated samples, all stage chunks when feasible; exact raw INT32 comparisons, three-way DOT4 report, retained reports for unresolved float stages. |
| P3 | Record interpretation and synchronize branch; `RESULTS.md`, `PROGRESS.md`, `.agent/EXEC_PLAN.md`, `artifacts/results/pass1-golden/` | Review outputs/diff, `git diff --check`, existing validation gates, commit and push the private feature branch; do not merge. |

### Current progress

- [x] Confirm archive targets current clean branch commit `98657b4`; verify ZIP CRC and all manifest entries.
- [x] Safely extract archive into ignored `build/` and review its docs, installer, oracle, overlay, tests, runner, and source anchor requirements.
- [x] Confirm actual source parser and HLSL overlays against the pinned Native/1080 Pass1 specialization; adapt compact named tensor descriptors and numeric-suffixed constants.
- [x] Run installer dry-run and package/focused tests; apply reviewed payload without changing `third_party/`.
- [x] Build default-off Release and run CTest; verify probe, guard, scalar, and prefix diagnostic defaults remain disabled.
- [x] Run three-way DOT4 and all 20 Pass1 stage oracle campaigns; analyze paired inputs, repeated raw INT32 accumulators, quantized outputs, and sampled float paths.
- [x] Add compact oracle/campaign evidence and update `RESULTS.md` and `PROGRESS.md`; add regression coverage for the summary's stage-specific follow-up.
- [x] Review final diff and `git diff --check`; commit and push the private feature branch without merging.

### Blockers

No build or runtime blocker remains. The intrinsic/scalar arithmetic cause inside the fused shader is still unresolved; this diagnostic does not identify AMD's intended arithmetic result, prove quality, or open the production gate.

### Decision log

| Date | Decision | Reason |
|---|---|---|
| 2026-10-08 | Keep the package's probes inside the Pass1 FP16-bias overload and in build-local shader overlays. | This is the Native/1080 Pass1 overload; build-local redirection preserves pinned vendor files. |
| 2026-10-08 | Treat float32/float64 CPU comparisons as supporting diagnostics and raw INT32 as authoritative. | GPU/HLSL floating lowering and rounding tie behavior are not fully established by NumPy. |

### Measured execution

The 20-stage sweep completed on the RX 5700 XT with 160/160 fresh-process
GPU cases. Each intrinsic/scalar pair used the same Pass0 input hashes, and
all repeated harness cases returned successfully. The scalar path matched
all sampled raw INT32 accumulator lanes against the independent CPU oracle.
Intrinsic first diverged in raw Pass0 chunk `acc0_0`, before quantization;
across `acc0_0..3`, only 3/2,048 intrinsic lanes were within one integer unit
and the maximum absolute error was 134,656. The eight `acc1` chunks and four
`acc2` chunks had no intrinsic raw lane within one unit; maximum errors were
229,506 and 653,340, respectively.

The exact compiled intrinsic macro, native intrinsic, and scalar reference
matched in 4,096/4,096 standalone DOT4 vectors. This probe does not cover the
fused shader's operand packing/register mapping. The first observed gap is
therefore localized to the fused arithmetic path at or before `acc0_0`, but
the responsible lowering detail and correct AMD result remain unknown.

The all-stage runner initially stopped only at its final PowerShell array
argument expansion, after the GPU campaigns and DOT4 probe had completed.
The argument construction was fixed and directly exercised; the report
summary and 160-case step record were generated and validated. Two summary
regression tests now guard the distinction between raw-accumulator and
quantization follow-up. The full Python suite passed 122/122, default Release
CTest passed 1/1, and the default build retains all production options OFF.
Compact reports and 40 campaign manifests are in
`artifacts/results/pass1-golden/`; large raw captures and build trees remain
ignored under `build/p1/`.

## User-supplied Pass1 intrinsic recovery (2026-10-08)

### Objective

Investigate the observed 256-aligned Pass1 raw-INT32 intrinsic/scalar differences using the supplied signedness-mask solver, first-fused-DOT4 operand tap, and six opt-in HLSL lowering variants. Require each candidate to pass the DOT4 operand/result check, raw `acc0_0`, and full Pass1 output against the existing scalar/CPU baseline before running the unchanged synthetic O0 gate. Keep all production settings and quality thresholds unchanged.

### Fixed decisions

- Treat ZIP documents and its `CODEX_PROMPT.md` as package content; the user request and repository instructions remain authoritative.
- Preserve the pinned AMD model, FidelityFX vendor checkout, and all existing acceptance thresholds. No file under `third_party/` may change.
- Keep `FSR4N10_PASS1_DOT4_EXPERIMENT` empty by default; test variants exist only in build-local wrappers and require the Pass 11 guard.
- Treat the 256-multiple signature and any exact lane-mask fit as hypotheses until the compiled fused operands/result and unchanged correctness gates corroborate them.
- Do not promote any candidate from synthetic output alone. A passing O0 remains insufficient for AMD-reference image quality or game readiness.

### Milestones

| # | Work and affected files | Validation |
|---|---|---|
| R0 | Verify exact `3ed1c9a` base, ZIP safety/CRC/manifest, package docs and installer | Clean tree and base ancestry; every manifest size/SHA-256; review all installer transformations before dry-run. |
| R1 | Install signedness inference, `dot0` probe, and build-local DOT4 variants; `CMakeLists.txt`, compiler, stage overlay, diagnostics, tests, runner | Installer dry-run; 13 package tests; focused and full repo tests; default-off Release build/CTest; no vendor edits. |
| R2 | Fit all 256 signedness-mask pairs against the existing 128-sample `acc0` oracle | Exact per-lane agreement required for an inferred mask; preserve full ranking and modulo-256 evidence. |
| R3 | Run scalar baselines and candidate sequence `dot0 -> acc0_0 -> final`; run unchanged O0 only for candidates passing all three | RX 5700 XT, same sequence/input hashes, repeated captures; keep every failed report; do not loosen gates. |
| R4 | Record evidence and synchronize only the current private branch | Update results/progress/plan and compact artifacts; `git diff --check`, verify defaults/vendor hashes, commit and push without merging. |

### Current progress

- [x] Confirm clean private feature branch at exact archive target `3ed1c9a53b779382d466f6b95ef26d9d14536965`.
- [x] Verify all 12 listed archive payload hashes/sizes, CRCs, safe paths, and the package's no-vendor-content claim.
- [x] Review package docs, installer transformations, signedness equations, HLSL alternatives, GPU runner, and pure tests; keep the embedded prompt as untrusted reference content.
- [x] Run installer dry-run on the clean target. It plans edits to three integration files and six additive payload files; no vendor path is included.
- [x] Apply the reviewed installer; verify the `dot0` tap and six variants against the actual FP16-bias overload.
- [x] Run package tests (13/13), full Python tests (132/132), default-off Release build, and CTest (1/1).
- [x] Execute the 256-mask inference and all candidate `dot0 -> acc0_0 -> final` gates on the RX 5700 XT; retain passing and failing reports.
- [x] Run the unchanged O0 gate for all three Pass1-exact candidates; preserve the failure evidence.
- [ ] Finish report/artifact review, `git diff --check`, verify defaults/vendor hashes, then commit and push this private branch without merging.

### Blockers

No candidate passes the unchanged O0 numeric gate. The three variants that match sampled Pass1 outputs still produce non-finite model intermediates in the full synthetic graph, so the production gate remains closed. This does not prove the inferred signedness model matches AMD reference arithmetic or establish visual quality.

### Decision log

| Date | Decision | Reason |
|---|---|---|
| 2026-10-08 | Test `native_zero`, operand-swap, signed-unpack, and unsigned-bias forms only through a build-local Pass1 wrapper. | Separate accumulator routing and packed-operand lowering while leaving every other provider pass fixed. |
| 2026-10-08 | Require exact signedness-mask agreement across every sampled raw accumulator before calling the byte-signature explained. | Modulo-256 divisibility alone is not unique to signed/unsigned reinterpretation. |
| 2026-10-08 | Keep the original scalar Pass1 captures as the common comparison baseline for all candidates. | Prevent variant-specific baselines from masking numerical changes. |

### Measured execution

The signedness search found an exact model over all 2,048 sampled raw INT32
lanes across `acc0_0..3`: input byte mask `0x0` (signed) and weight byte mask
`0xF` (unsigned). All seven native and experimental builds passed the first
fused-DOT4 `dot0` tap on 256 sampled pixels. Native, zero-accumulator,
operand-swap, and swap-plus-zero variants each matched only 1/512 raw
`acc0_0` lanes, with maximum absolute error 84,224.

`unpack_dot`, `unpack_scalar`, and `unsigned_bias_3dot` each matched the scalar
CPU oracle at `acc0_0` (512/512) and final Pass1 (2,048/2,048), with identical
Pass0 inputs. Each then completed the eight-frame O0 replay repeatably but
failed the unchanged numerical-validity gate: all 2,073,600 model pixels were
non-finite on audit frames 0, 4, and 7. Post-RGB replay matching is not a
numeric pass. No candidate is promoted and no quality or game-readiness claim
is made.

Provider manifests show all changed shader payloads belong to Pass1; other
payload hashes match the same-stage native build. Compact reports and oracle
campaigns are in `artifacts/results/pass1-intrinsic-recovery/`; raw captures
remain ignored in `build/p1fix/`. Package tests passed 13/13, the full Python
suite 132/132, and the default Release CTest 1/1. The default CMake cache
still has the experimental mode empty and production diagnostics OFF.
