# THFA - Temporal Hash Filter Atlas

THFA is the primary no-CNN reconstruction path.

## Runtime objective

descriptor -> compact index -> atlas parameters -> 4/5/8 texture samples -> HR current candidate.

## Spatial descriptor

Start RAISR-style:
- orientation: 8 or 16 bins
- strength: 4 bins
- coherence: 4 bins
- alias-risk: 2 bins
- local contrast: 2-4 bins

Avoid output-pixel atan2. Use gx/gy signs, abs values, comparisons/ratios and cheap structure-tensor approximations. Compute once at LR/tile scale and reuse.

## Temporal descriptor

Candidates:
- motion magnitude 3 bins
- SARM confidence 3-4 bins
- depth edge 2 bins
- reactive 2-3 bins
- history validity 3 bins
- history age 2-4 bins.

Do not take a full Cartesian product.

## Phase/scale

Use exact jitter phase/subpixel type and render/output ratio. Provide tuned common ratios plus an interpolated continuous path.

## Atlas family A: analytic steerable

Store compact parameters such as Cholesky/SPD filter shape, history alpha, history clamp, residual/detail gain and confidence bias. Reconstruct the analytic kernel at runtime.

## Atlas family B: direct learned residual filter

Fit small filters around a stable baseline interpolator. Candidates: 3x3, 9-13-tap cross/diamond, 5x5 reference.

Result = baseline + learned residual.

## Factorized atlas

Prefer:
SpatialAtlas[S] + TemporalCorrection[T] + PhaseCorrection[P]
over one monolithic table. Also test low-rank compositions such as base[S] + U[S]*V[T].

## Teacher fitting

For each sample capture LR neighborhood, valid warped history, descriptor, jitter phase, FSR4 output and native HR target when available.

Possible target: beta*nativeHR + (1-beta)*FSR4Teacher. Tune beta; do not hardcode.

Direct filters: robust ridge regression per bucket with parent regularization/backoff for sparse classes.

Analytic filters: fit low-dimensional parameters against temporal sequences.

## Anti-flicker interpolation

Hard descriptor bins may flicker. Test orientation-neighbor blend, strength/coherence interpolation, temporal hysteresis and parameter-space interpolation.

## Memory example

8192 entries * 8 FP16 values * 2 bytes = 128 KiB. Several atlases remain tiny relative to VRAM.

Benchmark StructuredBuffer, ByteAddressBuffer and texture storage.

## Sampling

Implement 4-bilinear-tap, 5-tap, 8-bilinear-tap and direct reference filters. Use Gather/bilinear hardware when semantically valid. Compare tile-coherent indirect dispatch with a unified coherent shader.
