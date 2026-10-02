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

The deterministic source inventory covers 12 model variants (6 presets × INT8/FP8 representations), 3 resolution tiers, 12 neural passes, pre/post model stages, 13 padding-reset entry points and locked initializer hashes. Two generated inventory files were byte-identical. Its parser/classification checks are part of the seven passing Python unit tests.

## Build and hardware capability probe

| Check | Result |
|---|---|
| CMake Release and RelWithDebInfo configure/build | Passed |
| `compile_fp16_probe` DXC `cs_6_6 -enable-16bit-types` | Passed |
| CTest `model_tools_unit_tests` | Passed (7 Python unit tests) |
| Harness `--list-adapters` | RX 5700 XT found as `1002:731f`; D3D12 yes, SM 6.8, wave ops yes (32–64 lanes), native 16-bit shader ops yes, binding tier 3 |
| Upstream I8 shader source compile | Passed for all 6 presets × 3 resolution tiers × entries 0–13: 252 DXIL outputs across 18 manifests using DXC `cs_6_6`; aggregate index under `build/release/reference/i8/index.json` |
| Targeted compile reproducibility | Recompiled native/1080p; both endpoint DXIL hashes, its pass manifest hash, and the aggregate-index hash remained unchanged |
| Native/1080p quantized weight conversion | Passed bounds checks for 38 tensors / 122,880 I8 values; produced 245,760 FP16 bytes; repeated pack and manifest hashes matched |
| FP16 weight pack scope | Includes only source `QuantizedTensor4i8_*` weights. Native-FP16 weights, biases, runtime tensors and GPU model dispatch are outside this pack. |
| FP16 GPU arithmetic probe | Passed in Release and RelWithDebInfo: all 64 output half values matched expected products on the RX 5700 XT |
| FP16 DXIL inspection | `dxc -dumpbin` shows `fmul fast half` in the compiled probe |
| GPU execution of FSR4 neural passes | Not implemented/observed |
| FSR4 frame, image-quality comparison, stability run, GPU timestamps | Not run |

No neural execution, performance or quality claim is made. The harness enumerates adapters and runs a standalone FP16 arithmetic self-check.

## Limitations

AMD's published FSR 4.0.2 support is RX 9000 Series and above, with signed DLL integration. This project targets RX 5700 XT with a custom unsigned implementation; hardware execution and later game-loader integration remain unvalidated.
