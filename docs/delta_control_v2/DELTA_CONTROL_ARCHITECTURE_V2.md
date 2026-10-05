# DeltaControl V2 architecture

Build this only after the oracle suite, and simplify it automatically whenever a cheaper exit already satisfies quality.

## Core principle

The FSR4 neural body estimates a compact reconstruction policy. A student should predict that policy rather than duplicate the teacher hierarchy unless evidence proves it necessary.

## Student target

Preferred spatial representations:
- physical rho/sx/sy
- equivalent safe covariance/precision representation
- exact normalized 3x3 kernel or compact kernel code

Temporal outputs:
- blend
- recurrent U8-like state or lower-dimensional latent state

Raw p0..p3 remain canonical capture/provenance labels but raw-logit MSE is not the primary training objective.

## ParamGrid - primary dense candidate

```text
exact FSR4 PRE semantics or aligned FSR3 semantics
                  |
                  v
       low-resolution predictor
                  |
                  v
        control coefficient grid
                  |
          edge-aware slicing
                  |
                  v
         full-resolution controls
                  |
                  v
      project/source-equivalent POST
```

Candidate grid scales:
- 1/2
- 1/4
- 1/8 output linear resolution

The oracle chooses the coarsest acceptable scale.

## Bilateral/guided slicing

Plain bilinear interpolation can smear control discontinuities. Guidance candidates:
- current luma
- depth
- motion divergence
- disocclusion confidence
- reactive state

Do not build a high-resolution CNN just to generate guidance. Prefer analytic guidance or a tiny low-resolution guide.

## Shift1x1 predictor

If learned spatial features are required, use parameter-free spatial shifts plus 1x1 channel mixing before conventional 3x3 networks.

Bounded search space:

```yaml
grid_scale: [2,4,8]
width: [8,12,16,24,32]
blocks: [1,2,3,4,6]
shift_pattern: [cross4, eight_neighbor, dilated_eight_neighbor]
```

Fuse shift into source-coordinate loads when practical; do not materialize a shifted tensor pass.

Use true FP16 and inspect DXIL/RGA to ensure hot arithmetic is not silently promoted.

Do not copy SCNet implementation code directly; reimplement the published idea within this project's license requirements.

## Separate spatial and temporal heads

Use a shared cheap representation if useful, then branch:

Spatial head:
- filter/kernel controls
- edge residual confidence

Temporal head:
- blend
- recurrent/state update
- refresh confidence

They need not operate at identical spatial resolution.

## Delta formulations

When FSR3 is available, compare:

### Control delta
`control = baseline(FSR3 semantics) + predicted_delta`

### Basis delta
`output = FSR3_output + sum_i coeff_i * basis_i`

### Hybrid
Reuse FSR3 temporal/history confidence but execute project FSR4-style current filtering.

Do not assume one formulation is best before oracle results.

## Frequency split

Run low-frequency/control reasoning on coarse grids. Add a narrow high-frequency residual branch only near structural boundaries or teacher-error regions.

Do not spend equal full-resolution compute in flat and hard regions.

## Runtime storage

Avoid full-resolution eight-channel intermediate writes when slicing can feed reconstruction directly.

Prefer fusing:
`slice -> bounded control transform -> local reconstruction -> history blend`
when real Navi10 timing improves.

## Geometric speed opportunity

A 1/4-linear grid has only 1/16 as many prediction sites as output resolution. If temporal reuse refreshes only part of those sites, learned compute can drop further. These are geometric work reductions, not guaranteed latency claims; final GPU timing decides.
