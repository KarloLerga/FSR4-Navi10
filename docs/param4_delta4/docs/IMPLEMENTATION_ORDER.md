# Implementation Order After e739364

This order is intentional. Do not jump to later experimental items before the gating evidence exists.

## P0 - GPU teacher

- upstream GPU PRE,
- exact model graph,
- upstream GPU POST,
- final RGB correctness,
- teacher control/state capture,
- deterministic temporal sequence format.

Exit gate:
- capture files contain valid real teacher p0..p3/recurrent/RGB.

## P1 - FSR3 aligned baseline

- run same sequence through FSR3.1,
- instrument current/history/internal semantic signals,
- produce frame-aligned FSR3 + FSR4 dataset.

Exit gate:
- deterministic paired capture.

## P2 - Oracles

Run:

- control-grid bandwidth,
- recurrent precision,
- filter codebook,
- FSR4/FSR3 component decomposition,
- Delta4 basis projection,
- simple-regression baselines.

Exit gate:
- `PARAM4_ORACLE_RESULTS.md` with hard numbers.

## P3 - Param4 dense baseline

Implement the smallest dense Param4 network that can match teacher controls usefully.

Start with exact FSR4 pre features.

Compare:

- linear,
- 1x1,
- Shift1x1.

Exit gate:
- quality-qualified full temporal output and full-resolution RX 5700 XT timing.

## P4 - ControlGrid

Only if oracle supports it:

- low-res control prediction,
- guided/bilateral upsample,
- sparse edge refinement.

## P5 - Delta4 FSR3 front-end

- integrate FSR3 internal state,
- basis/control prediction,
- fuse final decision with FSR3 accumulate/output where practical.

## P6 - Temporal control reuse

- reproject controls,
- update active tiles only,
- dense fallback.

## P7 - Adaptive exits

- easy: stock/cheap Delta4 basis,
- medium: control-grid/Param4 light,
- hard: dense Param4Shift,
- very hard: NaviQSR,
- full FSR4 only reference/debug/fallback if explicitly enabled.

## P8 - Full compatibility FP16 optimization

Continue in parallel when teacher path is stable.

## Explicit deprioritization

Do not spend the main run on:

- further msad4 micro-tuning,
- new synthetic-only THFA features,
- PHR activation,
- larger synthetic NaviQSR training,

until teacher/oracle results justify them.
