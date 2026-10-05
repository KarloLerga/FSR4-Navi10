# Oracle Suite V2

Do not train a major network before these experiments run on representative multi-frame teacher data. Every control approximation must be judged after final reconstruction, not only by parameter MSE.

## O0 - exact offline POST replay

Using captured:
- raw p0..p3
- exact current reconstruction source
- exact reprojected history
- render/output geometry
- jitter/scale/exposure semantics

reproduce FSR4 POST from pinned source math.

Compare to captured final RGB across multiple frames, presets and resolutions. If this gate fails, stop all downstream training and fix capture/replay semantics.

## O1 - teacher control distributions

Report:
- raw p histograms
- transformed rho/sx/sy/blend distributions
- saturation frequencies
- spatial total variation/gradients
- temporal delta after reprojection
- correlations with semantic input channels
- correlations with FSR3 semantics
- breakdown by scene class, preset and tier

Do not over-penalize raw logits when different saturated logits map to nearly identical physical controls.

## O2 - control spatial-bandwidth oracle

Downsample teacher control fields to:
- 1/2 linear resolution
- 1/4 linear resolution
- 1/8 linear resolution

Reconstruct with:
1. bilinear
2. bicubic/reference
3. guided/depth-aware interpolation
4. bilateral-grid slicing

Run source-equivalent POST and evaluate final RGB and temporal behavior.

This is a highest-priority oracle. A 1/4-linear control grid requires only 1/16 as many spatial prediction sites.

## O3 - control pyramid decomposition

Represent:

```text
control_full = upsample(control_coarse) + sparse_edge_residual
```

Test 1/4 and 1/8 coarse grids. Measure residual energy and percentage of tiles needing correction near depth edges, motion discontinuities, reactive areas, disocclusion and large teacher-control gradients.

## O4 - constant/preset/jitter baseline

Fit extremely cheap baselines:
- global mean by preset/tier
- mean by jitter phase
- tile/class means

Run exact POST. This tells how input-dependent teacher decisions really are.

## O5 - zero-network AnalyticControl

Compute current/history signal descriptors and structure-tensor statistics. Fit increasingly capable mappings to teacher controls:
1. closed form
2. linear/affine
3. small polynomial/rational
4. LUT

No CNN. Evaluate final RGB.

## O6 - control/state rank

Analyze:
- normalized 3x3 teacher kernel weights
- blend
- recurrent normalized U8 state

Run PCA/SVD and channel ablations. For K=1..8, decode approximate controls/state and replay final output.

For recurrent state test:
- remove channels one at a time
- K-dimensional linear latent
- lower-resolution state grid
- prediction from previous state

## O7 - spatial-kernel codebook

Convert teacher rho/sx/sy into exact normalized 3x3 kernel weights. Cluster K in:
- 8,16,32,64,128,256

Test:
- nearest kernel
- interpolated top-2
- jitter-phase-specific codebook

Keep teacher blend/history exact first. Evaluate final RGB.

## O8 - Delta4 scalar basis

With aligned FSR3:

```text
A = C - H
Y = T - H
alpha = dot(A,Y) / max(dot(A,A), eps)
O = H + alpha*A
```

Evaluate unconstrained and alpha clamped to [0,1], per pixel, per tile and low-resolution alpha grids.

## O9 - Delta4 multi-basis

Add cheap directions:
- Laplacian/current high-pass
- difference of two cheap interpolation kernels
- gradient-normal detail
- gradient-tangent detail
- FSR3 shading/reactive confidence-related basis

Solve regularized 2/3/4-dimensional least squares offline. Determine whether a few coefficients can represent the FSR4 quality delta.

## O10 - offset/resampling oracle

Inspired by efficient rasterized SR offset prediction, construct candidate current samples:
- center
- +/- x
- +/- y
- diagonals
- optional subpixel samples along local edge normal/tangent

Measure whether teacher reconstruction can be represented by selecting/mixing a tiny subset plus history. Report how often zero offset or one neighbor is sufficient.

## O11 - FSR3-to-FSR4 residual sparsity

Compute:
`DeltaRGB = FSR4_teacher - FSR3_output`

Also compute luma, gradient, FLIP/perceptual and temporally reprojected errors.

For 8x8 and 16x16 tiles report:
- fraction below near-zero threshold
- fraction below selected teacher-mimic threshold
- fraction below perceptual/JND-like threshold
- error class distribution

This determines whether adaptive compute is worthwhile.

## O12 - temporal control reuse

Reproject previous teacher controls, blend and recurrent state using the trusted motion convention. Compare to current teacher.

Report:
- stable pixel fraction
- stable 8x8/16x16 tile fraction
- error versus state age
- refresh requirement
- failures by disocclusion/reactive/specular class

Also test:
`control_t = warp(control_t-1) + small_delta`

## O13 - ideal multi-exit routing

Define hypothetical exits:
- Exit0 analytic/constant/linear
- Exit1 coarse control grid
- Exit2 tiny Shift1x1
- Exit3 larger Param4 predictor
- Hard fallback NaviQSR

For each tile, offline determine the first exit whose final RGB meets quality thresholds.

Report:
- ideal exit population
- theoretical work
- spatial maps
- temporal exit-switch rate

Only build runtime routing if this upper bound shows a large easy fraction.

## Required outputs

Generate:
- `docs/PARAM4_ORACLE_RESULTS_V2.md`
- `artifacts/results/oracle_v2_summary.json`
- machine-readable per-oracle files
- representative heatmaps/difference images

The report must explicitly state which architecture the measurements support and which ideas failed.
