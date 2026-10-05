# Multi-exit control routing V2

## Principle

Different regions have different reconstruction difficulty. The router should predict whether a cheaper exit's final RGB is accurate enough, not merely whether the region has edges.

## Teacher-derived labels

For each 8x8/16x16/32x32 output tile, compute actual teacher-mimic error for every exit and label the first exit that passes configured quality thresholds.

The router target can be:
- predicted final-RGB error per exit
- exit probability distribution

## Inputs

Keep the router cheaper than the work it saves. Candidate features:
- structure-tensor statistics
- current/history difference
- depth edge
- motion divergence
- reactive state
- FSR3 shading change/accumulation
- temporal state age
- previous exit
- cheap control-residual magnitude

## Temporal hysteresis

Avoid exit flicker:
- promote easy -> hard immediately on invalidation
- demote hard -> easy conservatively
- use threshold hysteresis
- previous-exit prior
- optional short minimum hold if quality-safe

## Exit hierarchy

Exit0: AnalyticControl / linear / LUT

Exit1: coarse ParamGrid

Exit2: tiny Shift1x1

Exit3: larger Param4 predictor

Hard: NaviQSR

Reference/debug: full FSR4

## Sparse-GPU warning

The existing msad4 result already demonstrated that theoretical operation savings may not become latency savings.

Benchmark routing execution as:
- dense unified shader
- unified early-return
- compacted indirect tile lists

Choose measured Navi10 break-even per resolution/driver/shader hash.
