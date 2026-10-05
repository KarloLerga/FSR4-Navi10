# Temporal control reuse V2

## Cache decisions, not deep features

Preferred cached state:
- spatial control representation
- temporal blend
- recurrent state or reduced latent
- confidence
- age
- optional coarse-grid predictor features

This is cheaper and easier to invalidate than caching the entire original FSR4 latent hierarchy.

## Reprojection

For each current control grid vertex/tile:
- reproject prior controls/state using trusted motion convention
- test depth consistency
- test current-vs-history semantic differences
- include FSR3 dilated MV/depth where Delta4 proves useful

## Reuse modes

Very stable:
`control_t = warp(control_t-1)`

Moderately stable:
`control_t = warp(control_t-1) + predicted_small_delta`

Unstable:
run current-frame Exit1/2/3.

## Immediate invalidation

Invalidate/promote on:
- camera cut/reset
- out-of-bounds reprojection
- depth mismatch/disocclusion
- reactive/T&C
- exposure discontinuity
- large shading change
- resolution/scale change
- maximum age
- excessive cumulative warp distance

## Oracle before runtime optimization

Do not enable temporal reuse merely because neighboring frames look similar. Measure teacher-control stability after correct reprojection over real sequences first.

## Refresh

Test max ages 2/4/8/16 and distributed refresh. Never allow a deterministic refresh schedule to create visible moving patterns.

## Recurrent compression

Teacher recurrent is already RGBA8 UNORM. Test:
- fewer latent dimensions
- PCA/codebook decode
- lower-resolution recurrent grid
- previous-state prediction

Do not spend time converting existing U8 to another U8 representation without a measurable bandwidth/quality reason.
