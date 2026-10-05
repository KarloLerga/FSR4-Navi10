# Delta4 Basis Projection Oracle

This is a cheap analytical experiment that should happen immediately after teacher + FSR3 captures exist.

## Goal

Determine whether FSR4's teacher output can be closely represented as a low-dimensional combination of signals FSR3 already has.

If yes, runtime may only need to predict a few coefficients instead of a neural output image or full FSR4 control field.

## Basis 0 - scalar current/history blend

Let:

- `C` = FSR3 current upsample candidate before temporal accumulation,
- `H` = reprojected FSR3 history,
- `T` = FSR4 teacher output in matching color/exposure space.

Model:

```text
O = H + alpha (C - H)
```

For unconstrained least squares per pixel:

```text
A = C - H
Y = T - H
alpha = dot(A,Y) / max(dot(A,A), epsilon)
```

Also evaluate clamped `alpha in [0,1]`.

Report oracle quality and alpha distribution.

## Basis 1 - add one high-frequency/detail direction

Define cheap detail candidate `D`.

Candidates:

- current - 3x3 Gaussian(current),
- current - bilinear/down-up current,
- Laplacian luma projected back to RGB/luma,
- directional edge residual,
- difference between two cheap reconstruction kernels.

Model:

```text
O = H + alpha A + beta D
A = C - H
```

Per pixel solve:

```text
g00 = dot(A,A) + lambda
g01 = dot(A,D)
g11 = dot(D,D) + lambda
r0  = dot(A,Y)
r1  = dot(D,Y)

det = g00*g11 - g01*g01
alpha = (r0*g11 - r1*g01) / det
beta  = (r1*g00 - r0*g01) / det
```

Evaluate unconstrained and practical constrained ranges.

## Basis 2 - spatially steerable detail

Add two edge-oriented detail bases:

- along-edge filtered difference,
- across-edge filtered difference.

Then solve a 3x3 system per pixel offline.

The Delta4 runtime path would predict only 3 coefficients.

## Coverage metric

Do not report only average PSNR.

For each oracle define per-pixel/per-tile teacher error and report:

- percentage below 1/255 RGB error,
- percentage below 2/255,
- percentage below chosen FLIP/JND threshold,
- hard-tile ratio at 8x8 and 16x16,
- error by class: flat, edge, thin, reactive, disoccluded, moving, specular.

This tells us whether an adaptive architecture is viable.

## Decision

If scalar/basis oracle covers a large majority:

`Delta4Basis` becomes the main runtime path.

Only hard regions use Param4Shift/NaviQSR.

If it does not, direct Param4 control distillation remains primary.
