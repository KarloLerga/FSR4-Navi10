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
| Full GPU-native FSR4 frame path | Not implemented. The experimental image smoke below uses CPU preprocessing/postprocessing around the GPU I8 model graph. |
| FSR4 quality comparison, 10,000-run stability stress, end-to-end effect timing | Not run |

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

## Limitations

AMD's published FSR 4.0.2 support is RX 9000 Series and above, with signed DLL integration. This project targets RX 5700 XT with a custom unsigned implementation; hardware execution and later game-loader integration remain unvalidated.
