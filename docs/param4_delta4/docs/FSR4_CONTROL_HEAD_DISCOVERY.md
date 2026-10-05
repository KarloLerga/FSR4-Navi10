# Critical Source Discovery - What FSR4 Actually Predicts

This is the most important architectural observation in this addendum.

## 1. FSR4 output is not direct RGB

The FSR4 v07 4.0.2 model decoder ends with 8 output channels at display resolution.

In the upstream post implementation, these are interpreted as:

- channels 0..3: reconstruction/control parameters,
- channels 4..7: recurrent state.

The final RGB is produced by deterministic postprocessing.

## 2. Four model parameters

The post shader uses four scalar values per output pixel.

Let raw model values be:

`p0, p1, p2, p3`

The shader derives approximately:

```text
rho   = tanh(p0)
sx    = 2 * sigmoid(p1)
sy    = 2 * sigmoid(p2)
blend = sigmoid(p3)
```

For a 3x3 neighborhood of the current low-resolution input, it computes an anisotropic correlated Gaussian weight.

For spatial offset `(x,y)` after scale/jitter mapping:

```text
E = sx^2 * x^2
  + 2 * rho * sx * sy * x*y
  + sy^2 * y^2

w = exp(-0.5 / 0.47^2 * E)
```

The normalized weighted current reconstruction is then blended with reprojected temporal history:

```text
output = current_filtered * (1 - blend)
       + history_reprojected * blend
```

The model therefore learns **how to reconstruct**, not arbitrary output RGB.

## 3. Four recurrent channels

The remaining four output channels are passed through sigmoid and saved as recurrent state for the next frame.

The next frame's network input includes that recurrent state.

## 4. FSR4 pre-network inputs are compact

The upstream pre stage performs substantial temporal/image work before the CNN:

- upsample current input into the model's color space,
- dilate/select motion,
- test local disocclusion,
- reproject previous history,
- reproject previous recurrent state,
- lightly rectify reprojected history toward current,
- convert current/history into YCbCr-like components.

The model input is essentially:

1. current luma,
2. history luma,
3. chroma/color distance between current and history,
4. recurrent channel 0,
5. recurrent channel 1,
6. recurrent channel 2,
7. recurrent channel 3,
8. padding/unused channel in storage.

This is a far smaller semantic problem than generic RGB-to-RGB super-resolution.

## 5. Consequence

Do not ask a lightweight model to learn all of super-resolution from scratch.

Instead train it to predict the exact FSR4 control/state outputs.

That preserves the most characteristic part of the FSR4 reconstruction formulation while allowing the expensive 14-pass U-Net-style network to be replaced.

## 6. Required teacher capture values

For every teacher frame capture at minimum:

```text
frame metadata
input color
input depth
input motion
jitter
exposure
reset flag
reactive / transparency masks when present

FSR4 reprojected history color
FSR4 current/upscaled input used by post
FSR4 model input tensor (7 semantic channels)
FSR4 raw model parameters p0..p3
FSR4 transformed physical parameters rho,sx,sy,blend
FSR4 recurrent output r0..r3
FSR4 final output RGB
```

Optional but valuable:

- pass0 features,
- bottleneck features,
- pass11/pass12 features,
- disocclusion/debug masks.

## 7. New Param4 optimization target

The smallest meaningful output target is not RGB.

It is:

```text
[rho, sx, sy, blend, r0, r1, r2, r3]
```

or the equivalent raw logits if matching the upstream network numerically is preferred.

Predicting transformed physical parameters can remove sigmoid/tanh work from the runtime post path, provided training and clamping guarantee valid parameter ranges.
