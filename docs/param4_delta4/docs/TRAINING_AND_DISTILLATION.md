# Training and Distillation Plan

## Phase 0 - Do not train yet

Complete the GPU teacher and aligned FSR3 capture first.

Current synthetic NaviQSR training is useful as infrastructure validation, not as a quality target.

## Phase 1 - Analyze teacher controls

Before training a Param4/Delta4 network:

- distribution of raw p0..p3,
- distribution of physical rho/sx/sy/blend,
- spatial total variation,
- temporal difference after reprojection,
- recurrent statistics,
- PCA/rank across control+state channels,
- control-grid oracle,
- codebook oracle,
- recurrent quantization oracle,
- FSR3/teacher basis oracle.

Produce `docs/PARAM4_ORACLE_RESULTS.md`.

## Phase 2 - Tiny baseline predictors

Fit increasingly capable predictors:

1. constant by preset/phase,
2. linear regression from exact FSR4 pre features,
3. small MLP/1x1 predictor,
4. THFA/LUT predictor,
5. Shift1x1 network.

Every step produces final post-filter RGB metrics.

This tells us how much complexity is actually required.

## Phase 3 - Param4ExactPre

Train the direct Param4 network from exact FSR4 pre features to:

- physical controls,
- recurrent state.

Teacher targets are captured from real FSR4 GPU path.

Unroll temporal sequences.

## Phase 4 - Delta4

Train predictor from FSR3 internal state to teacher controls/basis coefficients.

Compare:

- FSR3 signals only,
- FSR3 + previous Delta4 recurrent,
- FSR3 + small current image neighborhood.

Avoid duplicating expensive feature extraction.

## Phase 5 - Adaptive compute

Once dense quality is known:

- train difficulty/error predictor,
- add early exits,
- add control-field reuse,
- add hard fallback to NaviQSR.

Use teacher error as routing target rather than arbitrary gradient thresholds.

## Loss details

### Control kernel loss

Convert predicted and teacher physical controls into the normalized 3x3 filter weights used by post.

Loss on actual kernel weights is more meaningful than raw-logit MSE.

### Blend loss

Compare physical blend values, with extra weight near disocclusion/fast motion where blend mistakes are visually costly.

### Recurrent loss

Direct state loss plus rollout loss after multiple Param4 frames.

### RGB reconstruction

Run differentiable equivalent of the exact FSR4 post filter during training.

Use:

- Charbonnier/L1,
- edge/gradient loss,
- optional native-HR target,
- temporal warp loss,
- flicker penalty.

### Hard-region weighting

Mine:

- thin geometry,
- foliage,
- reactive/transparency,
- disocclusion,
- specular/shading change,
- high FSR3-vs-FSR4 difference.

Do not let vast flat regions dominate the loss.

## Teacher vs native truth

FSR4 is a behavior teacher, not absolute ground truth.

Where native/supersampled HR is valid, use it alongside teacher supervision so the Param4/Delta4 network is not forced to reproduce teacher artifacts.
