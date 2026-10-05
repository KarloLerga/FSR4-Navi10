# Research synthesis driving DeltaControl V2

## FSR4 itself is a kernel/control predictor

The pinned source proves the large model's learned action is compact: local spatial filter parameters, temporal blend and recurrent state. This makes policy distillation a more natural target than direct RGB distillation.

## Deep Bilateral Learning

Deep Bilateral Learning demonstrated the architecture pattern:
- learned processing at low resolution
- prediction of local transformation coefficients
- edge-aware slicing at high resolution
- cheap full-resolution application

FSR4 is unusually well aligned with this pattern because its model already predicts reconstruction controls.

## SCNet

SCNet demonstrates that parameter-free spatial shifts can supply spatial context to networks built from only 1x1 convolutions while remaining competitive with lightweight regular-convolution SR networks.

Use this as a clean-room architectural idea for a tiny control predictor, not as evidence that it will automatically reproduce FSR4.

## ClassSR and ENAF

ClassSR demonstrates that patches of different difficulty can use networks of different capacities and reports up to about 50% FLOP savings on its DIV8K experiments.

ENAF improves routing by estimating reconstruction quality rather than relying on a handcrafted edge score.

For this project the FSR4 teacher gives a stronger target: actual final-RGB error of each proposed exit.

## SMSR

Sparse Mask SR demonstrates learned spatial/channel sparsity in image SR and supports the concept that flat/easy regions often do not require full compute. Navi10 still needs real sparse-execution break-even measurement.

## CGSR

CGSR is especially relevant because it targets real-time computer graphics and uses rendering information, architecture search and rendering-aware temporal pruning. The paper reports substantial parameter/operation reductions and latency reductions while maintaining similar quality on its tested backbones.

Key project lesson: renderer metadata should be used not only as extra network channels, but to decide which computation is unnecessary.

## RDG

RDG decouples G-buffer guidance, selectively encodes structure, boosts high-frequency detail and uses depth/MV-constrained temporal refinement. This supports separate spatial and temporal control reasoning rather than treating every semantic channel equally.

## SRPO

SRPO handles flat rasterized areas with interpolation and trains an ultra-small 8,434-parameter network to predict offsets for sharp regions. It demonstrates that a learned system can predict sampling decisions rather than full RGB everywhere.

This directly motivates the DeltaControl offset/resampling oracle.

## Residual learning

Residual-learning SR established that predicting only the high-frequency residual can be easier than predicting the full output. Delta4 applies the same logic to upscalers: FSR3 supplies a strong temporal baseline and the learned component predicts only the FSR4-quality policy/residual.

## Temporal reuse

ReFrame and MotionDeltaCNN show temporal neural work can sometimes be reused/skipped, but also that sparse execution can lose on GPU occupancy/overhead. Therefore this project first attempts to cache/reproject the tiny control/state fields rather than the full original FSR4 latent hierarchy.

## 2026 temporal SR direction

Recent renderer-aware temporal SR continues to emphasize color/depth/MV/jitter, temporal subpixel evidence and dynamic reconstruction. These trends support teacher-driven control distillation, but the local RX 5700 XT measurements remain authoritative.
