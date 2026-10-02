# QSSR Research Findings and Engineering Conclusions

## 0. Status and epistemic rules

This document separates three categories:

### VERIFIED
A fact directly supported by a public source.

### DERIVED
A calculation or engineering inference from verified facts.

### PROPOSED
A design proposed for this project. It may combine public techniques in a way not found in the searched literature. Do not call it globally novel without a formal literature/patent search.

---

## 1. The important QSSR discovery

### VERIFIED — Sony QSSR

On 2026-10-01 Sony announced **Quick Spectral Super Resolution (QSSR)** for the standard PS5. Sony describes two key innovations:

1. a **streamlined neural network architecture**
2. a **hand-tuned implementation that maximizes performance on PS5**

Sony explicitly says QSSR improves image detail and temporal stability, while PSSR on PS5 Pro remains the higher-quality tier.

Public reporting quoting Sony Principal Engineer Daniel Craig adds a crucial detail: base PS5 does not have PS5 Pro's dedicated ML path, so **QSSR relies primarily on FP16 math**, uses packed math heavily, and focuses on keeping the GPU pipeline full and amortizing costs around the math.

### VERIFIED — measured behavior

Digital Foundry's early test, as quoted by multiple sources, found:

- Marvel's Wolverine, 864p -> 1440p: QSSR was about **1.5–1.8 ms slower than Insomniac's previous upscaler** in the tested uncapped sequence.
- A 2160p-output fidelity test showed an approximately **4.4 ms frame-time hit**.

Important: the 1.5–1.8 ms number is **not the isolated total QSSR runtime**. It is an additional cost relative to the previous upscaler under that test.

### VERIFIED — base PS5 vs RX 5700 XT

Base PS5:
- RDNA2-based GPU
- 10.3 TFLOPS FP32
- 448 GB/s memory bandwidth

RX 5700 XT:
- RDNA1 / Navi10
- 9.75 TFLOPS FP32
- **19.51 TFLOPS FP16**
- 448 GB/s memory bandwidth

Sony says QSSR uses packed FP16 extensively. If one simply doubles the PS5 FP32 peak as the usual packed-FP16 arithmetic ceiling, that is about 20.6 TFLOPS FP16.

### DERIVED — why QSSR matters to this project

RX 5700 XT peak FP16 is about:

`19.51 / 20.6 ~= 0.947`

or roughly **95% of that simple PS5 packed-FP16 peak estimate**, and both have the same quoted external memory bandwidth.

This does **not** mean identical real performance. PS5 has:
- RDNA2 rather than RDNA1,
- a fixed console environment,
- different caches/compiler/API,
- custom platform features Sony can exploit.

But it is strong evidence that a **well-designed FP16 neural upscaler in this compute/bandwidth class is physically plausible**. Therefore the project should not assume that "FSR4-like quality on 5700 XT is impossible because it lacks modern matrix hardware."

The key is likely **architecture + execution layout**, not merely translating the current FSR4 INT8 operations to FP16.

---

## 2. Sony's public efficient-SR research gives a strong architecture clue

### VERIFIED — Sony patent US 2025/0005708

A Sony Interactive Entertainment Deutschland patent application by Marcos Conde describes a real-time image upscaler with:

- pixel-unshuffle before deep feature extraction,
- separate low-frequency and high-frequency feature paths,
- deep convolution on reduced spatial dimensions,
- structural re-parameterization for inference.

The patent states that after pixel-unshuffle and shallow feature extraction, later convolution layers can operate at half width/height and their computational cost can be reduced **on the order of 75%** in the illustrated configuration, without a similar reduction in final image quality.

The patent also describes training a `1x1 -> 3x3 -> 1x1` linear sequence and algebraically folding it into **one 3x3 convolution for inference**, assuming no nonlinearity prevents the fusion.

It also permits content-specific model weights.

### VERIFIED — earlier public research by the same author

The 2023 CVPRW paper *Towards Real-Time 4K Image Super-Resolution* by Zamfir, Marcos V. Conde, and Timofte reports the same broad strategy:

- extract important high-frequency details efficiently,
- reduce spatial resolution of deep feature maps,
- use pixel-unshuffle,
- use a simplified NAFNet-like block,
- use structural re-parameterization.

The project has public code (`RT4KSR`).

### IMPORTANT LIMITATION

There is no public source proving that this patent or RT4KSR is the exact internal architecture of QSSR.

Do **not** write:
> "QSSR uses this patent."

Correct wording:
> "This public Sony-related efficient-SR work is highly relevant to the design constraints QSSR publicly describes and provides concrete techniques worth evaluating."

Also, the word **Spectral** in QSSR does not prove that QSSR uses Fourier or wavelet transforms.

---

## 3. Existing FSR4 topology tells us where the waste is

The editable/reference FSR4 v07 shader topology contains an encoder/decoder with roughly:

- pass 0: full input -> half spatial, 16 channels
- passes 1–2: high-spatial 16-channel residual blocks
- pass 3: -> quarter spatial, 32 channels
- passes 4–5: 32-channel blocks
- pass 6: -> eighth-ish spatial, 64 channels
- passes 7–8: bottleneck
- pass 9: upsample + skip
- pass 10: decoder block
- pass 11: upsample + skip
- pass 12: high-spatial block
- pass 13: final high-resolution output head

The generated FSR4 HLSL is already substantially fused. Therefore "just fuse more operators" is not a sufficient breakthrough.

### DERIVED

A rough source-level MAC accounting puts a large fraction of compute in the high-spatial encoder/decoder stages. Exact percentage depends on how fused/partial convolutions are counted, but a reasonable source-derived estimate is on the order of **~60%** for the highest-spatial stages around passes 1/2/11/12/13.

The architectural opportunity is therefore:

> **Avoid performing a deep neural trunk repeatedly on large spatial feature maps.**

---

## 4. Important exact algebraic observations for FSR4

These are exact transformations where layout/padding semantics match.

### 4.1 2x2 stride-2 convolution

A `2x2, stride=2` convolution is equivalent to:

1. `space_to_depth_2x` / pixel-unshuffle
2. a `1x1` convolution over the four spatial phases.

This does not automatically reduce the MAC count, but it can:
- improve memory layout,
- expose phase structure,
- fuse better with downstream operations,
- make fixed polyphase transforms cheap.

### 4.2 2x2 stride-2 transposed convolution

With non-overlapping stride/kernel conditions, a 2x2 stride-2 transposed convolution can be represented as:

1. `1x1` convolution producing phase channels
2. pixel-shuffle.

Again, the arithmetic count is similar, but it can improve locality and permit fusion with output reconstruction.

### 4.3 Why Sony-style pixel-unshuffle still matters

FSR4 pass 0 already performs a conceptually similar spatial reduction. Therefore merely replacing pass 0 with `pixel_unshuffle` is **not** the major win.

The win comes from designing a **network architecture that keeps the expensive deep body at reduced spatial resolution and avoids reconstructing large neural feature maps until the final cheap stage**.

---

## 5. Temporal reuse is a second independent acceleration dimension

### VERIFIED — ReFrame, ICML 2025

ReFrame caches intermediate encoder/decoder features across frames and dynamically refreshes them when stale.

Reported:
- ~1.4x average speedup with negligible quality loss,
- a lower-sensitivity supersampling example reaches up to ~1.85x inference speedup.

### VERIFIED — MotionDeltaCNN

MotionDeltaCNN extends sparse CNN delta processing to moving-camera video and reports large improvements versus DeltaCNN on moving-camera workloads.

Crucial warning from the paper:
- sparse execution is not automatically faster;
- if work becomes too small to utilize the GPU, skipping tiles may not reduce latency;
- dense fallback is important.

### DERIVED — games have a major advantage

A game upscaler receives:
- engine motion vectors,
- depth,
- current color,
- often reactive/transparency/composition masks,
- camera jitter.

Therefore this project does not need to estimate inter-frame correspondence purely from RGB video.

This enables a more reliable **motion-compensated latent cache**.

---

## 6. Efficient Neural Supersampling gives another concrete clue

The ICCV 2023 paper *Efficient Neural Supersampling on a Novel Gaming Dataset* reports a neural supersampling design around **4x more efficient** than prior methods at similar accuracy.

Important techniques:

- warp previous HR color/features,
- depth-informed motion-vector dilation,
- recurrent historical features,
- output candidate reconstruction plus blending information,
- jitter-conditioned convolutions.

The paper's ablation reports a measurable quality loss when jitter-conditioned convolution is removed.

Because game jitter follows a deterministic sequence, jitter-dependent first/last layer parameters can be **precomputed for the finite jitter phases**, avoiding a runtime conditioning network.

This fits Navi10 extremely well:
- more compiled shader/weight variants,
- less dynamic work,
- no need to minimize binary size.

---

## 7. The biggest new direction: neural network predicts reconstruction decisions, not RGB

### VERIFIED inspiration — Intel patent US 2026/0099895

A public Intel patent describes a temporally amortized supersampling pipeline in which a network can predict parameters for an **analytic reconstruction filter** rather than output a large arbitrary per-pixel filter.

One example uses an anisotropic Gaussian with only **3 predicted parameters** rather than materializing a 3x3 filter's 9 coefficients. The analytic filter is reconstructed on-chip.

The patent also shows:
- motion-vector-warped history,
- confidence,
- pixel-unshuffle,
- a quantized neural autoencoder,
- pixel-shuffle,
- analytic filtering,
- temporal blending.

### PROPOSED project synthesis

Instead of making a smaller network reproduce FSR4's final RGB directly, use FSR4 as a teacher for a network that predicts:

- spatial reconstruction shape,
- temporal history confidence,
- history clamping/validity,
- residual/inpainting need,
- optionally a small high-frequency correction.

The bulk of the final pixel construction is then done by **cheap deterministic RDNA1-friendly texture sampling + packed FP16 math**.

This potentially moves a large amount of work out of the neural network.

---

# 8. Proposed new architecture: NaviQSR

Do not remove `FullFSR4_FP16`.

Add:

- `NaviQSR_Dense`
- `NaviQSR_Analytic`
- `NaviQSR_MCLD`
- `NaviQSR_Auto`

## 8.1 Inputs

Use the same type of temporal information expected by modern game upscalers:

- current low-resolution color, preferably linear/pre-exposed
- depth
- engine motion vectors
- reactive mask, when available
- transparency/composition mask, when available
- exposure/pre-exposure
- current and previous jitter
- output resolution and render resolution
- previous reconstructed high-resolution frame
- cached recurrent feature state

If a source is unavailable, define conservative fallbacks. Missing masks must reduce reuse aggressiveness, never silently increase it.

---

## 8.2 Preprocess and motion compensation

For current output pixel/sample `p`, define the previous-frame sample coordinate approximately as:

`p_prev = p + motion(p) + jitter_prev - jitter_cur`

with exact sign/convention controlled by the integration API.

Use depth-informed motion dilation around edges:
- inspect a small depth neighborhood,
- choose the motion of the foreground/closest surface when appropriate,
- mark ambiguous regions as low confidence.

Warp:
- previous HR reconstruction,
- previous depth,
- selected latent feature maps,
- prior confidence.

Construct an uncertainty value from:

- depth mismatch,
- motion divergence,
- current vs warped luminance residual,
- reactive/T&C masks,
- out-of-bounds state,
- exposure discontinuity,
- camera-cut state.

Never reuse cached latents after:
- camera cut,
- resolution change,
- render-scale discontinuity beyond configured tolerance,
- invalid exposure jump,
- invalid motion vectors.

---

## 8.3 Reversible polyphase stem

### Proposed exact transform

Perform `space_to_depth_2x` on image-like channels, producing four spatial phases:

`p00, p10, p01, p11`

Optionally transform those four phases using a fixed orthonormal-like Haar/polyphase mixing:

```
LL = 0.5 * (p00 + p10 + p01 + p11)
LH = 0.5 * (p00 - p10 + p01 - p11)
HL = 0.5 * (p00 + p10 - p01 - p11)
HH = 0.5 * (p00 - p10 - p01 + p11)
```

The inverse uses the corresponding inverse fixed transform.

Properties:
- no learned inference cost,
- no information is intentionally discarded,
- only adds/subtracts/multiplies by 0.5,
- packed FP16-friendly,
- explicitly exposes low/high spatial phase information.

### Important caveat

Critically sampled Haar/polyphase features are phase-sensitive. The camera jitter phase must be accounted for. Do not assume spatial phase is stationary frame-to-frame.

The project should compare:
- raw pixel-unshuffle phase channels,
- fixed Haar mixing,
- learned 1x1 phase mixing.

Do not assume Haar always wins.

Semantic channels such as depth/motion/reactive mask should use a separate packing scheme rather than blindly applying the RGB Haar transform.

---

## 8.4 Low-frequency trunk / high-frequency branch

The default network should avoid a deep full-spatial feature stack.

Suggested starting topology (architecture search may alter it):

### LF structural trunk
- input: half-spatial polyphase features
- shallow projection: 16–32 channels
- deep trunk at H/2 x W/2 or lower
- 4–8 efficient residual/reparameterizable blocks
- packed FP16
- optional second downscale only if quality remains acceptable

### HF/detail branch
Do not run an equally expensive deep trunk.

Possible inputs:
- LH/HL/HH polyphase bands
- luma gradient
- depth edges
- normal/material edge hints where available
- reactive mask
- motion divergence

Possible implementation:
- analytic Sobel/Scharr + 1x1/3x3 shallow network
- very narrow learned branch
- tile-sparse residual head

Merge HF information late.

This follows the broad efficient-SR principle: the expensive deep network should not spend equal resources on smooth low-frequency structure and tiny high-frequency correction.

---

## 8.5 Structural re-parameterization

Training may use an over-parameterized linear block:

`1x1 -> 3x3 -> 1x1 -> activation`

where **there is no nonlinearity between the three foldable convolutions**.

At export, algebraically compose them into a single 3x3 convolution.

For:
- first layer `K1`
- spatial layer `K2`
- last layer `K3`

compute an equivalent kernel conceptually:

`K_eq[o,i,dy,dx] = sum_m sum_n K3[o,m] * K2[m,n,dy,dx] * K1[n,i]`

and correctly fold all biases.

Export two alternatives:
1. folded dense 3x3
2. bottleneck/depthwise form

Benchmark both on real Navi10. A theoretically lower FLOP count can lose due to memory/register behavior.

---

# 9. Proposed analytic reconstruction head (AKR)

This is the strongest new design.

## 9.1 Do not make the network output full RGB by default

At low spatial resolution, predict a compact control vector.

A useful first version:

```
s0, s1, s2       # anisotropic kernel / SPD matrix
alpha            # current-vs-history blend
history_radius   # history clamp strength / confidence
residual_gate    # how much explicit residual refinement is needed
detail_gain      # optional
```

Optionally add:
- 1 luma residual
- 2 lower-bandwidth chroma residuals

Do not immediately output 3 full-resolution arbitrary RGB channels from a heavy neural decoder.

---

## 9.2 Stable anisotropic-kernel parameterization

Instead of axes + angle, use a Cholesky parameterization to guarantee a positive-definite 2D filter matrix without trig:

```
l11 = exp2(clamp(s0, minS, maxS))
l21 = s1
l22 = exp2(clamp(s2, minS, maxS))

L = [ l11   0
      l21  l22 ]

Q = L * transpose(L)
```

For sample offset `d = (dx,dy)`:

```
e = dot(d, mul(Q, d))
w = exp(-0.5 * e)
```

Efficient HLSL form:

```
w = exp2(-0.7213475204 * e)
```

because `0.5 / ln(2) ~= 0.7213475204`.

Normalize the selected tap weights.

This:
- guarantees a valid ellipse,
- avoids angle sin/cos,
- gives the network only 3 unconstrained-ish numbers to learn.

Autotune `exp2` vs a bounded polynomial/table approximation, but quality must match.

---

## 9.3 Texture-unit-assisted filter

Do not naively issue 9 independent texel loads.

Generate variants:
- 4 bilinear taps
- 5 taps including center
- 8 bilinear taps
- 9 direct taps as a quality reference

Bilinear taps can combine neighboring texels in hardware. Use symmetric sample locations along the learned ellipse axes.

Select tap class **per tile**, not per pixel, to avoid severe lane divergence.

The network/uncertainty classifier assigns a tile to:
- `FAST_4`
- `NORMAL_5`
- `QUALITY_8`
- `RESIDUAL_REFINE`

Use GPU-generated indirect dispatch lists when profitable.

---

## 9.4 Temporal reconstruction

Let:
- `C_t` = analytically reconstructed current candidate
- `H_t` = motion-warped previous HR output
- `a_t` = predicted/current confidence blend

Conceptually:

`O_t = a_t * C_t + (1-a_t) * H_t`

But before blending:
- clamp or variance-clip history against a current neighborhood,
- reduce history on disocclusion,
- reduce history on reactive/transparency,
- force current on invalid/OOB history.

Use YCoCg or luma/chroma-local clipping only if measured better than RGB/HDR-safe clipping.

Avoid "infinite history" blur.

---

# 10. MCLD — Motion-Compensated Latent Delta reuse

This is the second major multiplier.

## 10.1 Cache only useful latent levels

Cache network trunk features after selected blocks/scales.

Do not cache every tensor blindly.

Candidate cached state:
- half-spatial LF trunk feature
- optional quarter-spatial bottleneck
- recurrent HF confidence/detail feature

Use FP16 or a compact measured-safe storage format.

---

## 10.2 Warp cached latents

Warp previous latent maps using renderer motion vectors mapped to the latent resolution.

For object boundaries:
- depth-informed motion dilation
- conservative validity mask

If warp confidence is low, mark tile active.

---

## 10.3 Tile-based sparsity, not arbitrary pixel sparsity

RDNA1 must remain well occupied.

Default feature-tile candidates:
- 8x8
- 16x16

Autotune.

For each tile build an `active` bit from:

```
active =
    depthMismatch > threshold
 OR motionDivergence > threshold
 OR colorResidual > threshold
 OR reactiveMax > threshold
 OR outOfBounds
 OR cameraCut
 OR forcedRefresh
```

Do not branch every thread through an irregular sparse pattern.

Build a compact active-tile list and use a GPU-driven indirect dispatch/persistent-worker scheme where that is measurably faster than dispatching all tiles.

---

## 10.4 Receptive-field mask propagation

If a convolution has radius `r`, changes in an input tile affect neighbors.

For each layer:

`A_next = DILATE(A_current, receptive_field_radius)`

For:
- skip/add: union the active masks from all dependencies
- downsample: conservatively map child mask
- upsample: conservatively expand parent mask

Halo reads can come from:
- current freshly computed active neighbors
- motion-warped cached stable neighbors

Do not create seams at active/stable boundaries.

---

## 10.5 Dense break-even fallback

Sparse execution is not always faster.

Measure the real RX 5700 XT and build a break-even table per kernel:

```
active_ratio -> sparse_ms
active_ratio -> dense_ms
```

If active fraction exceeds the measured break-even:
- execute dense for that layer/frame.

Do not hardcode "50%" as universal.

Persist tuning by:
- GPU PCI/device ID
- driver version
- shader hash
- output resolution
- model hash

---

## 10.6 Staleness control

Even if a tile looks stable, do not let stale errors live forever.

Use:
- confidence decay
- periodic distributed refresh
- refresh on large accumulated warp displacement
- refresh when uncertainty increases

A low-discrepancy/blue-noise refresh schedule may spread refresh cost, but validate temporal visibility.

`Quality` mode should refresh more conservatively than `Performance`.

---

# 11. New optional idea: Temporal Phase Interleaving (experimental)

This is a project synthesis, not a verified QSSR technique.

If the final head naturally produces multiple subpixel phase outputs, do not necessarily update every phase neural head every frame in stable regions.

Example:
- frame N updates phase set A
- frame N+1 updates phase set B
- missing phases are reconstructed from reprojected history
- current jitter phase receives priority

Only enable when:
- low motion,
- high history confidence,
- no reactive/disocclusion,
- active-tile ratio is low.

Always provide full-update fallback.

This can potentially reduce final-head cost, but it is experimental and must not be enabled by default until temporal quality is proven.

---

# 12. Jitter-phase specialization

For a finite jitter sequence (e.g. Halton 2,3 with N phases):

- index exact phase from integration data,
- precompute/generate phase-specialized first/last layer weights,
- compile or pack them at model export.

If jitter is arbitrary:
- use a small continuous conditioning path,
- or build/cache weights at initialization rather than every frame.

Do not spend a per-frame MLP just to regenerate weights for deterministic recurring jitter.

The training harness must test:
- phase transitions
- static camera with changing jitter
- moving camera
- jitter reset/camera cuts

---

# 13. Low-rank factorization: analyze, do not assume

For each FSR4/network 1x1 convolution, compute singular values.

A factorization:

`Cin -> r -> Cout`

is only arithmetically smaller than the original 1x1 if:

`r*(Cin+Cout) < Cin*Cout`

Example `Cin=C`, `Cout=2C`:

`r < 2C/3`

Use energy curves:
- 99.99%
- 99.9%
- 99%
- task-distilled fine-tuning

Prefer **structured low rank** over unstructured weight sparsity on Navi10.

Do not use low-rank approximations in the full FSR4 reference path unless an explicitly approximate mode is selected.

---

# 14. Winograd: optional dense-kernel optimization

For stride-1 3x3 FP16 convolutions, implement an optional pretransformed-weight Winograd candidate such as `F(2x2,3x3)`.

Theoretical multiplication reduction for the convolution itself can be significant, but transform overhead and small channel counts may erase the win.

Therefore:
- direct kernel remains required,
- Winograd is selected per pass only after actual Navi10 timing,
- numerical error must pass quality checks.

Do not apply to:
- stride-2
- transposed conv
- tiny cases where measured slower.

---

# 15. Hardware-in-the-loop architecture search

Do not pick one network width/depth purely from FLOPs.

Build a small latency-aware architecture search space:

Possible values:
- trunk width: 16, 20, 24, 28, 32
- blocks: 3–8
- latent recurrent width: 4–16
- HF branch width: 4–16
- half-res only vs half+quarter
- folded3x3 vs bottleneck form
- analytic tap class
- residual head on/off
- MCLD tile size

Training strategy:
- optional slimmable/supernet where practical,
- otherwise train a small set of candidate Pareto models.

Selection objective must include **measured RX 5700 XT milliseconds**, not only parameter/FLOP counts.

Example objective:

`score = quality_loss + lambda * max(0, measured_ms - target_ms)^2`

Final result should expose several Pareto points rather than pretending one model dominates all.

---

# 16. Training / distillation strategy

## 16.1 Teacher

The existing dense/reference FSR4 implementation becomes the teacher.

Where a lawful official/reference FSR4 output path is available, it may also be captured.

Do not require fast teacher inference; offline training capture can run slowly.

## 16.2 Ground truth

Prefer native/supersampled high-resolution render targets when available.

The network should learn from both:
- native HR truth
- FSR4 teacher behavior

This reduces the risk of blindly copying teacher errors while preserving FSR4-like reconstruction characteristics.

## 16.3 Optional public dataset

Qualcomm QRISP is highly relevant:
- temporal sequences
- color
- depth
- motion vectors
- jitter
- mip-biased lower-resolution inputs
- HR targets

But Qualcomm states the dataset is available for **research purposes** under its dataset license.

Do not auto-accept legal terms on the user's behalf.
Do not imply a model trained on QRISP can automatically be commercially redistributed.

Build the importer, and if license acceptance is required, stop only at that explicit user interaction.

## 16.4 Synthetic/procedural dataset generator

To avoid being blocked by a third-party dataset, also implement a small procedural temporal renderer/capture harness covering:

- subpixel lines
- fences/grids
- alpha-tested foliage-like cards
- particles
- high-frequency textures
- specular highlights
- transparent overlays
- disocclusion
- camera pans
- object motion
- rotation
- fast camera cuts
- exposure changes
- thin foreground objects
- scrolling UVs
- emissive effects

Output:
- LR color
- HR reference
- depth
- motion vectors
- jitter
- reactive-style mask
- transparency/composition mask
- exposure metadata

This dataset is not expected to replace real content; it is a deterministic correctness/stress dataset.

---

# 17. Losses

Keep losses configurable.

Recommended groups:

### Reconstruction
- Charbonnier / robust L1 against HR
- robust L1/Charbonnier against teacher output

### Edges/details
- gradient loss
- Laplacian/high-frequency loss
- optional Haar/subband loss

### Temporal
On valid reprojected pixels compare temporal deltas:

`(O_t - Warp(O_{t-1}))` vs `(GT_t - Warp(GT_{t-1}))`

Mask:
- disocclusion
- invalid motion
- reactive regions as appropriate

### Perceptual evaluation
Use FLIP/LPIPS offline for evaluation/model selection. Do not let perceptual loss cause hallucinated texture by default.

Avoid GAN training as the default gaming reconstruction path.

---

# 18. Quality hierarchy and runtime modes

Required modes:

## `full_fsr4_fp16`
- existing reference/full-quality path
- no architectural simplification
- teacher and fallback

## `naviqsr_dense`
- lightweight network
- no temporal sparse skipping
- deterministic performance
- easiest network correctness baseline

## `naviqsr_analytic`
- compact network predicts AKR controls
- analytic reconstruction + temporal blend

## `naviqsr_mcld`
- analytic/dense network plus motion-compensated latent reuse

## `auto`
- chooses dense vs MCLD based on measured break-even and confidence
- must not silently change configured quality tier

Optional:
- `naviqsr_tpi_experimental`

---

# 19. Aspirational performance targets — NOT promises

These are engineering targets informed by public evidence, not guaranteed results.

### Full dense FSR4 FP16
Continue current optimization work.

### NaviQSR 1440p output
A QSSR-like architecture on PS5 demonstrates that a streamlined FP16 model in this hardware class can be useful at 1440p.

Stretch target:
- isolated total upscaler around low-single-digit milliseconds
- ideally <= ~2.5 ms on RX 5700 XT

Do not treat Digital Foundry's 1.5–1.8 ms number as total QSSR time.

### NaviQSR 4K output
QSSR's observed ~4.4 ms frame-time hit on base PS5 demonstrates that this class of hardware can plausibly run a carefully designed FP16 neural reconstruction path at 4K.

Stretch target:
- ~3.5–5 ms total isolated NaviQSR runtime on RX 5700 XT

This is aggressive. Console-specific optimization and RDNA2 differences may prevent parity.

### Dense arithmetic target
A low-spatial network should aim for roughly **25–40% of the dense neural arithmetic** of the full teacher as an initial architecture target.

This is not a quality guarantee.

### Temporal reuse
ReFrame's public results make an additional typical ~1.2–1.6x latency reduction on temporally coherent cases a reasonable research target, with higher wins in favorable scenes and dense fallback in chaotic scenes.

Do not multiply all theoretical speedups into a single promised number.

---

# 20. The core engineering hypothesis

The project should test this hierarchy:

### Old hypothesis
"Take full FSR4 and make every convolution FP16."

Useful, but limited.

### Better hypothesis
"Preserve FSR4 quality behavior while reducing the amount of neural work."

### Best current project hypothesis

> A small low-spatial FP16 network can learn FSR4's reconstruction **decisions**; a cheap analytic filter and temporal history perform the expensive high-resolution reconstruction; renderer motion/depth make intermediate state reusable; uncertain tiles fall back to dense recomputation/full FSR4.

This is the architecture most likely to produce a discontinuous improvement in quality-per-millisecond on Navi10.
