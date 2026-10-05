# Automatic architecture selection policy V2

Codex must not choose an architecture subjectively before measurement.

## 1. Exactness gate

If exact offline POST replay fails, fix capture/replay semantics before training.

## 2. Spatial bandwidth

Choose the coarsest control grid whose final reconstructed RGB remains on the quality Pareto frontier. Never choose scale from control MSE alone.

## 3. Cheapest dense predictor

Evaluate in order:
1. constant/phase
2. analytic
3. linear
4. LUT/codebook
5. tiny Shift1x1
6. deeper Shift1x1

Pick the least expensive candidate satisfying validation quality.

## 4. FSR3 residual path

If Delta4 can reach comparable quality, compare TOTAL runtime:
- standalone ParamGrid/Param4
- FSR3.1.5 + Delta4

Published FSR3 cost is not zero; include it.

## 5. Adaptive compute

Enable multi-exit only if O11/O13 shows a meaningful easy-tile population and real GPU timing improves.

If nearly all tiles require the deepest exit, remove routing overhead from production.

## 6. Temporal reuse

Enable only if O12 demonstrates stable reuse and measured runtime improvement with quality-safe invalidation.

## 7. Hard fallback

Choose deeper Param4 versus NaviQSR based on hard-tile quality and actual sparse/dense break-even.

## 8. Two quality axes

Always report:

Teacher mimic:
`candidate vs full FSR4`

Actual fidelity:
`candidate and FSR4 vs native/supersampled HR where valid`

A candidate may differ from FSR4 if it is demonstrably closer to valid ground truth and remains temporally stable.

## 9. Default mode

Do not make an experimental path default until:
- temporal validation passes
- reset/cut behavior is correct
- runtime advantage is material
- final quality/performance report exists
