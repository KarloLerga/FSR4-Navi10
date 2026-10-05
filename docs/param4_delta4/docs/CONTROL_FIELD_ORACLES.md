# Control-Field Oracles - Determine What Can Be Removed Before Training

These analyses are mandatory because they can expose orders-of-magnitude simplifications without guessing.

# Oracle A - Parameter smoothness / control-grid bandwidth

FSR4 spends a large CNN to produce only eight display-space control/state channels.

Test whether those fields actually need display-resolution prediction.

For each teacher sequence and each channel:

1. capture native full-resolution teacher control field,
2. downsample to control grids:
   - 1/2 resolution,
   - 1/4 resolution,
   - 1/8 resolution,
3. reconstruct to full resolution using:
   - bilinear,
   - bicubic,
   - depth/edge-aware guided upsample,
   - bilateral-grid slicing,
4. feed reconstructed controls through the exact teacher post filter,
5. measure final image/temporal error, not only parameter MSE.

Required metrics:

- final RGB PSNR/SSIM,
- FLIP if available,
- teacher-output absolute error percentiles,
- temporal warp error,
- flicker,
- edge/disocclusion subset errors.

If 1/4-resolution controls survive, prediction spatial density falls by 16x before model simplification.

## Edge refinement variant

Use coarse control grid for most areas, plus a sparse residual grid around:

- depth edges,
- reactive regions,
- high control-gradient regions,
- disocclusion.

This should be compared with a fully dense predictor.

# Oracle B - Recurrent-state precision

The recurrent state is four sigmoid-like channels.

Test storage formats:

- RGBA16F reference,
- RGBA8_UNORM,
- R10G10B10A2-like/custom 10-bit if practical,
- 8-bit per-channel with per-frame/per-model scale only if needed.

Re-run full temporal sequence using quantized recurrent state, not a one-frame static comparison.

If RGBA8 is acceptable it halves recurrent bandwidth/storage versus four FP16 channels.

# Oracle C - Physical parameter output

Compare raw-logit storage/prediction to direct physical outputs:

```text
rho   = tanh(p0)
sx    = 2 sigmoid(p1)
sy    = 2 sigmoid(p2)
blend = sigmoid(p3)
```

The Param4 path can predict the physical values directly.

This removes sigmoid/tanh transforms from post and gives explicit safe ranges.

Train/evaluate both because logits may be easier to regress in some regions.

# Oracle D - Filter-shape codebook

Convert each teacher `(rho,sx,sy)` into the normalized 3x3 kernel actually used at the current scale/jitter phase.

Cluster kernel shapes for K:

`K = 16, 32, 64, 128, 256, 512, 1024`

Measure final output after replacing the teacher kernel by its nearest codebook kernel while retaining exact teacher blend/history.

If a small K works:

- store precomputed filter kernels,
- Param4/router predicts a compact filter ID instead of three continuous values,
- runtime can eliminate most exponentials in the 3x3 filter.

Do not classify by Euclidean parameter distance only. Cluster/evaluate in normalized filter-weight space because different parameter vectors can have similar output kernels.

# Oracle E - Exponential LUT

If continuous control remains best, benchmark replacing `exp()` in Gaussian weights with a small 1D linearly interpolated LUT over the bounded energy range.

Compare:

- native exp/exp2,
- Texture1D LUT 64/128/256 samples,
- polynomial only if it is actually faster on Navi10.

Quality must be tested after normalized filter reconstruction.

# Oracle F - Teacher recurrent importance

Run teacher ablations:

1. exact recurrent state,
2. zero recurrent every frame,
3. previous recurrent held constant,
4. 8-bit recurrent,
5. spatially downsampled recurrent + guided upsample.

This reveals how much Param4 network capacity must be dedicated to the recurrent output.

# Oracle G - FSR4 component decomposition

Capture enough data to construct hybrid outputs:

- FSR4 current filter + FSR4 history + FSR4 blend (exact teacher),
- FSR4 filter + FSR3 history + FSR4 blend,
- FSR3 current + FSR4 history + FSR4 blend,
- FSR3 current/history + FSR4 blend only,
- FSR3 output baseline.

This identifies whether the visible quality difference is dominated by:

- spatial kernel selection,
- history quality/alignment,
- blend decision,
- recurrent state.

Do this before designing a large Delta4 model.
