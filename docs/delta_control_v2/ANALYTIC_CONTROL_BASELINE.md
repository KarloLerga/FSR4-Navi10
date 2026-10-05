# AnalyticControl - zero-network baseline

## Purpose

FSR4 POST applies an anisotropic local filter and temporal blend. Classical image/temporal descriptors already estimate orientation, anisotropy and confidence. Test how much teacher behavior is explainable without a neural network.

## Structure tensor

From a stable luma/current-source representation:

```text
gx = dI/dx
gy = dI/dy
Jxx = blur(gx*gx)
Jyy = blur(gy*gy)
Jxy = blur(gx*gy)
```

The local tensor encodes edge orientation, strength and coherence.

For runtime, avoid expensive eigendecomposition if equivalent algebraic ratios/approximations are sufficient.

## Map to spatial teacher controls

Fit and compare:
1. hand-designed closed form
2. affine mapping from Jxx/Jyy/Jxy plus semantic features
3. low-order polynomial/rational mapping
4. small quantized LUT by orientation/strength/coherence
5. preset/jitter-phase-specific coefficient sets

Use teacher normalized 3x3 kernel weights as the fitting target where possible, not only raw p values.

## Map temporal evidence to blend

Features:
- current versus reprojected-history color/luma difference
- depth mismatch
- motion magnitude/divergence
- reactive/T&C
- FSR3 shading-change/accumulation if Delta4 is active

Fit logistic regression or a small LUT before any MLP.

## Recurrent baseline

Test reduced linear state-space models:

```text
z_t = A*z_(t-1) + B*x_t + b
r_t = clamp_or_sigmoid(C*z_t + D*x_t)
```

Search latent K=1..4. Compare final temporal RGB, not only state MSE.

## Why this matters

Even if AnalyticControl only solves easy regions, it can become Multi-Exit Exit0 and make the learned predictor responsible only for the teacher residual.
