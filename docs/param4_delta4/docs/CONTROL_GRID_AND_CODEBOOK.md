# ControlGrid - Predict FSR4 Decisions at Low Spatial Density

The FSR4 post operator is local and its model output is a control field. That makes it a strong candidate for guided low-resolution prediction.

## 1. Required oracle first

Run `CONTROL_FIELD_ORACLES.md` before implementation complexity.

If teacher controls are sufficiently smooth, build:

```text
small low-resolution predictor
       -> coarse control grid
       -> edge-aware slicing/upsampling
       -> exact FSR4 post filter
```

This mirrors a proven family of real-time image-processing architectures where a network predicts low-resolution coefficients and a cheap guided/bilateral stage reconstructs them at high resolution.

## 2. Bilateral control grid

A candidate grid axis set:

```text
x
y
guide_luma or edge coordinate
```

Grid stores:

```text
rho
sx
sy
blend
optional recurrent corrections
```

At each output pixel:

- compute guide value from current luma/depth/edge,
- slice/interpolate nearby grid vertices,
- obtain control values,
- execute FSR4 post filter.

Benchmark against simple bilinear controls. Do not assume bilateral grid wins.

## 3. Edge residual overlay

If controls are smooth except near discontinuities:

```text
coarse grid
+
sparse edge residual tiles
```

Edge residual prediction is activated around:

- depth discontinuities,
- reactive regions,
- large teacher-control gradient,
- disocclusion.

This can keep most compute at 1/4 or 1/8 resolution.

## 4. Kernel codebook

The spatial control triple defines only a normalized 3x3 filter.

Cluster teacher filters in final normalized-weight space.

Store K kernels in constant/texture memory.

For finite common jitter/scale phases, optionally precompute phase-specific kernel versions.

Runtime then needs:

- filter ID,
- blend,
- recurrent state.

This eliminates per-pixel Gaussian exponentials for the spatial filter.

## 5. Hierarchical code prediction

Avoid a 1024-way dense classifier at full resolution.

Possible hierarchy:

```text
coarse filter family (e.g. 16 classes)
+
local sub-index (e.g. 16 classes)
```

or derive nearest code from predicted low-dimensional control values.

Only use classifier/codebook if it is faster than continuous controls in real GPU timing.

## 6. Exp LUT

If continuous controls remain:

Bound the Gaussian energy range seen in teacher captures and evaluate a tiny 1D LUT for `exp(-kE)`.

Use hardware linear interpolation.

This is secondary to control-grid compute reduction; do not optimize transcendental cost before profiling says it matters.
