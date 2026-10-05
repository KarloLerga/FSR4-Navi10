# Acceptance Criteria - Param4 / Delta4 Addendum

## Teacher

Required:

- complete GPU FSR4 PRE -> model -> POST path,
- temporal state persistence,
- reset/cut handling,
- deterministic repeated output,
- capture of p0..p3 and recurrent4,
- instrumented/non-instrumented RGB equivalence,
- full-resolution timing.

## FSR3 paired capture

Required:

- same input sequence/frame IDs,
- captured current candidate,
- reprojected history,
- semantic masks/state,
- final output.

## Oracles

Required reports:

- control-grid quality at 1/2,1/4,1/8,
- recurrent quantization,
- codebook sizes,
- component decomposition,
- scalar blend oracle,
- 2-basis and optional 3-basis oracle,
- hard-tile coverage.

Do not skip oracle analysis and immediately train a large Param4/Delta4 network.

## Dense Param4

Must prove:

- trained on teacher controls,
- recurrent rollout rather than teacher-forcing only,
- final FSR4 post RGB quality,
- temporal metrics,
- true GPU execution,
- true FP16 audit if advertised,
- 1080p/1440p/4K or supported target-resolution timing.

## Delta4

Must compare against:

- FSR3 baseline,
- Param4 exact-pre,
- full FSR4 teacher.

Report both:

- quality delta,
- GPU-time delta.

## Adaptive routing

Required:

- measured route fractions on temporal sequences,
- seam-free boundaries,
- dense fallback,
- break-even measurement,
- no threshold chosen only to improve a benchmark score.

## Stability

At minimum:

- 10,000+ frame/dispatch state stress,
- camera cuts,
- exposure changes,
- resolution changes,
- invalid/OOB motion,
- NaN/Inf checks.

## Documentation

Create/update:

```text
docs/PARAM4_ORACLE_RESULTS.md
docs/PARAM4_RESULTS.md
docs/DELTA4_RESULTS.md
docs/PARAM4_FINAL_ARCHITECTURE.md
docs/PARAM4_LIMITATIONS.md
RESULTS.md
PROGRESS.md
DECISIONS_LOG.md
.agent/EXEC_PLAN.md
```

No claim of "FSR4 quality" without direct teacher sequence metrics and representative images.
