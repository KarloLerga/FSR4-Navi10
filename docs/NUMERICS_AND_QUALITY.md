# Numerical fidelity, visual quality and temporal stability

## 1. Priority
Performance optimization is invalid if it visibly degrades FSR4 in the default production mode. Quality gates run before timing gates when selecting a candidate.

## 2. Reference hierarchy
Use, in order:
1. Faithful locally built FSR4 4.0.2 reference implementation from pinned upstream source/model.
2. Upstream sample/provider output if runnable on the same inputs.
3. Deterministic CPU/scalar operator references for individual conversion/math primitives.

Do not use FSR3 output as the quality reference.

## 3. Reference backend correctness
Before judging FP16, prove `reference_i8` reproduces upstream behavior. For a deterministic testcase, reference implementation outputs/checksums must be stable across repeated runs on the same build/device, aside from documented GPU floating-point non-determinism.

## 4. Pass-by-pass differential mode
Harness can dump every model intermediate. Comparison order:
- pre output
- pass 1 ... pass 12 (or actual upstream count)
- post output
- RCAS output

When final output diverges, locate first divergent pass rather than patching later stages blindly.

## 5. fp16_compat gate
Because arithmetic representation changes, bit identity is not required unless naturally achieved. Initial release-quality target on deterministic synthetic/recorded sequences:
- no NaN/Inf
- no invalid resource values/out-of-range explosions
- final linear-image PSNR vs reference >= 50 dB where metric is meaningful
- SSIM >= 0.999 on luma for ordinary scenes
- mean absolute error sufficiently small that diff image requires amplification to see structure
- 99.9th percentile absolute linear RGB error <= 1/256 unless source/reference HDR range requires normalized alternative

These are starting acceptance thresholds, not excuses to accept visible artifacts. If visual/temporal review detects regression, fix it even when scalar metrics pass.

If exact FSR4 output range/color space makes these numeric thresholds inappropriate, derive normalized thresholds from reference repeatability/noise and document the justified replacement in DECISIONS_LOG.md.

## 6. fp16_high_precision gate
High precision may differ more from the quantized reference. It may become default only when:
- it passes all stability tests
- objective quality is no worse in a meaningful aggregate
- no repeatable new ghosting/shimmering/ringing is visible in synthetic stress sequences
- performance is equal/better or quality gain is significant enough to justify small cost

If it is better quality but slower, expose it as optional `high_precision`, not default `hybrid_auto` unless the user later chooses quality over speed.

## 7. Synthetic temporal stress cases
Generate deterministic sequences covering:
1. static fine checker/line pattern with subpixel jitter
2. one-pixel/high-frequency lines moving slowly
3. high-contrast object revealing previously occluded background
4. thin alpha-like geometry surrogate
5. specular-like moving highlight
6. camera pan over fine texture
7. sudden cut/reset
8. exposure change
9. depth discontinuity with motion
10. zero-motion static scene for history convergence

They do not replace real captures but catch algorithmic temporal faults.

## 8. Temporal metrics
For each pixel/region where appropriate compute:
- error vs reference each frame
- temporal variance difference
- residual error after motion stops
- disocclusion recovery time
- static convergence noise

Create graphs/JSON rather than only screenshots.

## 9. Color/exposure correctness
Compare in the same linear domain before tone mapping/display conversion. Respect upstream pre-exposure and colorspace flags. A gamma-space PSNR alone is not sufficient.

## 10. Reset/state
Test:
- first frame with reset
- consecutive frames without reset
- explicit reset mid-sequence
- render size change if supported
- preset change/context recreation

History resources must not leak stale data after reset/recreate.

## 11. Precision debugging
When a FP16 candidate diverges:
- disable fusion first
- use FP32 accumulator
- preserve quantization boundary exactly
- compare intermediate tensor
- then reintroduce optimization one dimension at a time

Never “fix” a difference by clamping final output unless upstream algorithm requires that clamp.

## 12. Comparison reports
Every validation run outputs JSON plus optional CSV and diff images. Include backend hashes and input hashes so results are reproducible.
