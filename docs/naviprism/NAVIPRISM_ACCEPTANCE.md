# NaviPRISM Runtime and Acceptance

## Frame graph

0 reset validation
1 preprocess LR and matching data
2 spatial descriptor
3 SARM residual motion
4 refined history/optional PHR reprojection
5 history validity/resurrection
6 THFA lookup
7 cheap current reconstruction
8 fast-path confidence
9 compact HARD tile list
10 SADNet or NaviQSR for HARD tiles
11 merge
12 history clip/reject
13 temporal blend
14 HR output
15 history/PHR update
16 GPU timestamps

## Routing

EASY -> THFA fast
MEDIUM -> THFA quality
HARD -> SADNet
VERY_HARD -> NaviQSR
REFERENCE/DEBUG -> full FSR4 FP16

Use tile-coherent routing. Track easy/medium/hard fractions.

## Quality acceptance

Evaluate temporal sequences, not only still frames:
- PSNR/SSIM
- FLIP where available
- LPIPS offline where available
- temporal warp error
- flicker
- ghosting
- edge/thin-line error
- disocclusion
- specular/animated-UV cases.

Save A/B frames, difference heatmaps and temporal strips.

## Performance acceptance

Use GPU timestamp queries after warmup. Never include shader compilation, PSO creation, disk IO or CPU waiting.

Report preprocess, descriptor, SARM, THFA, hard classification, SADNet, NaviQSR fallback, temporal blend, PHR/history update and total.

Report median, p90/p95, driver, GPU ID, input/output resolution, shader/model hash.

## Definition of success

A strong success is a measured Pareto point where:
1. image/temporal quality is materially closer to full FSR4 than the analytical baseline,
2. total GPU time is materially below full FSR4 FP16,
3. most normal-scene pixels/tiles use the no-CNN fast path,
4. hard fallback fixes failure regions without seams.

## Honest failure documentation

Record if msad4 does not lower efficiently, SARM does not help, atlas flickers, hard fraction stays high, SADNet loses to FP16 NaviQSR or PHR is not useful. Do not tune thresholds dishonestly just to improve graphs.

## Current implementation checkpoint

- Implemented and GPU/reference checked: `msad4` microbench, SARM 4x4 residual search, 4/5/8/9-tap THFA filter, and conservative tile classification/compaction. These validators currently use deterministic synthetic buffers.
- Implemented as offline/reference tooling: THFA factorized ridge fitting and FP16 atlas packing, tile descriptor math, and PHR reprojection/reset model.
- Not connected to a real game-frame graph: scene preprocessing/exposure, motion and validity resource ingestion, FSR4 teacher capture, SADNet or NaviQSR sparse fallback dispatch, temporal blending, and PHR GPU persistence.
- No NaviPRISM image-quality or full-resolution/end-to-end performance result exists. The microbench dispatch timings in `NAVIPRISM_RESULTS.md` cannot establish quality or a production speedup.
