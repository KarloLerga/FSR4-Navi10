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
| 3 | Build system and source-faithful harness: `CMakeLists.txt`, `cmake/`, `src/`, `include/`, `scripts/` | clean CMake Release and RelWithDebInfo configure/build; deterministic repeated reference sequence |
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
- Repaired `scripts/fetch-upstreams.ps1`: its `$Args` parameter collided with PowerShell's automatic variable, causing the documented fetch to fail.
- Verified Windows 11 build 26200, RX 5700 XT (PCI `1002:731F`), driver `32.0.21045.1000`, Git 2.51.2, CMake 4.3.3, Python 3.11.9, and Visual Studio C++ tools. Ninja and DXC are not yet available; bootstrap is pending.
- No project implementation, build, shader compile, quality run, or performance result has been completed yet.

## Blockers and resolution

- **Missing Ninja/DXC:** run the reviewed bootstrap, let it install the official packages, then record versions.
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
- [ ] Bootstrap and record the complete build environment.
- [ ] Build and validate reference harness.
- [ ] Implement and validate complete FP16 compatibility/high-precision paths.
- [ ] Implement tuning, adapter, packaging and finish review.

## Measurements

No model, shader, quality, stability, or performance measurements have been made. Record measured data in `RESULTS.md` and `artifacts/results/` as milestones complete.
