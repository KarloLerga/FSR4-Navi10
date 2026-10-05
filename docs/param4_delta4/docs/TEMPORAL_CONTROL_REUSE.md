# Temporal Control Reuse - Cache Decisions, Not Deep Features

Previous addenda explored latent feature reuse. With the new FSR4 control-head understanding, an even cheaper reusable state exists.

## 1. Reproject previous control fields

State:

```text
rho,sx,sy,blend
recurrent[4]
confidence
```

Warp previous controls using motion vectors.

Compare current cheap semantic features against reprojected previous features.

Stable tile:

- reuse controls,
- optionally predict only a small delta.

Unstable tile:

- execute dense Param4 predictor.

## 2. Why this is preferable to caching deep latent tensors

- only eight channels,
- already physically meaningful,
- easier validity checks,
- lower memory bandwidth,
- easier debugging,
- no need to propagate sparse masks through every hidden convolution layer.

## 3. Invalidation

Force dense refresh on:

- camera cut/reset,
- out-of-bounds reprojection,
- depth mismatch,
- high disocclusion,
- reactive/transparency,
- exposure discontinuity,
- large render-scale change,
- confidence decay,
- excessive accumulated warp distance.

## 4. Refresh strategy

Even stable controls need bounded staleness.

Use:

- confidence decay,
- maximum age,
- distributed refresh schedule.

The refresh schedule must not create visible temporal patterns.

## 5. Sparse execution

Prefer tile-coherent refresh:

- 8x8 or 16x16 control tiles,
- active list compaction,
- indirect dispatch only if measured faster.

Compare with a unified shader and early return.

Dynamic GPU overhead can erase theoretical savings on small workloads.
