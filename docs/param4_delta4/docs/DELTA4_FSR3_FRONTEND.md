# Delta4 - Reuse FSR3.1 as the Temporal Front-End

## Core idea

FSR3.1 already runs well on RX 5700 XT and already computes many of the semantic decisions a lightweight FSR4-like policy would otherwise need to recompute.

Do not build a second temporal preprocessing stack next to FSR3 unless necessary.

## FSR3 signals available from open source

The FSR3 upscaler pipeline already contains resources/logic for:

- dilated motion vectors,
- dilated depth,
- reconstructed previous depth,
- reprojected history,
- current upsampled color,
- reactive mask,
- disocclusion,
- shading change,
- accumulation state,
- thin-feature lock/new locks,
- luma history,
- luma instability,
- farthest depth,
- exposure information.

These are precisely the kinds of features a learned history/filter policy needs.

## Variant A - Delta4Control

Keep FSR3's upstream temporal preparation.

Before/inside final accumulation, predict a compact correction policy from existing FSR3 state.

Possible outputs:

```text
FSR4-like rho,sx,sy
history blend correction
history clamp correction
lock/accumulation correction
small recurrent state
```

Use an FSR4-style 3x3 current filter where helpful.

## Variant B - FSR4 parameter correction

Fit a baseline mapping from FSR3 signals to FSR4 physical controls, then predict only the residual:

```text
p_teacher = p_baseline(FSR3 state) + delta_p
```

A simple baseline can be:

- constant by preset/phase,
- THFA/LUT mapping,
- linear model.

The neural/ShiftNet head then predicts smaller residual values.

## Variant C - Delta4Basis

Use the basis oracle defined separately.

Runtime output can become only:

```text
alpha
beta1
beta2
confidence
```

for a cheap combination of FSR3 current/history/detail candidates.

If oracle coverage is high, this is likely the fastest architecture.

## Do not double-pay for history

Avoid:

```text
full FSR3 output
then another independent full-resolution reproject/filter/history pass
```

Instead integrate the learned/teacher-distilled policy into the FSR3 accumulation stage or reuse its already loaded/reprojected history.

The ideal implementation fuses:

- existing FSR3 history data,
- Delta4 decision,
- final filter/blend,

inside one output-stage dispatch where possible.

## Instrumented FSR3 baseline

Build a pinned FSR3.1 baseline using the already fetched FidelityFX SDK.

Add capture-only outputs for:

```text
C = current upsampled color before final accumulation
H = reprojected history before final accumulation
reactive
disocclusion
shading_change
accumulation
luma_instability
lock
motion/depth derived features
final FSR3 output
```

Instrumentation must not change normal output.

Feed identical temporal input sequences to:

- FSR3 capture,
- FSR4 teacher capture.

This creates aligned Delta4 training rows.

## Performance budget

Use measured FSR3 as the baseline, not an arbitrary theoretical number.

The official FSR3.1 RX 5700 XT performance data is a useful sanity reference, but local harness timing is authoritative.

The correction stage should be designed so its cost is a small fraction of FSR3 itself.

Do not promise a fixed target before local full-resolution measurement.
