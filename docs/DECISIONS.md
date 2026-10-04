# Fixed technical decisions

These decisions are intentionally pre-made so a weaker coding model does not waste the run redesigning the project.

## D1 — Scope
The project is only FSR4/Navi10 for now. Do not add KCD2, Witcher, OptiScaler game profiles, frame generation, driver mods, overclocking, ReShade, or unrelated shader optimization.

## D2 — Platform/API
Primary and required platform: Windows 11 x64, DirectX 12. HLSL/DXIL only for the production path. Vulkan is explicitly out of scope for this run.

## D3 — Target GPU
Primary target: Radeon RX 5700 XT, Navi10, LLVM/ROCm architecture name `gfx1010`. Optimize for this device even when that makes code less generic.

## D4 — Reference algorithm
FSR 4.0.2 is the behavioral/model reference because its source/model version is publicly recoverable from the AMD FidelityFX SDK 2.0.0 publication history. Do not invent a different network and call it FSR4.

## D5 — Current FSR 4.1.x
FSR 4.1.x is a signed-binary/API product in current AMD SDK documentation. It may be consulted for public API/documentation/reference behavior, but this project must not depend on redistributing or patching AMD's signed 4.1.x binary.

## D6 — Primary neural representation
The primary optimized implementation uses FP16 weights and FP16 activations, with true 16-bit HLSL types and packed/vectorized arithmetic where DXC/driver map them efficiently on Navi10.

## D7 — Numerical compatibility mode
`fp16_compat` preserves the model topology and the semantically important quantization/clamping boundaries of the original model even when arithmetic is carried out in FP16. It exists to achieve output close to the original reference.

## D8 — High-precision mode
`fp16_high_precision` keeps more intermediate state in FP16 and removes only provably redundant quantize/dequantize round-trips. It is allowed to differ numerically from the INT8 reference but must meet the quality/temporal gates.

## D9 — Hybrid production selection
The final production backend may select different implementations per neural pass. Full FP16 remains mandatory and must be complete. A pass may use original INT8 only when the automated local tuner proves that the INT8 shader is faster on this RX 5700 XT and its output is equivalent under the reference-quality gates. This protects against uncertain gfx1010 dot-product behavior.

## D10 — No quality cheating
Default performance wins may not come from deleting network layers, reducing feature channels, reducing output resolution, skipping temporal inputs/history, lowering preset quality behind the user's back, or disabling expensive passes. Optional experimental modes may do such things only if clearly named and never selected by default.

## D11 — Offline specialization
Prefer generated, model/preset/resolution-specific HLSL over a generic neural runtime. Runtime flexibility is less important than speed on a fixed model and fixed GPU family.

## D12 — Model assets
Original model assets remain under `third_party/` or are fetched/generated locally. The project's own generated FP16 packs go under `generated/model/`. Preserve provenance and hashes.

## D13 — Pass structure
Use the actual upstream provider/model as source of truth. Expected shape from existing public reference implementations is pre → model passes 1..12 → post, with optional SPD/RCAS around it. Never hardcode dispatch/tensor details until confirmed from the fetched source.

## D14 — Compiler
Use current stable DXC available locally. Compile production compute shaders with Shader Model 6.6, HLSL 2021, O3 and `-enable-16bit-types`, unless a specific upstream shader requires a stricter compatible profile. Record compiler version in build metadata.

## D15 — Wave policy
Generate wave32 and wave64 variants where legal/useful. Do not assume one always wins. The final tuner may select per pass. Wave32 is the initial default for Navi10 compute shaders.

## D16 — Resource policy
Use persistent preallocated scratch/history resources, reuse/alias memory only where lifetime analysis proves safety, and minimize UAV barriers without violating data dependencies.

## D17 — PSO policy
Compile shaders offline for release, build PSOs once per needed permutation, cache them, and avoid runtime shader compilation during normal gameplay dispatch.

## D18 — Validation
The original/reference path and optimized path must be executable in the same standalone harness against identical deterministic multi-frame inputs. Every pass can optionally dump intermediates for binary-searching divergence.

## D19 — Measurements
Performance claims come from GPU timestamps/end-to-end dispatch timings on the local RX 5700 XT. RGA/RGP/ISA data explains why, but is not a substitute for actual timing.

## D20 — Deliverable architecture
Produce four separable components:
1. `fsr4n10_core` — model/runtime/backend implementation.
2. `fsr4n10_harness.exe` — deterministic standalone validation/benchmark runner.
3. `fsr4n10_ffxapi.dll` — unsigned FSR API-compatible adapter for later integration experiments.
4. tools/generators — model conversion, shader generation, compilation, validation and packaging.

Do not overwrite AMD-signed binaries. An optional packaging helper may copy/rename the project's own DLL for a user-selected integration directory later, but core build output keeps distinct project names.

## D21 — NaviQSR is a separately named architecture family
The full dense FSR4 FP16 implementation remains mandatory as reference/correctness path, teacher, dense fallback, and benchmark baseline. Add `naviqsr_dense`, `naviqsr_analytic`, `naviqsr_mcld`, and `auto` as separate modes. Do not claim teacher parity, production readiness, or speedup until temporal quality and RX 5700 XT measurements pass. This decision supersedes only the older non-goal against training a new network or reducing topology.

## D22 — Treat QSSR reporting and this project's synthesis at their actual evidence level
Sony's public announcement supports only that QSSR uses a streamlined neural architecture and a PS5-tuned implementation. FP16/packed-math details are attributed to public reporting/interview excerpts, not Sony's announcement. NaviQSR/MCLD-AKR is a proposed project synthesis; do not describe it as Sony's implementation, as a wavelet/QSSR fact, or as a globally novel invention.

## D23 - Keep NaviPRISM as an independent primitive reconstruction path
Preserve full FSR4 and NaviQSR. Build `naviprism_filter`, sparse `naviprism_sadnet`, optional `naviprism_phase`, and quality-gated `auto` modes as described in `docs/naviprism/`. Treat SARM, THFA, and `msad4` speed as proposals until source-derived correctness, RX 5700 XT ISA, quality, and timestamp evidence are recorded.

## D24 - Use architecture names consistently
Call the compact neural path the NaviQSR network and the primitive/filter path NaviPRISM. Remove obsolete aliases from source, documentation, comments, and project history when the user requests the terminology change.
