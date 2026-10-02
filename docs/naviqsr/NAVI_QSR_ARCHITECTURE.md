# NaviQSR Detailed Architecture Specification

## 1. Required pipeline

```text
Inputs
  LR color
  depth
  motion vectors
  reactive/T&C masks
  exposure
  jitter
  previous HR output
  previous latent cache
        |
        v
Preprocess + motion dilation
        |
        +--> Warp previous HR
        |
        +--> Warp cached latent state
        |
        v
Uncertainty / validity map
        |
        v
Space-to-depth / polyphase packing
        |
        +--> optional fixed Haar phase transform
        |
        +-----------------------+
        |                       |
        v                       v
LF structural stem         HF/detail features
        |                       |
        v                       |
Low-spatial FP16 trunk          |
        |                       |
        +-----------+-----------+
                    |
                    v
          compact control head
                    |
          +---------+----------+
          |                    |
          v                    v
 analytic filter params   residual/detail params
          |                    |
          v                    |
current reconstruction         |
          |                    |
          +---------+----------+
                    |
                    v
        history clamp/blend
                    |
                    v
                 HR output
                    |
             recurrent cache
```

`NaviQSR_MCLD` replaces dense trunk evaluation on stable tiles with warped cached latent features.

---

# 2. Suggested initial channel topology

This is a strong starting point, not a permanent hardcoded truth.

Assume image-like packed input after 2x space-to-depth.

### Stage S0 — analytic preprocessing
No neural channels:
- linear color / luma
- gradients
- depth derivatives
- motion divergence
- reactive confidence
- warped-history residual
- validity

### Stage S1 — shallow projection
At half input spatial:
- 24 FP16 channels

Candidate:
- phase-packed RGB/current features
- warped-history features
- selected geometry/confidence features

### Stage S2 — LF trunk
At half input spatial:
- 24 channels
- 3–4 reparameterizable blocks

### Optional S3 — bottleneck
At quarter input spatial:
- 32 channels
- 2–4 blocks

This stage should be included only if architecture search says the receptive-field/quality gain offsets transition cost.

### HF/detail branch
At half input spatial:
- 8–12 channels
- 1–2 shallow blocks
- may be partially analytic

### Recurrent latent
- 8–16 FP16 channels at half spatial
- optionally 8 channels at quarter spatial

### Control head
At half input spatial:
- 6–12 channels total
- converted/interpolated to output control values cheaply

Avoid a large neural decoder at output resolution.

---

# 3. Training block and export forms

Train a rich block with:
- residual connection
- optional linear 1x1 expansion
- 3x3 spatial transform
- linear 1x1 contraction
- single activation after the foldable chain
- optional train-only auxiliary branch

At export generate:

### Variant A — `rep3x3`
Fold linear operations to one 3x3.

### Variant B — `bottleneck`
Keep 1x1 -> spatial -> 1x1 if lower real latency.

### Variant C — `partial_spatial`
Run 3x3 spatial mixing only on a channel subset, then pointwise mix, inspired by FasterNet-like behavior.

Actual RX 5700 XT timing decides per stage.

---

# 4. FP16 rules

- DXC must compile with true 16-bit types enabled.
- Audit DXIL/ISA; do not trust HLSL spelling alone.
- Inner arithmetic should emit packed FP16 operations where expected.
- Avoid repeated FP16<->FP32 conversion.
- Use FP32 only where range/stability requires it:
  - accumulation candidates if FP16 visibly fails,
  - exposure transformations,
  - sensitive normalization/statistics.
- Prepack constants two FP16 values per 32-bit word when beneficial.
- Compare wave32/wave64 shader variants.

---

# 5. AKR implementation details

## 5.1 Parameter field

Suggested base control vector:

```cpp
struct FilterControl {
    half s0;
    half s1;
    half s2;
    half alphaLogit;
    half clampLog;
    half residualGateLogit;
    half detailGain;
    half confidence;
};
```

Storage may pack into 4xFP16 pairs.

## 5.2 SPD reconstruction

```hlsl
float l11 = exp2(clamp((float)s0, -3.0, 3.0));
float l21 = (float)s1;
float l22 = exp2(clamp((float)s2, -3.0, 3.0));

float q00 = l11*l11;
float q01 = l11*l21;
float q11 = l21*l21 + l22*l22;
```

For offset `d`:

```hlsl
float e = q00*d.x*d.x + 2.0*q01*d.x*d.y + q11*d.y*d.y;
float w = exp2(-0.7213475204444817 * e);
```

Clamp eigenvalue-like scale indirectly by limiting `s0/s2/l21` so the network cannot generate an unusably narrow or infinitely wide filter.

## 5.3 Current candidate

Sample LR/current input in output-to-render coordinate space.

Create multiple candidate implementations:
- scalar direct 3x3
- 4 bilinear sample ellipse
- 5 sample ellipse
- 8 sample ellipse

Do not normalize with division by zero; enforce epsilon.

## 5.4 History

Warp previous HR history separately at output resolution.

Use confidence:
- analytic disocclusion
- predicted confidence
- reactive masks

Clip history before blend.

---

# 6. MCLD implementation details

## 6.1 Cache buffers

Use ping-pong:
- `latentA_prev`, `latentA_cur`
- optional `latentB_prev`, `latentB_cur`
- `latentValidity`
- `previousDepthMoments`
- `previousSignature`

Avoid reallocating per frame.

## 6.2 Cheap tile signature

For each latent tile generate a small signature before deciding reuse:

- mean luma
- luma variance
- edge energy
- mean/min depth
- max depth gradient
- mean motion
- motion variance/divergence
- reactive max/mean
- warped color residual

Compare to warped previous signature.

This is much cheaper than running the trunk.

## 6.3 Active mask

Each tile has:
- `ACTIVE`
- `REUSE`
- `INVALID`

`INVALID` must recompute and may suppress history.

## 6.4 GPU compaction

Pipeline:
1. classify tiles
2. prefix-sum/compact active indices
3. write indirect dispatch count
4. execute sparse tile kernel
5. if sparse count exceeds tuned threshold, skip compaction result and run dense kernel

A simpler always-dispatch-with-early-return variant may be faster for some kernels. Autotune both.

---

# 7. Phase-specialized jitter path

Represent jitter as exact normalized renderer offsets.

At model export:
- generate N known phase-conditioned head/stem weights where sequence is finite,
- store all N in the model pack,
- select by phase ID.

If the integration does not expose a reliable phase ID:
- hash/quantize exact jitter to a cached weight set,
- or use generic model.

Never select the wrong phase just for speed.

---

# 8. Full-FSR4 interaction

`FullFSR4_FP16` is not obsolete.

Use it for:
- teacher output generation
- teacher intermediate feature capture
- reset frames
- quality debugging
- occasional validation
- fallback when network confidence is catastrophically low, if the user enables that expensive safety mode

Production `NaviQSR` should not invoke the full teacher every frame.

---

# 9. network feature distillation

Instrument teacher tensors at useful scales:
- half spatial
- quarter spatial
- bottleneck
- decoder half spatial

Do not force network channel count to equal teacher.

During training use train-only 1x1 projectors:
- network feature -> teacher feature dimension

Feature loss on normalized feature maps.

Projectors are removed after training.

---

# 10. Architecture-search dimensions

```yaml
trunk_width: [16, 20, 24, 28, 32]
trunk_blocks: [3, 4, 5, 6, 7, 8]
use_quarter_stage: [false, true]
quarter_width: [24, 32, 40]
quarter_blocks: [1, 2, 3, 4]
hf_width: [4, 8, 12, 16]
hf_blocks: [0, 1, 2]
latent_width: [4, 8, 12, 16]
control_channels: [6, 8, 10, 12]
block_export: [rep3x3, bottleneck, partial]
filter_taps: [4, 5, 8]
polyphase_mode: [raw, haar, learned1x1]
tile_size: [8, 16]
```

Prune invalid/obviously huge combinations.

Do not brute-force train every Cartesian product from scratch.

Use staged search:
1. dense quality architecture
2. kernel/export timing
3. temporal reuse
4. final Pareto selection
