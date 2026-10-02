# Navi10 / RX 5700 XT backend design

## 1. Philosophy
Optimize the actual full frame, not an architecture theory. Navi10 has efficient native 16-bit packed math, but public compiler/ISA documentation around particular dot-product instructions in gfx1010 is nuanced. Therefore the project implements full FP16 and proves the final per-pass choice through generated ISA plus GPU timestamps.

## 2. FP16 fundamentals
Use DXC true 16-bit types with `-enable-16bit-types`. Prefer `float16_t`, `float16_t2`, `float16_t4` for arithmetic/data whose precision budget permits it.

Primary goals:
- reduce instruction count vs scalarized quantized math
- double effective packed arithmetic where driver maps half vector operations efficiently
- reduce storage/bandwidth vs FP32
- avoid unnecessary conversion instructions

Never assume a HLSL `half2` expression maps to a single ideal instruction. Inspect selected ISA.

## 3. Accumulation policy
For each operator family create at least two accumulator implementations where relevant:
- FP16 multiply + FP32 accumulator (quality-safe baseline)
- FP16 multiply + FP16/packed accumulator (performance candidate)

Default `fp16_compat` starts with FP32 accumulation for numerically sensitive reductions. A candidate may use FP16 accumulation only after pass-level and temporal quality validation.

## 4. Dot/convolution implementation style
Because Navi10 lacks RDNA3-class WMMA, use vector ALU and lane-level parallelism.

For fixed small kernels/channels:
- load activations as half2/half4-compatible vectors
- load prepacked weights in matching pairs
- perform multiply-add accumulation in compile-time-fixed loops
- maintain multiple independent accumulators to hide latency without exploding VGPR count
- reduce address recalculation by pointer/base offset hoisting

Do not write one giant generic nested loop with runtime channel/kernel dimensions.

## 5. Threadgroup mapping
Start from upstream dispatch mapping. Candidate changes are allowed only when semantic pixel/tensor coverage stays identical.

For 2D image-like passes, 8x8 groups are a strong baseline because AMD's RDNA guide recommends 8x8-like access for coalesced image writes. For 1D model passes, preserve/source-informed 64-thread groups as a baseline.

Generate a small set of alternatives (e.g. 64 vs 128 threads for appropriate 1D passes; 8x8 vs 16x4 where mapping permits) and measure.

## 6. Wave size
Compile wave32 baseline. Generate wave64 only where legal and worthwhile.

Wave64 may help when:
- cross-lane operations benefit
- fewer wave-level duplicated operations occur
- the original operator was designed around 64 lanes

Wave32 may help:
- divergence
- occupancy/scheduling
- naturally 32-wide work

Do not force wave64 globally.

## 7. LDS policy
LDS is not automatically faster. Use it only when the same tile/weights are reused enough times to amortize:
- global load saved
- LDS store/load
- barriers
- bank conflict risk
- reduced occupancy due to LDS allocation

For each major operator family, have a direct-cache path and an LDS-tiled candidate if reuse suggests it. Keep only the measured winner.

## 8. Register pressure
RGA/RGP resource usage is a design constraint.

When fusing operations:
- track VGPR count before/after
- watch for occupancy step changes
- split kernels if fusion turns a bandwidth win into an occupancy loss
- avoid materializing large temporary vectors when recomputation is cheaper

Use scalar/compile-time constants to reduce vector register use.

## 9. Memory layouts
Favor contiguous vector loads and avoid scattered byte unpacking.

The FP16 packer may produce operator-specific layouts such as:
- weights grouped by output channel and input half-pairs
- pretransposed kernels
- packed bias/scale next to weights for same output channels

Use 16/32-byte aligned reads where possible. Do not rely on unaligned vector reads unless proven safe/fast.

## 10. Intermediate storage
For `fp16_compat`, default intermediate feature maps to R16/R16G16/R16G16B16A16-like or structured FP16 storage matching actual channel layout, not FP32.

Do not force GPU texture formats when ByteAddress/StructuredBuffer layouts are more natural for neural tensors. Pick per operator based on source access pattern and DX12 capabilities.

## 11. Fusion candidates
High-value fusion categories:
- bias + activation
- dequant/scale + convolution input transform
- convolution output + residual add + activation
- producer quantization semantics + consumer dequantization, implemented as one register-domain clamp/round operation
- adjacent pointwise operations

Avoid fusion across a boundary where:
- the intermediate has multiple consumers
- the producer/consumer dispatch topology differs incompatibly
- fusion sharply raises VGPR/LDS
- a barrier is semantically required for global neighborhood access

## 12. Pass-specific generation
The shader generator must emit pass-specific code using actual graph constants. Do not leave runtime switch statements for pass type in production shader.

## 13. INT8 reference/hybrid candidate
Compile faithful INT8 reference where hardware/driver permits. Use RGA/ISA to determine whether packed dot HLSL becomes a native dot instruction or scalarized sequence on this environment.

If native INT8 is unexpectedly efficient on RX 5700 XT for a particular pass, `hybrid_auto` may select it. This is a performance optimization, not a failure of the FP16 project; the complete FP16 path remains available.

## 14. Pre/post passes
Do not focus only on the neural middle. Profile pre/post/RCAS/SPD too. If these are already FP16/FP32 and significant:
- vectorize
- reduce redundant loads
- fuse compatible transforms
- improve thread mapping
without changing input/output semantics.

## 15. Barriers and scheduling
After functional correctness, build an exact dependency DAG. Replace blanket barrier-after-every-dispatch behavior with minimal barriers that preserve producer/consumer visibility.

If an upstream provider uses conservative UAV barriers, use it as reference correctness, then prove safe reductions through resource separation/dependencies and stress testing.

## 16. Async compute
Do not add async-compute complexity in this run unless the standalone/integration contract clearly permits overlapping independent FSR work with other queues. The upscaler's internal passes are mostly dependent; prioritize kernel/runtime efficiency first.

## 17. Dynamic resolution/presets
Compile per upstream resolution tier/preset. Runtime chooses correct prebuilt shader/model pack. No runtime model recompilation.

## 18. Performance telemetry
Each pass records:
- backend variant ID
- group dimensions
- wave variant
- GPU timestamp duration
- optional RGA VGPR/LDS/scratch stats

Export to JSON for tuning and `RESULTS.md` generation.

## 19. Practical target
No hard promise is encoded because the exact RX 5700 XT driver/compiler behavior must be measured. Aspirational targets:
- materially reduce neural network time vs unmodified/reference FSR4 path
- target roughly multi-x improvement if the reference quantized path is heavily inefficient
- make 1080p/1440p output meaningfully usable; attempt 4K but report truthfully if the network remains too expensive

Never fake or extrapolate final performance numbers.
