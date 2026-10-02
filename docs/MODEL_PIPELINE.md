# Model pipeline: extraction, conversion, packing and shader generation

## 1. Objective
Transform the upstream FSR4 4.0.2 model assets into deterministic, Navi10-friendly FP16 model packs and specialized shader metadata without changing the logical network.

The conversion toolchain is part of the product. Do not manually edit generated weight blobs.

## 2. Discover actual upstream layout first
After fetching the source-bearing tree, inspect:
- `Kits/FidelityFX/upscalers/fsr4/internal/shaders/`
- model-specific generated HLSL directories/files
- `initializers.bin` files
- provider static weight tables
- `dx12/ml2code_runtime/`
- shader selector/build scripts
- provider code that chooses model/preset/resolution tier

Expected public structure includes INT8 and FP8 model variants named around `fsr4_model_v07_*`, but code must discover the actual exact names.

Create `generated/manifests/upstream_inventory.json` listing all discovered model/preset/tier files, sizes and SHA-256 hashes.

## 3. Canonical representation
Create a host-side `ModelManifest` schema. JSON is the human-readable canonical serialization, while C++ may load a compact binary representation.

Required fields:
```json
{
  "schemaVersion": 1,
  "modelId": "...",
  "sourceCommit": "...",
  "sourceVariant": "i8|fp8",
  "preset": "quality|balanced|performance|ultraperf|native|drs",
  "resolutionTier": "...",
  "passes": [
    {
      "index": 0,
      "name": "...",
      "entryPoint": "...",
      "source": "...",
      "dispatchGeometry": "...",
      "inputs": ["..."],
      "outputs": ["..."],
      "operators": ["..."],
      "weights": ["..."]
    }
  ],
  "tensors": [
    {
      "name": "...",
      "dtype": "...",
      "shape": [0],
      "byteOffset": 0,
      "byteSize": 0,
      "scale": null,
      "zeroPoint": null,
      "layout": "..."
    }
  ]
}
```

Do not invent operator names if upstream code generator expresses them differently. Preserve enough metadata to reproduce all conversions.

## 4. Extractor design
Preferred implementation:
1. Parse machine-generated model HLSL and any generated declarations with a narrow parser tailored to upstream conventions.
2. Cross-check parsed offsets/sizes against binary blob size and provider declarations.
3. Where weight arrays are embedded in C/C++ rather than `initializers.bin`, extract them using a small compiled helper or a parser that validates token counts and types.
4. Fail on ambiguity instead of silently guessing.

Unit tests must use at least several tensors spanning different operator types and verify exact byte/element counts.

## 5. Dequantization

### 5.1 INT8 source
For each quantized tensor, reproduce the exact source dequantization convention. Do not assume generic `(q-zero)*scale`; inspect upstream HLSL/operator code for scale/bias/packing semantics.

The host converter must have a scalar reference implementation and tests that compare it with a small shader/CPU reproduction of upstream formulas.

### 5.2 FP8 source
If using the FP8 model as a quality source, decode its actual FP8 flavor exactly (expected public source references indicate E4M3-style data, but inspect source). Preserve saturation/subnormal/special-value behavior according to upstream implementation.

### 5.3 Output
Convert to IEEE binary16 (`float16`) byte representation deterministically. Python implementation may use NumPy only if exact conversion behavior is controlled; otherwise implement explicit half conversion and test it.

## 6. FP16 pack format
Define a simple versioned binary pack. Recommended header:

```c
struct ModelPackHeader {
  char magic[8];          // "F4N10PK"
  uint32_t version;
  uint32_t headerBytes;
  uint8_t sourceSha256[32];
  uint8_t manifestSha256[32];
  uint32_t tensorCount;
  uint32_t flags;
  uint64_t tensorTableOffset;
  uint64_t dataOffset;
  uint64_t fileBytes;
};
```

Each tensor record contains name hash/string-table offset, dtype, shape, layout enum, alignment, byte offset/size and any compatibility quantization metadata.

Requirements:
- little-endian
- bounds checked
- all offsets validated before GPU upload
- data aligned for efficient D3D12 buffer upload, e.g. at least 16/32 bytes; increase alignment per layout if useful
- SHA-256 of final pack

## 7. Prepacking layouts
Generate layouts only where a consumer shader uses them.

Candidate layouts:
- NHWC FP16 canonical
- channel pairs (`half2`) contiguous
- channel quads (`uint2`/two half2 vectors) where useful
- operator-specific transposed or blocked kernel layout

For a convolution-like inner loop, optimize so neighboring lanes read contiguous activation data and weight fetches have high locality. Use the actual operator graph to choose the blocking.

## 8. Quantization metadata for fp16_compat
Compatibility mode may need original scale/bias/clamp boundaries even when weights are pre-dequantized.

Store:
- activation scale
- output scale
- clamp range
- rounding mode or formula
- zero point if any
- per-channel vs per-tensor scale metadata

Do not physically re-encode intermediate data to INT8 unless that is selected by a hybrid shader. Implement the mathematically equivalent boundary in registers/FP16/FP32 where possible.

## 9. Shader generator
`tools/shaders/generate_hlsl.py` should read canonical manifests and emit one specialized shader source/entry per candidate variant.

Generated shader identity should encode:
```text
backend / model / preset / tier / pass / layout / wave / fusion variant
```

Example only:
`f16c_quality_1080_p07_blocked_w32_fused.hlsl`

Generated sources include a header comment with:
- generator version/git hash
- source manifest hash
- compile defines
- generation timestamp optional (do not include it in content hash if reproducibility matters)

## 10. Common generated code
Generate/include reusable primitives for:
- safe FP16 loads
- half2 dot/FMA building blocks
- activation functions used by actual model
- saturation/clamping
- reference quantization emulation
- coordinate mapping
- tensor address calculation specialized by fixed layout

Avoid generic virtual/operator dispatch in HLSL.

## 11. Shader compilation
`compile_hlsl.py` must:
- locate DXC robustly
- compile with explicit command line recorded in manifest
- capture stdout/stderr
- hash DXIL
- optionally emit disassembly and debug PDB
- fail build on warnings likely to indicate truncation or unsupported 16-bit behavior
- cache by content hash + compiler version + flags

For production FP16 use true 16-bit types and verify the compiled DXIL/ISA actually contains 16-bit operations rather than silent promotion to FP32 where material.

## 12. ISA analysis
If RGA CLI exists, run it for production candidates and parse/store:
- ISA text
- VGPR count
- SGPR count
- LDS usage
- scratch/spills
- wave size
- occupancy/resource statistics available

Add a static reject/warn policy:
- any scratch spill in a hot neural kernel is a high-priority optimization issue
- major VGPR increases from fusion require end-to-end proof
- absence of expected 16-bit arithmetic in FP16 shader triggers investigation

## 13. Generated artifact reproducibility
Two clean conversions from the same upstream commit/tool version must produce byte-identical manifests, model packs and release DXIL when the same DXC version/flags are used.

Provide `scripts/repro-check.ps1` that generates into two temp folders and compares hashes.
