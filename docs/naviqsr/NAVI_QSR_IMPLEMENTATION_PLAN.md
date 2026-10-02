# Codex Implementation Tasks — Required

This file is prescriptive. Integrate with the existing repository naming conventions where sensible, but preserve all functionality.

## A. Do not delete current work

Before changes:
- `git status`
- commit/stash a checkpoint if appropriate
- identify current buildable full-FSR4 path
- preserve it

Add the new architecture without breaking existing targets.

---

# B. New source tree

Create/adapt approximately:

```text
src/naviqsr/
  NaviQsrContext.h/.cpp
  NaviQsrSettings.h
  NaviQsrResources.h/.cpp
  NaviQsrHistory.h/.cpp
  NaviQsrModel.h/.cpp
  NaviQsrModelPack.h/.cpp
  NaviQsrDispatch.h/.cpp
  NaviQsrAutoTuner.h/.cpp
  NaviQsrMetrics.h/.cpp
  ActiveTileScheduler.h/.cpp
  JitterPhaseCache.h/.cpp
  DenseFallback.h/.cpp

shaders/naviqsr/
  preprocess.hlsl
  motion_dilate.hlsl
  warp_history.hlsl
  warp_latent.hlsl
  tile_signature.hlsl
  classify_tiles.hlsl
  compact_tiles.hlsl
  polyphase_pack.hlsl
  polyphase_haar.hlsl
  network_stem.hlsl
  network_block_rep3x3.hlsl
  network_block_bottleneck.hlsl
  network_block_partial.hlsl
  network_control_head.hlsl
  analytic_reconstruct_4tap.hlsl
  analytic_reconstruct_5tap.hlsl
  analytic_reconstruct_8tap.hlsl
  history_clip.hlsl
  temporal_blend.hlsl
  residual_refine.hlsl
  cache_commit.hlsl
  reset_history.hlsl

training/naviqsr/
  model.py
  blocks.py
  polyphase.py
  analytic_reconstruction.py
  temporal.py
  losses.py
  train.py
  validate.py
  export.py
  distill_teacher.py
  datasets/
    qrisp.py
    procedural.py
    captured_teacher.py

tools/naviqsr/
  analyze_fsr4_topology.py
  analyze_weight_rank.py
  fold_reparam.py
  generate_jitter_variants.py
  build_model_pack.py
  benchmark_kernel_variants.py
  benchmark_sparse_break_even.py
  capture_teacher_features.py
  compare_temporal_sequences.py
  architecture_search.py
```

Names may be changed to match repo style; capabilities may not be omitted.

---

# C. Runtime ordering

Implement explicit frame graph:

1. validate/reset temporal state
2. preprocess current input
3. motion/depth dilation
4. warp HR history
5. warp recurrent latent state
6. compute cheap tile signatures + confidence
7. decide dense vs sparse path
8. polyphase/feature packing
9. run network trunk
10. produce compact control maps
11. analytic current reconstruction
12. optional residual refine
13. clip/reject history
14. temporal blend
15. write output
16. commit latent/history for next frame
17. GPU timestamps

All GPU transitions/barriers must be explicit and minimal.

---

# D. Teacher/reference instrumentation

Extend existing full FSR4 FP16 path with optional debug export of selected intermediate tensors.

Requirements:
- disabled in release by default
- asynchronous readback where possible
- deterministic naming with frame/model/pass metadata
- no change to normal inference output
- capture final output + selected features

Used only for distillation/validation.

---

# E. Training architecture

Implement PyTorch reference model matching exported inference semantics as closely as practical.

Backend preference:
1. standard CUDA if user happens to have compatible GPU (not assumed)
2. PyTorch DirectML on Windows when available
3. CPU fallback

Do not assume ROCm Windows supports RX 5700 XT.

Keep backend selection automatic and logged.

---

# F. QRISP handling

Implement importer, but:
- never click/accept a dataset license automatically,
- if download requires legal acceptance/authentication, instruct user exactly once,
- record license note in docs.

Project must remain buildable without QRISP.

---

# G. Procedural dataset

Implement deterministic dataset generation if no external data is present.

The generator does not need to be a game engine. It needs controlled temporal stress patterns and correct ground truth.

At minimum generate:
- moving checker/grid
- rotating thin spokes
- fences
- alpha foliage cards
- particle sprites
- specular moving stripe/highlight
- subpixel wire
- scrolling texture
- foreground/background disocclusion
- camera pan
- camera rotation
- exposure jump
- scene cut

Generate exact motion/depth analytically when possible.

---

# H. Full accuracy checks

Every exported network model must be tested on temporal sequences, not only still frames.

Metrics:
- PSNR
- SSIM
- FLIP if available
- LPIPS offline if available
- temporal warp error
- disocclusion error
- edge-region error
- foliage/thin-line stress error
- history ghosting score

Also save A/B images and frame-difference heatmaps.

No model becomes default based only on PSNR.

---

# I. GPU timing rules

Use GPU timestamp queries around isolated passes.

Never:
- include disk I/O
- include CPU waiting
- include shader compilation
- include first-run PSO creation

Warm up.

Report:
- median
- p90/p95
- min
- number of frames
- output/input dimensions
- driver version
- GPU ID
- shader/model hash

---

# J. Hardware-in-loop search

`architecture_search.py` should coordinate:

1. candidate config generation
2. training/fine-tuning or selecting supernet submodel
3. export/fold
4. HLSL/model-pack generation
5. local benchmark executable
6. quality evaluation
7. Pareto report

The final default model must be selected from the measured Pareto frontier.

---

# K. Existing FP16 full-FSR4 optimizations to keep

Do not abandon:
- true `float16_t`/packed math
- pass specialization
- shader generation
- prepacked weights
- wave32/wave64 variants
- direct-vs-alternative kernel autotuning
- reduced conversions
- reduced barriers
- persistent resources
- scratch aliasing

Add optional:
- direct vs Winograd 3x3 candidate
- exact pixel-unshuffle/1x1 form for stride2 2x2 conv
- exact 1x1/pixel-shuffle form for compatible 2x2 transpose conv
- SVD rank report for 1x1 weights

These are secondary; do not let them delay NaviQSR implementation indefinitely.

---

# L. Acceptance gates

The addendum is not complete until:

### Build
- full existing project builds
- all NaviQSR shaders compile
- runtime can create all PSOs/resources
- standalone test harness runs on RX 5700 XT

### Correctness
- camera cut resets correctly
- resolution changes reset correctly
- OOB history never contaminates output
- sparse/dense boundary has no visible seam
- no NaNs/infs after 10,000+ dispatch stress
- deterministic output in deterministic test mode

### Modes
- `full_fsr4_fp16`
- `naviqsr_dense`
- `naviqsr_analytic`
- `naviqsr_mcld`
- `auto`

### Performance
- isolated per-pass timings
- dense-vs-sparse break-even table
- output-resolution scaling report
- memory report

### Quality
- static and temporal metrics
- teacher comparison
- native HR comparison where available
- screenshots/heatmaps
- failure cases documented

### Documentation
Create:
- `docs/NAVIQSR_RESULTS.md`
- `docs/NAVIQSR_ARCHITECTURE_FINAL.md`
- `docs/NAVIQSR_KNOWN_LIMITATIONS.md`
- `docs/NAVIQSR_REPRODUCE.md`

Do not claim success without measured results.

---

# M. What not to do

Do not:
- rename FSR3 and call it FSR4
- silently skip teacher layers in `full_fsr4_fp16`
- use random frame interpolation as a substitute
- sharpen aggressively to fake detail metrics
- train a GAN by default
- use unstructured sparsity without real GPU benefit
- assume fewer FLOPs means faster Navi10
- use the QSSR name as proof of a wavelet algorithm
- state Sony patents are QSSR implementation
- state this project's combined algorithm is globally novel
- disable quality validation to reach timing targets
- make sparse reuse mandatory when scene changes heavily
