# Results

## Environment

| Item | Observed value |
|---|---|
| OS | Windows 11 Pro, build 26200 |
| GPU | AMD Radeon RX 5700 XT, PCI vendor/device `1002:731F` |
| Driver | `32.0.21045.1000`, dated 2026-07-23 |
| Git | 2.51.2.windows.1 |
| CMake | 4.3.3 |
| Python | 3.11.9 |
| Visual Studio C++ tools | Visual Studio 18 Community present |
| DXC | 1.9.2602.17 (`dxcompiler.dll` 1.9, commit `21d28f727`) |
| Ninja | 1.13.2 |
| AMD FSR4 source | `01446e6a74888bf349652fcf2cbf5f642d30c2bf` |
| Current FidelityFX SDK | v2.3.0, `60f4ea81909200d8542eca14dccb2628b763a9a3` |

## Source inventory

The deterministic source inventory covers 12 model variants (6 presets x INT8/FP8 representations), 3 resolution tiers, 12 neural passes, pre/post model stages, 13 padding-reset entry points and locked initializer hashes. Two generated inventory files were byte-identical. Its parser/classification checks are part of the passing Python unit tests.

## Build and hardware capability probe

| Check | Result |
|---|---|
| CMake Release and RelWithDebInfo configure/build | Passed for current source in both configurations |
| `compile_fp16_probe` DXC `cs_6_6 -enable-16bit-types` | Passed |
| CTest `model_tools_unit_tests` | Passed (12 Python unit tests) |
| Harness `--list-adapters` | RX 5700 XT found as `1002:731f`; D3D12 yes, SM 6.8, wave ops yes (32–64 lanes), native 16-bit shader ops yes, binding tier 3 |
| Upstream I8 shader source compile | All 6 presets x 3 resolution tiers x entries 0-13: 252 DXIL outputs across 18 manifests using DXC `cs_6_6`; source initializers are copied beside each compiled variant and match manifest SHA-256 values. |
| Targeted compile reproducibility | Native/1080p manifests, all 14 pass hashes, and initializer hashes matched between Release and RelWithDebInfo outputs. |
| FP16 parameter conversion | Converted all 6 presets x 3 tiers: 18 combinations, 78 parameter tensors and 124,872 values per combination; 4,495,392 FP16 bytes total. Each combination has 38 quantized I8 weights, one native FP16 weight, and 39 FP16 biases. |
| FP16 model pack scope | Versioned `F4N10PK` containers wrap the parameter blobs with source/manifest SHA-256 values, tensor records, bounds checks, and 16-byte-aligned payloads. GPU loading/dispatch, runtime activations and pass bindings are not implemented. I8 expansion uses `f16(i8 * f16(scale))`; operator-specific scale boundaries and model output equivalence are unvalidated. |
| Model-pack reproducibility | `scripts/repro-check.ps1` generated two clean outputs for all 18 combinations; hashes of all 56 pass catalogs, manifests, raw blobs, containers and indices matched. |
| Upstream I8 pass contract catalog | Generated 18 contracts with 486 entrypoints, 486 source operator calls, and 2,178 tensor descriptors; HLSL hashes and argument expressions are preserved. Input/output direction and host dispatch dimensions remain unresolved. |
| C++ model-pack reader | Release and RelWithDebInfo builds passed; validated all 18 containers (78 records each) and rejected a 64-byte truncated file. |
| Upstream I8 full-chain GPU smoke | Release and RelWithDebInfo both dispatched source pass 0, all 12 neural passes, and pass 13 on synthetic zero 1920x1080x8 FP16 model-input features. Each produced 16,588,800 finite nonzero FP16 feature values. Not a real-frame or image-quality test. |
| Pinned FSR4 I8 provider build | Release static provider and harness linked with the native/1080 shader set from commit `01446e6a74888bf349652fcf2cbf5f642d30c2bf`; the capture build generated 350 reflected shader headers, including PRE, 12 model passes, 13 padding variants, POST capture variants, RCAS, SPD, debug view and watermark. |
| FSR4 provider D3D12 smoke | RX 5700 XT (`1002:731F`, driver `0x00200000523503e8`) executed two instrumented and one ordinary 1920x1080 RGBA16F reset dispatches. Instrumented, ordinary and repeated output SHA-256 all match: `304bc89ba22b08e4ab12b2d27458179b6cf7af4cc7d4a35e5ccfe864edaa7813`; tapped arrays repeat byte-for-byte. Raw p0..p3, seven semantic channels, current source, reprojected history, recurrent state, physical controls and final RGB were captured. The synthetic `.f4cap` package passes container/hash integrity checks, but later exact POST replay found non-finite reconstruction intermediates and black output; it is not numerically valid teacher-quality evidence. Raw JSON report: `artifacts/results/fsr4_provider_smoke.json`. |
| FP16 GPU arithmetic probe | Passed in Release and RelWithDebInfo: all 64 output half values matched expected products on the RX 5700 XT |
| FP16 DXIL inspection | `dxc -dumpbin` shows `fmul fast half` in the compiled probe |
| NaviQSR D3D12 frame graph | Release build dispatches nine network layers followed by temporal AKR/RGB reconstruction in one command list. Smoke cases cover 2x/3x/4x scaling, 4/5/8 taps, and reset/valid history; max control error 1.13e-5 and max RGB error 1.14e-6. Weights are FP16-stored; activations and accumulation are FP32. |
| NaviQSR earlier build coverage | The network-only smoke passed in Release and RelWithDebInfo before frame-graph integration. The current joined graph has been built and dispatched in Release. |
| NaviQSR AKR D3D12 smoke | 4/5/8-tap variants passed the bounded GPU/reference check on one 64x36 output in Release. |
| Full GPU-native FSR4 provider frame path | Pinned provider PRE/model/POST dispatches on the RX 5700 XT and instrumented RGB matches ordinary output byte-for-byte. Package integrity and repeatable taps are confirmed. However, exact POST replay reports non-finite model-color intermediates over nearly every pixel because raw p0..p3 exceed the source exponent range; the captured output is nearly all black. Numerical validity, real-scene sequence input, quality validation, temporal stress, and full-effect selection remain open. The separate experimental image smoke below still uses CPU preprocessing/postprocessing around the GPU I8 model graph. |
| FSR4 quality comparison, 10,000-run stability stress, end-to-end effect timing | Not run |
| NaviQSR PyTorch reference tests | 6 passed: reversible raw/Haar transforms, reparameterization fold, analytic reconstruction/reset, deterministic sequence generation, QRISP importer gates, and model-pack validation. |

The zero-feature model smoke checks only neural tensor execution. Neither smoke has been compared with the AMD reference image, and neither validates production GPU-native frame semantics, long-run stability, or full-effect performance.



## Experimental I8 image smoke

A deterministic synthetic 960x540 sRGB P6 PPM was generated with `tools/quality/generate_test_frame.py`. The image smoke ran two static frames: frame one resets history, and frame two reuses history and recurrent state. The 14 source I8 model entries execute on the RX 5700 XT; preprocessing and postprocessing use CPU code based on the upstream equations. The output is a 1920x1080 24-bit BMP. The Release output repeated byte-for-byte and matched RelWithDebInfo at SHA-256 `26CFF120972DA3939F202BD0296B5F540280F2F75AD235E2D814F8A9E29D96C6`. This is an integration smoke, not an AMD reference comparison, image-quality result, or production GPU-native frame path.

## Preliminary I8 model GPU timing

Measured with the native/1080p source shader graph on the RX 5700 XT. Each configuration ran 5 warmup iterations followed by 20 measured iterations; D3D12 timestamp queries bracket each of the 14 compute dispatches. Times are preliminary kernel timings for a synthetic zero model-input tensor, before the quality gate. They exclude barriers, CPU scheduling, real-frame preprocessing, temporal history preparation, and RGB image postprocessing. Do not interpret them as full FSR4 effect time or as a backend-selection result.

| Source entry | Release avg (us) | Release median (us) | RelWithDebInfo avg (us) | RelWithDebInfo median (us) |
|---:|---:|---:|---:|---:|
| 00 | 130.882 | 116.820 | 116.794 | 116.660 |
| 01 | 610.872 | 591.120 | 656.050 | 580.120 |
| 02 | 668.936 | 626.280 | 626.060 | 621.680 |
| 03 | 119.044 | 113.120 | 113.996 | 112.340 |
| 04 | 574.458 | 498.900 | 511.176 | 499.380 |
| 05 | 548.132 | 503.900 | 590.124 | 503.620 |
| 06 | 197.822 | 172.400 | 178.178 | 170.680 |
| 07 | 537.638 | 475.960 | 480.818 | 467.920 |
| 08 | 496.448 | 449.580 | 496.490 | 451.700 |
| 09 | 796.234 | 774.660 | 784.112 | 771.860 |
| 10 | 586.670 | 456.180 | 547.116 | 455.460 |
| 11 | 1242.038 | 1211.480 | 1249.476 | 1189.440 |
| 12 | 608.756 | 581.780 | 600.546 | 581.600 |
| 13 | 761.688 | 682.940 | 730.674 | 679.980 |

The sum of per-pass average kernel times was 7,879.618 us in Release and 7,681.610 us in RelWithDebInfo. It omits inter-dispatch barriers and all frame/image stages.

## NaviQSR research prototype

The addendum implementation is a separate network prototype; it does not replace or complete FSR4. DirectML was unavailable, so training used CPU. The initial 256-update run evaluated on the same 64-frame data used for training and is in-sample only: 21.0118 dB mean PSNR / 0.71248 global SSIM versus bilinear 20.9925 dB / 0.71233. A follow-up avoided that leakage: train manifest SHA-256 `54f99be7474ff7783da0fc1ada80d0e5001ca59b74b33118579c19ffc7ee4e3b` (8 sequences x 8 frames, seed 17), separate holdout manifest SHA-256 `e359ce11df9a349d6bbcdc0e8e50a6a2be54c611b789b60ee023301c3a9acca6` (4 sequences x 8 frames, seed 9001), and 4,096 CPU updates. On the 32-frame holdout, mean PSNR was 21.0219 dB and global SSIM 0.70981 versus bilinear 20.9377 dB / 0.70928; mean temporal warp error was 0.05430. The 0.0842 dB PSNR gain is not a meaningful quality result. This remains synthetic content and a tiny model. Global SSIM is an image-level summary, not windowed SSIM. The trained network and analytic reconstruction now run as a joined D3D12 smoke, but case generation still preprocesses and packs features on CPU.

Structural export validation on the 4,096-update checkpoint folded the 1x1 -> 3x3 -> 1x1 block with maximum control-map difference 1.52588e-5 (configured tolerance 2e-5); the residual output difference was 0. The FP16 model pack validated 14 tensors, 9,056 payload bytes, and SHA-256 `310f3eaa82301dc6490d4ad3e740fe86b0feba1be9434792f7d52c43b7033303`. This checks packing and structural equivalence; it is not evidence of GPU network inference or FP16 image-quality parity.

### Analytic reconstruction GPU smoke

The 4-, 5-, and 8-tap analytic reconstruction variants compile with DXC and dispatch on the RX 5700 XT. Each compared a 64x36 output against the PyTorch reference from one LR 32x18 procedural frame. The remaining nonzero difference is consistent with GPU/CPU sampler and arithmetic precision; it is not bit-exact parity, and the test does not isolate the source of the error.

The isolated dispatch timings below used 5 warmups and 20 timestamped measurements after PSO creation. They cover only one tiny 64x36 AKR dispatch; they exclude uploads, PSO creation, readback, CPU waiting, network convolutions and the full frame graph. These figures are a microbenchmark, not an output-resolution performance result or a sparse/dense break-even claim. Driver was `32.0.21045.1000`; GPU PCI ID was `1002:731F`.

| Taps | Max abs error | Mean abs error | Min (us) | Median (us) | P90 (us) | P95 (us) | DXIL SHA-256 |
|---:|---:|---:|---:|---:|---:|---:|---|
| 4 | 0.00452450 | 0.00160213 | 0.28 | 0.74 | 1.80 | 1.80 | `c843e2f22af9c40cc22b31b43f03461b0f0f255f8fe3e8e1e92c43f2aea7be77` |
| 5 | 0.00455061 | 0.00172507 | 0.28 | 0.74 | 1.00 | 1.80 | `eee7f3508ba593f17a447b8c8ab887dedf7a38efc2767b67c9242bf3c6580bf5` |
| 8 | 0.00452298 | 0.00161305 | 0.28 | 0.74 | 1.96 | 2.12 | `4bfa7f2036a3a6140d215816bfbf78fe324f41a0556426b329e481b6d8e634f1` |

The full network runtime still lacks direct `.nqsrpack` loading and GPU-side game-frame preprocessing. FSR4 teacher capture, sparse MCLD, reset/stability stress at 10,000+ dispatches, and useful quality/performance selection remain incomplete. No NaviQSR production claim is made.

### Network convolution GPU smoke

The exported 4,096-update checkpoint ran all 9 network convolution/pool-concat layers on the RX 5700 XT. Its 5,096 model weight/bias elements are stored as FP16 and read from a packed D3D12 raw buffer; activations and multiply-accumulate operations are FP32. GPU controls/residuals matched a PyTorch reference using the same FP16-quantized folded parameters. Maximum/mean absolute error was 4.57e-6 / 3.73e-7 at LR 32x18 frame 1, 9.54e-6 / 5.24e-7 at LR 32x18 frame 7, and 1.12e-5 / 5.31e-7 at LR 64x36 frame 2. This validates the smoke graph's convolution results, not true FP16 arithmetic or a production pack loader.

The next table times the 9-layer network convolution/pool-concat graph with 5 warmups and 20 timestamped measurements. The timestamps exclude PSO creation, input/model upload, CPU waiting, and readback. They include the inter-layer resource transitions. Results vary between runs and cover only these tiny LR inputs; they do not imply full-resolution frame time or quality-qualified performance. GPU was RX 5700 XT (PCI `1002:731F`), driver `32.0.21045.1000`; network convolution DXIL SHA-256 `579b9546895b56da6755d0a5b31552fb828596ec84e9dacbfa73fca57b342bae`.

| LR input | Control/residual grid | Min (us) | Median (us) | P90 (us) | P95 (us) |
|---:|---:|---:|---:|---:|---:|
| 32x18 | 16x9 | 43.20 | 70.22 | 90.96 | 95.60 |
| 64x36 | 32x18 | 44.44 | 86.82 | 109.28 | 143.44 |

The earlier network-only timing table above remains a baseline. The current integrated harness consumes preprocessed features, phase packing, and previous-frame history uploaded by the CPU exporter, dispatches the nine network layers and temporal AKR/RGB output in one D3D12 command list, then compares controls, residuals, and image output with the Python reference. Release smokes covered 2x, 3x, and 4x scaling, 4/5/8 taps, reset and valid history. Across these tiny synthetic cases, network+AKR median timestamps were 57.18-60.38 us; p95 ranged up to 347.84 us because of noisy outliers. Queries use 5 warmups and 20 measured runs and exclude upload, CPU preprocessing, PSO creation, host wait, and readback. They are not full-resolution performance evidence. Direct `.nqsrpack` loading, GPU game-frame preprocessing, a shader ISA audit, and 10,000-run stability stress remain open.

## Limitations

AMD's published FSR 4.0.2 support is RX 9000 Series and above, with signed DLL integration. This project targets RX 5700 XT with a custom unsigned implementation; hardware execution and later game-loader integration remain unvalidated.

## QSSR/NaviQSR addendum status

The QSSR addendum is integrated as a separate proposed architecture family under `docs/naviqsr/`. Sony's official announcement says QSSR has a streamlined neural network and a hand-tuned PS5 implementation; it does not disclose the architecture. FP16/packed-math and performance details cited in the research addendum come from secondary reporting and are not treated as verified Sony implementation details. NaviQSR has a CPU-trained reference and a joined network+AKR D3D12 smoke. Teacher comparison, direct production-pack/frame input, sparse break-even, and production-quality/performance results remain open.

## NaviPRISM addendum status

NaviPRISM is an independent experimental primitive/filter path. Synthetic D3D12 validators pass on the RX 5700 XT for masked SAD, residual motion, THFA filtering, and tile classification. AMD RGA 2.14.2.7's gfx1010 disassembly contains `v_mqsad_u32_u8` in the `msad4` and SARM shaders. For the 4,096-case masked-SAD benchmark, median/p95 were 287.665/305.865 us for `msad4`, 288.654/325.290 us for scalar-u8, and 337.109/354.919 us for FP16 difference with FP32 accumulation. This shows near parity with scalar-u8 in this microbenchmark; it establishes no end-to-end speedup.

The SARM synthetic known-translation run matched the scalar reference on 48/48 tiles; median/p95 were 48.684/67.294 us. THFA's 4/5/8/9-tap variants matched the scalar reference on a 16x12-to-32x24 synthetic workload, with medians 0.928/0.953/2.199/0.975 us. The classifier returned the expected route counters and compacted indices for eight synthetic tiles. A four-phase reservoir GPU smoke matched the scalar reference for reprojection and reset; median/p95 were 2.313/12.504 us and 1.406/2.985 us on a 13x9 input. The full reservoir allocation was 13,104 bytes, with color capacity equal to a 26x18 RGB FP32 history. Exact inputs, hashes, and raw samples are in `NAVIPRISM_RESULTS.md` and `artifacts/results/naviprism_*.json`.

These are isolated synthetic implementation checks. THFA's GPU validator uses a synthetic atlas; it is not fitted from FSR4 captures. There is no captured teacher/native-HR sequence, full frame graph, downstream sparse fallback dispatch, persistent phase-history integration, temporal quality result, or game integration. NaviPRISM remains experimental; matching FSR4 image quality and end-to-end speed have not been established.

## DeltaControl V2 sequence and POST replay

The deterministic `.f4seq` smoke contains eight procedural synthetic 1920x1080 frames with reset/cut events at 0 and 4, valid exposure and reactive/transparency masks, and sequence SHA-256 `a06357453979901689f4f9c8ff2400a1efe5b9547e017a7fa4cf5219ba157ec2`. The same bytes were dispatched through the pinned FSR4 I8 native/1080 provider and FidelityFX FSR3.1.5 on the RX 5700 XT. All eight input-frame hashes align; each provider's instrumented output matches its own ordinary dispatch byte-for-byte. Both provider reports record build commit `41f903fdbd174a0742f9b67f3ab23f95f20804b6`. The pairing report is `artifacts/results/fsr3_fsr4_alignment_smoke.json`; FSR4 and FSR3 provider sequence reports are in `artifacts/results/`.

Timestamp queries bracket provider GPU work only. Excluding the first reset and camera cut, FSR4 mean/p50/p95 were 7,449.48/7,411.44/7,552.44 us; FSR3.1.5 was 2,535.77/2,513.24/2,617.16 us. This synthetic native-resolution harness timing is not game timing or a quality comparison. Cross-provider output equality is not claimed.

The literal float32 replay of pinned `post_common.hlsli` agrees with final RGB within 1e-3 at audited frames 0, 4 and 7. O0 still **fails**: the replay has non-finite model-color intermediates at 2,073,600/2,073,600, 2,073,600/2,073,600, and 2,073,528/2,073,600 pixels. The captured final RGB is all zero on frames 0 and 4 and 99.9965% zero on frame 7. The output match is caused by the same NaN-to-black clamp behavior; these captures cannot support control statistics, training, or quality analysis. Full per-frame values and replay source hash are in `artifacts/results/fsr4_post_replay_smoke.json`.

FSR3 source-confirmed taps and timing are present. Exact current/history basis taps were added and audited below. No representative rendered `.f4seq` was supplied, so O1-O13 and DeltaControl/Delta4 architecture selection remain gated on valid teacher captures.

## FSR4 root-cause matrix and FSR3 accumulation basis (2026-10-07)

The diagnostic matrix compared native signed-I8 `dot4` with a scalar bytewise signed-I8 implementation, each paired with literal or overflow-stable POST transforms. All four builds ran on the RX 5700 XT (`1002:731F`, driver `0x00200000523503e8`) over the same eight-frame synthetic sequence used by the prior FSR3 run. The sequence hash is `a06357453979901689f4f9c8ff2400a1efe5b9547e017a7fa4cf5219ba157ec2`; independently checked input hashes align across FSR3 and every matrix case.

| FSR4 diagnostic case | Provider output finite | Instrumented equals ordinary | POST RGB replay matches | Max non-finite model pixels | Max exact-zero RGB fraction | O0 eligible |
|---|---:|---:|---:|---:|---:|---:|
| Intrinsic `dot4`, literal POST | Yes | No | Yes* | 2,073,600 | 1.000000 | No |
| Intrinsic `dot4`, stable POST | Yes | No | No | 0 | 1.000000 | No |
| Scalar signed-I8, literal POST | Yes | No | No | 0 | 0.000000 | No |
| Scalar signed-I8, stable POST | Yes | No | No | 0 | 0.000000 | No |

*The intrinsic/literal replay matches captured RGB even though its source-equation intermediates are non-finite: frames 0 and 4 have 2,073,600/2,073,600 affected pixels, and frame 7 has 2,073,528/2,073,600. Its reference output is all zero on frames 0 and 4 and 99.9965% zero on frame 7. This is an invalid numerical match. Both scalar cases produce finite, nonblack values, but their RGB replay errors are material (max absolute error 0.01660, 0.04883, and 0.03589 on frames 0, 4, and 7) and instrumented output differs from the ordinary provider output on all eight frames. Their raw-parameter absolute maxima are 11.6953 and 12.0781, compared with 267.5 for the intrinsic cases; this change alone does not establish correctness.

The matrix therefore leaves the defect upstream of a source-valid POST unresolved. O1-O13 remain locked; the stable transform is diagnostic only. The replay and provider reports plus the case summary are in `artifacts/results/fsr4-rootcause-matrix/summary.json` and the adjacent per-case JSON files. Large raw captures remain under ignored `build/fsr4-rootcause-matrix/`.

The FSR3.1.5 reference was rebuilt with 40 shader permutations and capture-only taps at the exact accumulation lerp. On the same sequence, all eight input hashes align with all FSR4 cases, and FSR3 instrumented/ordinary outputs match byte-for-byte. Frames 0, 4, and 7 capture the four `C`/`H` arrays as little-endian FP16 with shape `[1080, 1920, 4]` (16,588,800 bytes per array); each frame's captured final-output region also matches the normal reference output hash. Hashes and gate results are recorded in `artifacts/results/fsr3_delta_basis_capture_audit.json`; the sequence report is `artifacts/results/fsr3_rootcause_basis_sequence.json`. This is synthetic diagnostic evidence and carries no quality claim. The raw capture arrays are retained under ignored `build/release/fsr3-rootcause-captures/`.

Recreate the audit after the matrix and FSR3 sequence runs with:

```powershell
python tools/sequence/audit_fsr3_delta_basis.py `
  --fsr3-report artifacts/results/fsr3_rootcause_basis_sequence.json `
  --fsr4-matrix-dir artifacts/results/fsr4-rootcause-matrix `
  --capture-root build/release/fsr3-rootcause-captures `
  --output artifacts/results/fsr3_delta_basis_capture_audit.json
```

## O0 unblock bundle validation (2026-10-08)

Applied the supplied diagnostic bundle on the RX 5700 XT without changing the default provider configuration or pinned upstream source. The corrected CPU replay follows the compiled source semantics at image edges: `x_in/y_in` wrap as unsigned 32-bit coordinates for distance conversion (`uitofp` in DXIL), while the texture lookup reinterprets the bits as signed and clamps. The attached bundle's proposed signed-distance edge coordinates would not match this source behavior.

The Release harness now captures optional `reference_rgb` from the ordinary provider dispatch and includes independent GPU POST and signed-I8 dot4 conformance modes. On the scalar/literal provider build, the CPU replay matched instrumented final RGB within 1e-3 for every component at frames 0, 4, and 7; the independent GPU POST oracle also stayed within 1e-3 for every component. Native `dot4add_i8packed` matched the scalar signed-I8 reference on 256/256 deterministic and edge cases. These probes validate shader/oracle behavior, not FSR4 quality or intrinsic performance.

| Frame | CPU replay exact half fraction | CPU replay max abs | GPU POST max abs | Instrumented/reference within 1e-3 | Instrumented/reference max abs |
|---:|---:|---:|---:|---:|---:|
| 0 | 0.315227 | 0.0004883 | 0.0006169 | 0.998459 | 0.1152344 |
| 4 | 0.507629 | 0.0009766 | 0.0009904 | 0.997550 | 0.0754395 |
| 7 | 0.500038 | 0.0009766 | 0.0008558 | 0.926073 | 0.2144775 |

The independent checks pass for CPU POST, GPU POST, all eight aligned FSR3/FSR4 input frames, the existing FSR3 accumulation-site C/H audit, and dot4 semantics. The teacher gate still **fails** on instrumented/reference parity: maximum RGB errors exceed the 0.0025 limit and within-1e-3 fractions fall below 0.99999.

A second run using the same build commit (`bb13a6d819657512e4612e2ab78ac15ef651ab6e`), RX 5700 XT/driver, sequence hash, and all eight input-frame hashes produced different instrumented and ordinary output hashes in all eight frames. Comparing validated audit captures also shows different `raw_model_parameters`, recurrent values, and final/reference RGB at frames 0 and 4 while the captured model-input channels match; frame 7 additionally differs in model-input channels and reprojected history. This places the repeatability break at or before model-parameter generation; its lower-level cause remains unresolved. O1-O13 stay locked. Both runs use procedural synthetic input and support no image-quality or game-compatibility claim.

Machine-readable records: `artifacts/results/scalar_literal_o0_unblock_v2.json`, `scalar_literal_repeat_capture_v2.json`, `scalar_literal_repeat_run_v2.json`, `scalar_literal_repeatability_v2.json`, `scalar_literal_post_replay_v2.json`, `scalar_literal_instrumentation_audit_v2.json`, `scalar_literal_gpu_post_frame_{0,4,7}.json`, `dot4_conformance_o0_unblock.json`, and `scalar_teacher_gate_o0_unblock_v2.json`. Raw capture packages and `.f4postcase` payloads are in ignored `build/fsr4-rootcause-matrix/case-data/scalar_literal_o0_unblock_v2/`.

Recreate the scalar/literal capture and gates from PowerShell:

```powershell
. .\scripts\BuildEnvironment.ps1
Initialize-Fsr4Navi10VsEnvironment
cmake -S . -B build\fsr4-rootcause-matrix -G Ninja `
  -DFSR4N10_FORCE_SCALAR_DOT4=ON -DFSR4N10_STABLE_POST_MATH=OFF
cmake --build build\fsr4-rootcause-matrix --config Release
python tools\sequence\run_fsr4_teacher.py `
  build\fsr4-rootcause-matrix\fsr4n10_harness.exe `
  build\release\delta-control-smoke.f4seq `
  artifacts\results\scalar_literal_o0_unblock_v2.json `
  --capture-root build\fsr4-rootcause-matrix\case-data\scalar_literal_o0_unblock_v2\captures
python tools\sequence\run_fsr4_teacher.py `
  build\fsr4-rootcause-matrix\fsr4n10_harness.exe `
  build\release\delta-control-smoke.f4seq `
  artifacts\results\scalar_literal_repeat_capture_v2.json `
  --capture-root build\fsr4-rootcause-matrix\case-data\scalar_literal_o0_unblock_v2\captures_repeat
python tools\sequence\run_fsr4_teacher.py `
  build\fsr4-rootcause-matrix\fsr4n10_harness.exe `
  build\release\delta-control-smoke.f4seq `
  artifacts\results\scalar_literal_repeat_run_v2.json
$captureRoot = 'build\fsr4-rootcause-matrix\case-data\scalar_literal_o0_unblock_v2'
python tools\oracles\compare_fsr4_sequence_repeatability.py `
  artifacts\results\scalar_literal_o0_unblock_v2.json `
  artifacts\results\scalar_literal_repeat_capture_v2.json `
  --first-capture-root "$captureRoot\captures" `
  --repeat-capture-root "$captureRoot\captures_repeat" `
  --output artifacts\results\scalar_literal_repeatability_v2.json
$captures = @(Get-ChildItem build\fsr4-rootcause-matrix\case-data\scalar_literal_o0_unblock_v2\captures `
  -Filter '*.f4cap' | ForEach-Object { $_.FullName })
python tools\oracles\replay_fsr4_post.py @captures `
  --output artifacts\results\scalar_literal_post_replay_v2.json
python tools\oracles\compare_fsr4_capture_reference.py @captures `
  --output artifacts\results\scalar_literal_instrumentation_audit_v2.json
build\fsr4-rootcause-matrix\fsr4n10_harness.exe --run-dot4-conformance `
  artifacts\results\dot4_conformance_o0_unblock.json
foreach ($frame in @(0, 4, 7)) {
  $capture = "build\fsr4-rootcause-matrix\case-data\scalar_literal_o0_unblock_v2\captures\frame_$frame.f4cap"
  $case = "build\fsr4-rootcause-matrix\case-data\scalar_literal_o0_unblock_v2\frame_$frame.f4postcase"
  python tools\oracles\export_fsr4_post_case.py $capture $case
  build\fsr4-rootcause-matrix\fsr4n10_harness.exe --run-fsr4-post-gpu-oracle `
    $case "artifacts\results\scalar_literal_gpu_post_frame_$frame.json"
}
python tools\oracles\evaluate_scalar_teacher_gate.py `
  --cpu artifacts\results\scalar_literal_post_replay_v2.json `
  --gpu artifacts\results\scalar_literal_gpu_post_frame_0.json `
        artifacts\results\scalar_literal_gpu_post_frame_4.json `
        artifacts\results\scalar_literal_gpu_post_frame_7.json `
  --instrumentation artifacts\results\scalar_literal_instrumentation_audit_v2.json `
  --dot4 artifacts\results\dot4_conformance_o0_unblock.json `
  --sequence-report artifacts\results\scalar_literal_o0_unblock_v2.json `
  --fsr3-report artifacts\results\fsr3_rootcause_basis_sequence.json `
  --basis-audit artifacts\results\fsr3_delta_basis_capture_audit.json `
  --repeatability artifacts\results\scalar_literal_repeatability_v2.json `
  --output artifacts\results\scalar_teacher_gate_o0_unblock_v2.json
```

The two comparison commands and teacher gate return a nonzero status while their reports record the observed mismatches; that is expected for the current failing O0 gates.

## FSR4 scratch race bisector (2026-10-08)

Applied the `FSR4-Navi10-RaceBisector-5b22fd0` diagnostics without editing the
pinned AMD checkout or changing default provider behavior. The standard and
global-UAV-barrier Release builds each completed 84/84 fresh-process cases on
the RX 5700 XT with no failed run. All cases used the existing eight-frame
synthetic sequence (hash
`a06357453979901689f4f9c8ff2400a1efe5b9547e017a7fa4cf5219ba157ec2`), and the
cross-build comparison confirmed matching inputs in all 84 paired cases.
An additional ordinary Release build also passed with both diagnostic CMake
options confirmed `OFF`.

| Build | Seed | First repeat-divergent prefix | First instrumented/ordinary scratch mismatch |
|---|---|---:|---:|
| Standard | off / zero / a5 | 11 | 11 |
| Global UAV barrier | off / zero / a5 | 11 | 11 |

For every seed and build, scratch snapshots matched through prefix 10. The
first changed snapshot was after prefix 11 plus POST; it therefore localizes
the first observed difference to that prefix boundary, not to a proven shader
instruction. Filling scratch with zero did not make the prefix-11 or full-model
outputs repeatable, so uninitialized scratch alone is not the cause. Changing
the seed from zero to `a5` changed ordinary and instrumented full RGB hashes on
all eight frames despite identical inputs.

The global barrier did not move the first observed divergence or restore
full-model repeatability. Between standard and barrier builds, full RGB hashes
differed for all six matching full-model seed/repeat pairs; scratch captures
differed at prefixes 11 and 12 and in full-model cases. This is consistent with
order/timing sensitivity but does not establish that barriers cause the
nondeterminism. The exact pass-11/POST source remains unresolved; no production
fix or quality claim follows from these diagnostics. O0 stays closed and O1-O13
remain locked.

The five machine-readable campaign/analysis files are in
`artifacts/results/fsr4-race-bisector/`. Raw scratch buffers remain ignored in
`build/fsr4n10-race-bisector/`. Run instructions and interpretation limits are
in `docs/RACE_BISECTOR.md`.

## Pass 11 Native/1080 I8 bounds guard (2026-10-08)

Integrated the build-local, default-OFF bounds guard for the pinned FSR4
Native/1080 I8 Pass 11 scalar `FNB_CT2D_ADD<32,1>` specialization. The
upstream FidelityFX checkout, weights, dispatch dimensions, arithmetic,
quality settings, and WMMA specialization remain unchanged. FidelityFX_SC's
dependency record proves the guarded build selected the uniquely named local
overlay (SHA-256
`3720BAC4CBE7D608870C83A8661403AE6D97DF0688B431AC7187A26B9BDEBD48`); the
stable Pass 11 selector and its content-addressed shader blob changed while
all pinned source hashes remained equal. A separate Release build confirms
`FSR4N10_PASS11_BOUNDS_GUARD=OFF` by default.

FidelityFX_SC also changed selector-header hashes/order for Pass 0, Pass 13,
and RCAS; their content-addressed shader payload digest sets were unchanged.
The comparison report separates selector-header hashes from actual payload
changes and identifies Pass 11 as the only payload set changed in this
build comparison.

On the RX 5700 XT (driver `32.0.21045.1000`), the baseline scalar, guarded
scalar, and guarded intrinsic Release variants completed 72/72 fresh-process
cases (24 each), with zero process failures. The test used the existing
eight-frame procedural sequence, hash
`a06357453979901689f4f9c8ff2400a1efe5b9547e017a7fa4cf5219ba157ec2`, across
zero/A5 scratch seeds, pass 10/11/12/full prefixes, and three repeats.

| Variant | Pass 11 scratch repeatable | Full RGB repeatable | Instrumented = ordinary | Zero/A5 RGB equal |
|---|---:|---:|---:|---:|
| Baseline scalar | no | no | no | no |
| Guarded scalar | yes | yes | yes | yes |
| Guarded intrinsic | yes | yes | yes | yes |

Baseline Pass 10 scratch repeated; Pass 11 was the first divergent prefix.
All eight baseline alias comparisons placed every changed byte inside the
source-predicted 64-pixel spill zone. The first changed byte in one ordinary
A5 repeat comparison was offset `13,240,320`, matching the predicted row-52
write collision. The bounds hypothesis is therefore supported by GPU
evidence. Guarded modes had zero differing bytes in their scratch comparison
sets and repeatable eight-frame RGB output across independent runs and both
scratch seeds.

The guarded scalar and intrinsic arithmetic modes differ from each other:
all eight final RGB frame hashes differ, and their pass-10 scratch snapshots
are not bit-identical. Each mode is stable on its own, but this campaign does
not establish cross-mode numeric equivalence. Full-run provider-only steady
state median dispatch means were 19,103.75 us for baseline scalar, 18,587.0
us for guarded scalar, and 7,768.32 us for guarded intrinsic across six runs
per variant. These modes have different dot4 arithmetic, so timings are
reported as observations rather than an isolated guard performance claim.

Validation: focused Pass 11 Python tests passed 25/25; default and guarded
Release CTest each passed 1/1; the all-variant Release campaign compiled and
ran all 72 cases. The existing O0 teacher gate remains closed: this is
synthetic diagnostic input, and no FSR4-vs-reference quality claim follows.
Machine-readable evidence is in
`artifacts/results/fsr4-pass11-guard/`; raw scratch captures remain ignored in
`build/pass11-guard-campaign/`. Source geometry, exact collision, command,
and interpretation details are in `docs/PASS11_BOUNDS_ROOTCAUSE.md`.
