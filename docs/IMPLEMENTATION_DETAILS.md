# Implementation details — file-by-file engineering guidance

This document exists to reduce architectural invention during the Codex run. Names may be adjusted to fit actual upstream types, but responsibilities should remain.

## 1. `include/fsr4n10/api.h`
Public project-owned API, separate from AMD FSR API compatibility exports.

Suggested concepts:
```cpp
namespace fsr4n10 {
  enum class BackendKind { ReferenceI8, Fp16Compat, Fp16HighPrecision, HybridAuto };
  enum class QualityMode { NativeAA, Quality, Balanced, Performance, UltraPerformance, DRS };

  struct ContextDesc {
    ID3D12Device* device;
    uint32_t maxRenderWidth, maxRenderHeight;
    uint32_t displayWidth, displayHeight;
    QualityMode quality;
    BackendKind backend;
    bool enableAutoExposure;
    bool enableRcas;
    // exact upstream flags added after source inspection
  };

  struct DispatchDesc {
    ID3D12GraphicsCommandList* commandList;
    ResourceView color;
    ResourceView depth;
    ResourceView motionVectors;
    ResourceView exposure;
    ResourceView reactive;
    ResourceView transparencyAndComposition;
    ResourceView output;
    float jitterX, jitterY;
    float motionVectorScaleX, motionVectorScaleY;
    float preExposure;
    float frameTimeDeltaMs;
    float sharpness;
    uint32_t renderWidth, renderHeight;
    bool reset;
  };
}
```
Do not finalize fields until matched to upstream provider constants/resources.

## 2. Device layer
`src/core/device_caps.cpp`
- Query DXGI adapter and D3D12 options.
- Keep raw values in a serializable `DeviceCaps`.
- Expose lane-count capabilities.
- Device name/PCI IDs are diagnostics; shader correctness uses D3D capabilities.
- `gfx1010` attribution can also be recorded from RGA target/local GPU identification, but do not gate solely on a name string.

## 3. Resource allocator
Implement a small explicit allocator rather than adding a large dependency.

Objects:
- `GpuBuffer`
- `GpuTexture`
- `DescriptorAllocator`
- `UploadRing`
- `TimestampHeap`
- `TransientArena`

`TransientArena` can start with separate committed resources for correctness, then migrate to placed resources/heaps and alias groups after lifetime graph is correct.

Each resource tracks current state in debug builds. Barrier builder receives producer/consumer states and validates transitions.

## 4. Model manifest loader
`src/core/model_manifest.cpp`
Use a real JSON parser dependency only if already available via vcpkg and worth it; otherwise generated manifest can also emit a C++ header/binary table to avoid runtime JSON dependency. Runtime release should prefer compact generated metadata; JSON is for tooling/debug.

## 5. Model pack loader
Validate:
- magic/version
- file size/offset overflow
- tensor record count limit
- alignment
- hash if requested
- no overlapping records unless format explicitly permits aliases

Upload immutable weights once during context creation to DEFAULT heap via staging upload, not every frame.

## 6. Shader pack
Compile offline DXIL into a packed archive or generated C++ blob table. Avoid thousands of loose files in final release if a pack is simpler.

Suggested entry metadata:
```cpp
struct ShaderRecord {
  uint64_t variantHash;
  uint32_t passId;
  uint16_t backend;
  uint16_t waveSize;
  uint32_t dxilOffset;
  uint32_t dxilBytes;
  uint8_t sha256[32];
};
```

## 7. Root signature strategy
First inspect upstream bindings. Prefer one common root signature for neural passes when descriptors are structurally similar.

Potential layout:
- descriptor table SRVs
- descriptor table UAVs
- CBV for frame/model constants
- small root constants for pass-specific offsets if cheaper

Do not change resource-binding ABI merely to save a few root parameters until working reference exists.

## 8. Scheduler
Represent pass execution as static generated metadata:
```cpp
struct PassPlan {
  PassId id;
  ShaderVariantId shader;
  DispatchDims dims;
  ResourceId inputs[N];
  ResourceId outputs[M];
  BarrierPlan barriersBefore;
};
```

The production schedule is built once per preset/tier/backend, not dynamically discovered every frame.

## 9. Reference backend
Prefer compiling/embedding the original source-visible shaders with minimal adapter glue. The purpose is to establish a faithful behavioral baseline, not to optimize it.

If the original path has hardware gating that rejects Navi10, the harness may need to instantiate equivalent shader/provider code directly instead of using AMD's signed capability gate. Keep algorithm/shader math unchanged.

## 10. FP16 compatibility backend
Implementation sequence per pass:
1. Start from the operator graph/weight declarations of the corresponding original pass.
2. Replace quantized weight storage with generated FP16 pack layout.
3. Replace packed INT8 dot operations with specialized FP16 vector MAC loops.
4. Preserve original bias/scale/nonlinearity/residual semantics.
5. Implement quantization-boundary semantics mathematically where required, but keep the value in register/FP16 intermediate if a round-trip memory write is unnecessary.
6. Compare output of the pass.
7. Only then fuse with neighbors or change thread mapping.

## 11. FP16 high-precision backend
Start as a branch of the validated compat backend. For each removable quantization round-trip:
- remove it in one operator boundary
- run pass/final/temporal comparison
- retain only if stable

Do not globally delete all quantization operations in a blind search/replace.

## 12. Shader generator architecture
Python modules:
```text
tools/shaders/
  ir.py            # internal pass/operator representation
  layouts.py       # tensor/weight layouts
  emit_common.py
  emit_conv.py
  emit_blocks.py
  emit_pass.py
  generate_hlsl.py
```

Keep generation deterministic: sort keys/names, stable whitespace/templates, no timestamps in hashed source.

## 13. Operator IR
Do not build a general ONNX framework. A small IR only needs operators actually present in FSR4 source:
- convolution/transposed convolution as observed
- depthwise/pointwise forms
- residual add
- activation
- scaling/quantization semantics
- copy/reformat
- up/downsample operators found upstream

Names and details come from source inspection.

## 14. FP16 convolution template
For fixed K, Cin, Cout:
```text
for each output tile assigned to lane/thread:
  accumulators = bias
  for fixed kernel/input channel blocks:
    load half2 activation
    load half2 weights for one/multiple output channels
    accumulator += dot(pair)
  apply residual/activation/compat boundary
  store vectorized output
```

Tune number of simultaneous output-channel accumulators. Too few underutilizes ALU; too many raises VGPRs.

## 15. Weight reuse
Weights are tiny relative to frame tensors in many neural upscalers, but do not assume cache behavior. Candidate techniques:
- readonly ByteAddress/StructuredBuffer in device local memory
- prepacked sequential reads
- small constant/root data only for truly tiny pass0 tables
- LDS staging only if repeated reuse and RGA/timing prove it

## 16. History tensors
Mirror upstream exactly. Persistent history may include previous reconstructed output/features/exposure. Do not alias across frames. Reset explicitly clears or marks history invalid per upstream semantics.

## 17. Timestamp system
Create one query heap/readback buffer sized for all pass begin/end pairs times frames-in-flight. Use `EndQuery` timestamps and `ResolveQueryData`; convert by command queue frequency. Wait outside measured region.

## 18. Benchmark statistics
Warmup e.g. 30-100 dispatches based on workload, then collect enough samples for stable median. Save all raw values. Calculate median, mean, p10/p90, stddev. GPU clocks can vary; note clock/power state if available but do not alter power settings.

## 19. D3D12 debugging
Development validation should support:
- D3D12 debug layer if installed
- info queue break/filter on corruption/error
- DRED on device removal
- optional GPU-based validation toggle (slow)

No unresolved error-severity messages before release.

## 20. Quality tool implementation
Image/tensor comparison can be Python/Numpy for development. Harness exports raw FP16 tensors plus metadata; Python converts to float32 for metrics. For final-output PNG, use a permissively licensed small image library or WIC; keep linear HDR raw reference separately because PNG 8-bit is not sufficient for precision metrics.

## 21. Synthetic testcase format
Define a directory/manifest:
```text
case_name/
  case.json
  frame_0000_color.bin
  frame_0000_depth.bin
  frame_0000_mv.bin
  ...
```
`case.json` specifies format, dimensions, strides, exposure, jitter, reset, resource presence. Hash all files.

Generate synthetic cases in project tooling so no copyrighted game captures are required for basic validation.

## 22. FSR API adapter implementation order
1. Build against public headers.
2. Implement version/query path.
3. Create/destroy context.
4. Dispatch mapping to core.
5. Resource requirement/memory query.
6. configure/debug callback if used.
7. smoketest via `LoadLibrary/GetProcAddress`.

## 23. Release pack
Do not include development research repositories. Release should only contain project binaries/assets/docs legally needed to run.
