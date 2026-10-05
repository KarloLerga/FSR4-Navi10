# Param4 - Direct FSR4 Control Distillation

## Objective

Replace the expensive full FSR4 neural graph while preserving the actual FSR4 post reconstruction mechanism.

Param4 target:

```text
4 filter/blend controls
+
4 recurrent channels
```

not RGB.

## Variant 1 - Param4ExactPre

Inputs use exact FSR4 pre semantics:

```text
current luma
history luma
chroma distance
previous recurrent[4]
```

The existing upstream FSR4 pre and post stages remain.

Only the 14-pass model body is replaced.

This is the cleanest quality experiment because the Param4 network's input/output contract mirrors the teacher.

## Variant 2 - Param4Semantic

Add inexpensive already-available semantic channels:

- motion magnitude,
- depth gradient,
- disocclusion,
- reactive,
- shading change,
- luma instability,
- accumulation/lock.

Only retain added channels if they improve teacher matching enough to justify their cost.

## Proposed clean-room Shift1x1 model

Public SR research shows parameter-free spatial shifts can restore spatial context to fully 1x1-convolution networks.

Implement the idea clean-room; do not copy non-compatible source code.

### Core block

Conceptually:

```text
x
 -> 1x1 channel mix
 -> parameter-free channel-group spatial shift
 -> activation
 -> 1x1 channel mix
 -> residual add
```

### Critical GPU implementation rule

Do not materialize a shifted tensor.

For each input channel group, calculate the shifted source coordinate directly while loading the channel for the 1x1 matrix multiplication.

This turns shift into address arithmetic/load selection instead of a separate pass.

### Direction groups

Candidate channel groups:

- center,
- left/right/up/down,
- four diagonals.

Autotune whether center channels are useful.

### Receptive field

Use shift dilation schedule instead of 3x3 convolution:

```text
block 0: dilation 1
block 1: dilation 1
block 2: dilation 2
block 3: dilation 2
block 4: dilation 4
```

Exact schedule is architecture-searchable.

## Spatial resolution

Do not begin by predicting display-resolution controls with a deep model.

Run the control-grid oracle first.

Candidate trunk resolutions:

- 1/2 output,
- 1/4 output,
- 1/8 output.

Upsample controls with:

- bilinear,
- edge-aware guided slicing,
- bilateral-grid slicing.

Use sparse edge refinement only if needed.

## Suggested starting model family

Candidate widths:

`12, 16, 20, 24, 32`

Blocks:

`2..8`

Two-level candidate:

```text
half-resolution stem, width 16-24
3-5 Shift1x1 blocks
optional space-to-depth / quarter-resolution branch
2-4 Shift1x1 blocks
merge
control/recurrent heads
```

The final architecture is selected by actual RX 5700 XT milliseconds and teacher quality, not FLOPs.

## True FP16

Inference requirements:

- `float16_t` / packed half operations,
- DXC `-enable-16bit-types`,
- inspect DXIL and RGA gfx1010 ISA,
- no silent FP32 activation promotion in the intended hot path,
- FP32 only where numerically necessary.

Current NaviQSR uses FP32 activations/MAC. Param4 must explicitly test a true FP16 path.

## Physical-control output

Prefer testing output heads that directly predict:

```text
rho in (-1,1)
sx in (0,2)
sy in (0,2)
blend in (0,1)
recurrent in (0,1)^4
```

Possible bounded parameterization during training can be removed/fused for inference.

Also keep a raw-logit teacher-matching mode for exact distillation comparison.

## Losses

Training loss must include both control accuracy and final reconstructed image quality.

Suggested:

```text
L = w_param * L_controls
  + w_rec   * L_recurrent
  + w_rgb   * Charbonnier(post(Param4), teacherRGB)
  + w_gt    * Charbonnier(post(Param4), nativeHR) where available
  + w_grad  * gradient/high-frequency loss
  + w_temp  * temporal consistency
  + w_hard  * weighted difficult-region loss
```

Compare raw-parameter loss versus physical-kernel loss.

A small control error that causes nearly identical final 3x3 weights should not be over-penalized.

## Recurrent training

Do not train each frame independently.

Unroll sequences:

- 8 frames minimum during development,
- 16/32 when feasible.

Feed the Param4 recurrent output into the next Param4 frame.

Teacher-forcing-only training is insufficient because recurrent drift will be hidden.

Use scheduled sampling or progressive rollout:

1. teacher recurrent during warmup,
2. mixed teacher/Param4 recurrent,
3. full Param4 recurrence.
