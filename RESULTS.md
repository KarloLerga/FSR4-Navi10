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
| FP16 GPU arithmetic probe | Passed in Release and RelWithDebInfo: all 64 output half values matched expected products on the RX 5700 XT |
| FP16 DXIL inspection | `dxc -dumpbin` shows `fmul fast half` in the compiled probe |
| NaviQSR D3D12 frame graph | Release build dispatches nine network layers followed by temporal AKR/RGB reconstruction in one command list. Smoke cases cover 2x/3x/4x scaling, 4/5/8 taps, and reset/valid history; max control error 1.13e-5 and max RGB error 1.14e-6. Weights are FP16-stored; activations and accumulation are FP32. |
| NaviQSR earlier build coverage | The network-only smoke passed in Release and RelWithDebInfo before frame-graph integration. The current joined graph has been built and dispatched in Release. |
| NaviQSR AKR D3D12 smoke | 4/5/8-tap variants passed the bounded GPU/reference check on one 64x36 output in Release. |
| Full GPU-native FSR4 frame path | Not implemented. The experimental image smoke below uses CPU preprocessing/postprocessing around the GPU I8 model graph. |
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
