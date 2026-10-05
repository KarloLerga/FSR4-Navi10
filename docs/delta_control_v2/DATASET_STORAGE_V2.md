# Dataset storage and sharding V2

## Two levels of truth

### Level A: audit `.f4cap`
Purpose:
- exact provenance
- source/shader hash validation
- debugging
- reproduction

Keep the current format.

### Level B: `f4n10.dataset.v2`
Purpose:
- efficient training/oracle streaming
- temporal chunks
- crops/tiles
- paired FSR4/FSR3 labels
- compression

Every derived sample must retain parent sequence/capture hashes.

## Profiles

### audit_full
All current fields at canonical precision.

### param4_train
Suggested minimum:
- seven semantic channels
- raw p0..p3
- recurrent u8
- current reconstruction source
- reprojected history
- final teacher RGB for validation
- depth/MV/jitter/metadata

Physical controls are derived offline.

### delta4_train
- FSR4 raw p0..p3
- FSR4 recurrent u8
- FSR4 final RGB
- aligned FSR3 selected features/state/output
- shared input/depth/MV/jitter metadata
- optional native/supersampled HR

## Precision policy

Canonical audit values remain unchanged.

Derived shards may use FP16 where either:
- the original resource is effectively FP16, or
- an explicit downcast validation demonstrates negligible post-RGB/temporal error.

Recurrent state remains U8 because the FSR4 teacher already uses U8 UNORM.

## Crop strategy

Do not train only on uniform random crops.

Classify crop candidates as:
- easy/flat/stable
- edge
- thin geometry
- motion
- disocclusion
- reactive
- specular/shading-change
- large FSR3-vs-FSR4 residual

Maintain a balanced training sampler and an unbiased random validation subset.

Suggested output-space crops:
- 128x128
- 256x256

Include halo needed by POST filtering and temporal reprojection.

## Chunking and compression

Use sequence-aligned chunks of 8-32 frames. Prefer zstd when available. Record dtype, shape, raw byte count, compressed byte count, and SHA-256.

## Streaming

Support:

```text
provider GPU -> async staging/readback ring -> shard builder -> compressed dataset
```

Do not require entire sequences in RAM.

## Reproducibility metadata

Every dataset manifest records:
- repository commit
- FSR4 source commit
- FSR3 source/version
- shader hashes
- GPU/driver
- sequence hash
- generator seed
- quality mode/dimensions
- derivation-tool version
