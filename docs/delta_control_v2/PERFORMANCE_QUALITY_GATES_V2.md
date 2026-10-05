# Performance and quality gates V2

## GPU timing only

FSR4:
- PRE
- MODEL
- PADDING
- POST
- RCAS
- TOTAL

FSR3:
- TOTAL
- selected internal stages only where useful

DeltaControl:
- semantics/preprocess
- predictor
- slicing
- reconstruction/post
- routing/compaction
- hard fallback
- TOTAL

Report median, p90, p95, p99, warmups, sample count, dimensions, driver/GPU and shader/model hashes.

## Mandatory output resolutions

- 1920x1080
- 2560x1440
- 3840x2160

Primary user targets:
- 4K Quality
- 4K Performance

## Quality metrics

Still:
- PSNR
- SSIM
- FLIP
- LPIPS offline if available
- gradient/edge error

Temporal:
- valid reprojection/warp error
- flicker
- ghosting/disocclusion subset
- static-jitter convergence
- reset recovery

Classes:
- flat
- edge
- thin geometry
- foliage/alpha-like
- disocclusion
- reactive
- specular/UV motion
- repeating texture

## Teacher mimic

Do not collapse evaluation into one magic threshold. Generate Pareto tables/plots and configurable strict profiles.

Never call a model perceptually equivalent based only on PSNR.

## Native truth

Where valid HR truth exists report:
- FSR3 -> truth
- FSR4 -> truth
- candidate -> truth

## Resource metrics

Record:
- transient VRAM
- persistent state VRAM
- control-grid bandwidth
- recurrent/state bandwidth
- shader/dispatch count
- selected shader VGPR/occupancy

## No theoretical speedup claims

A 1/4 grid being 1/16 as many sites is not automatically a 16x runtime speedup. Only measured end-to-end GPU time may be called a speedup.
