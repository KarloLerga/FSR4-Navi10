# NaviPRISM Results

This report records measured NaviPRISM behavior. It is separate from the full FSR4 and NaviQSR results in `RESULTS.md`.

## Environment checkpoint

Baseline commit `c1e54eb` on 2026-10-04:

- Release CMake build: passed.
- CTest: passed (1/1).
- NaviQSR Python reference suite: passed (6/6).
- Target GPU: AMD Radeon RX 5700 XT / PCI `1002:731F`.

## NaviPRISM evidence

The following checks ran on the RX 5700 XT with driver `32.0.21045.1000`. They validate isolated synthetic primitives and do not represent a complete upscaler or an FSR4 quality comparison.

| Gate | Status | Evidence |
|---|---|---|
| `msad4` scalar/reference semantics | Passed | 4,096 cases x 96 calls, including byte ordering, masks, encoding, and 48-call accumulation chunks; GPU outputs matched exactly. |
| Navi10 ISA inspection | Passed | AMD RGA 2.14.2.7 gfx1010 output contains `v_mqsad_u32_u8` in the `msad4` and SARM variants. Scalar-u8 and FP16 comparison variants do not contain that instruction. |
| `msad4` timing comparison | Measured | Median 287.665 us / p95 305.865 us; scalar-u8 288.654 us / 325.290 us; FP16 difference with FP32 accumulation 337.109 us / 354.919 us. Native intrinsic is near scalar parity in this workload. |
| SARM GPU/reference parity | Passed | Synthetic 64x48 image, 8x6 tiles, known residual translation `[1,-1]`; all 48 tiles valid and GPU output matches the scalar reference. Median 48.684 us / p95 67.294 us. |
| THFA shader/reference parity | Passed for synthetic atlas | 16x12 input to 32x24 output; 4/5/8/9-tap shader variants had errors below 1e-6 (JSON values are rounded to six decimals; validator gate is 2e-5). Median times were 0.928/0.953/2.199/0.975 us respectively. |
| THFA fitter and binary format | Implemented; unit-validated | Deterministic synthetic fitting, sparse-bucket backoff, FP16 packing, hash validation, and RGB capture-array conversion are covered by Python tests. The GPU report uses a deterministic synthetic atlas, not a teacher-fitted atlas. |
| Tile classifier/compaction | Passed for synthetic cases | Eight tiles produced expected route counts `[1,2,2,2,1]`; HARD list `[2,6]`, VERY_HARD list `[3,5]`. No downstream route is dispatched. |
| Phase history reservoir | CPU reference only | Reprojection, confidence/age, depth rejection, and reset behavior have reference tests; no GPU path or A/B quality test exists. |
| Teacher quality/performance | Open | No FSR4 teacher/native-HR capture sequence or full frame graph is available. |

Each timed validator used 5 warmups and 20 measured samples; each sample averaged 32 dispatches with resource barriers. The raw, machine-readable reports are `artifacts/results/naviprism_msad4.json`, `naviprism_sarm.json`, `naviprism_thfa.json`, and `naviprism_router.json`. These small synthetic dispatch timings are not full-resolution throughput or end-to-end performance.

The GPU router currently classifies and compacts tiles only. No SADNet or NaviQSR fallback, phase-history GPU path, scene/motion preprocessing, teacher capture, temporal image-quality metric, or game-frame integration is connected. The results establish primitive behavior and compiler selection; they do not establish that NaviPRISM is ready to use in a game or that it matches FSR4 image quality.
