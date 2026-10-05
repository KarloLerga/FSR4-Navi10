# Repository Audit - commit e739364

This document records the observed public repository state used to design this addendum.

## Verified repository state

Current `main` at time of research:

`e739364564fd9d68242b0fdd79e51d8b81b5fcd3`

Commit subject:

`feat: validate optional NaviPRISM phase history`

## Full FSR4 source work already present

The repository already has:

- deterministic FSR4 source/model inventory,
- all 18 I8 preset/resolution model combinations,
- compiled I8 entries,
- model parameter extraction/container tooling,
- RX 5700 XT FP16 arithmetic capability probe,
- I8 source graph GPU smoke,
- preliminary per-pass GPU timing,
- experimental two-frame image smoke.

However the current image smoke still uses CPU-side source-derived preprocessing/postprocessing around the GPU I8 model graph. It is not yet the actual complete upstream GPU FSR4 effect.

## Measured I8 neural graph timing

Native/1080p synthetic zero-input medians in `RESULTS.md`:

| Pass | median us |
|---:|---:|
| 0 | 116.820 |
| 1 | 591.120 |
| 2 | 626.280 |
| 3 | 113.120 |
| 4 | 498.900 |
| 5 | 503.900 |
| 6 | 172.400 |
| 7 | 475.960 |
| 8 | 449.580 |
| 9 | 774.660 |
| 10 | 456.180 |
| 11 | 1211.480 |
| 12 | 581.780 |
| 13 | 682.940 |

Sum of medians is about 7.26 ms. This is not total FSR4 effect time. It excludes real GPU pre/post stages and is measured on synthetic model input.

Highest-priority compatibility passes by measured time:

1. pass 11
2. pass 9
3. pass 13
4. pass 2
5. pass 1
6. pass 12

## NaviQSR current state

Actual repository state:

- deterministic procedural data pipeline exists,
- CPU training/export exists,
- 9-layer D3D12 network graph exists,
- temporal analytic reconstruction exists,
- small GPU/reference tests pass,
- current trained synthetic checkpoint improves PSNR by only ~0.084 dB over bilinear on its holdout,
- network parameters are FP16-stored but current convolution activations/MAC path is FP32,
- no FSR4 teacher distillation exists.

Conclusion: do not tune this synthetic Param4 path further before real teacher capture exists.

## NaviPRISM current state

Verified from `NAVIPRISM_RESULTS.md`:

- `msad4` compiles to Navi10 `v_mqsad_u32_u8`,
- `msad4` median 287.665 us,
- scalar-u8 median 288.654 us,
- FP16-difference median 337.109 us,
- therefore current msad4 workload shows effectively no useful advantage over scalar-u8,
- SARM synthetic translation correctness passes,
- THFA synthetic atlas shader/reference passes,
- router classification/compaction passes,
- phase history standalone reprojection/reset smoke passes,
- none of these paths currently has FSR4 teacher-fitted quality evidence.

Decision for next run:

- preserve NaviPRISM,
- use SARM only if it improves temporal quality,
- do not treat masked SAD as the main performance breakthrough,
- do not enable PHR until A/B quality supports it,
- pause large THFA/SADNet expansion until real teacher controls exist.

## Primary missing gate

The project still lacks the one artifact every Param4/Delta4 architecture needs:

> a deterministic, GPU-native, quality-checked FSR4 teacher sequence with captured final RGB, exact network control outputs, recurrent outputs and temporal inputs.

That is now P0.
