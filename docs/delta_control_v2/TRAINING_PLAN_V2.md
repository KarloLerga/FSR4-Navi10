# Training and distillation plan V2

## Phase 0 - provider semantics

Before training:
- stateful multi-frame teacher works
- exact offline POST replay passes
- instrumentation remains output-identical
- full teacher timing exists

## Phase 1 - aligned FSR3

Before Delta4:
- exact same F4SEQ input
- deterministic FSR3 capture
- final FSR3 output
- selected temporal resource taps
- full FSR3 total GPU time

## Phase 2 - oracles

Run O0-O13 and create `PARAM4_ORACLE_RESULTS_V2.md`. Do not train a large model before this report exists.

## Phase 3 - baseline complexity ladder

Fit in this order:
1. preset/phase constant
2. AnalyticControl
3. affine/linear
4. LUT/codebook
5. coarse bilateral ParamGrid
6. tiny Shift1x1
7. deeper Shift1x1

After each:
- reconstruct final RGB
- evaluate temporal sequence
- benchmark GPU where implementable

Stop increasing complexity when a cheaper candidate already meets the quality target.

## Phase 4 - Delta4

Train from FSR3 semantics to:
- spatial control delta
- blend/state delta
- low-dimensional basis coefficients

Compare against standalone ParamGrid from exact FSR4 PRE semantics. This measures the price/benefit of reusing FSR3 instead of executing separate FSR4-like temporal preparation.

## Phase 5 - adaptive compute

Only after dense quality is known:
- train predicted-error router
- add exits
- add temporal control reuse
- add hard fallback

## Loss priorities

1. final teacher RGB reconstruction
2. native/supersampled HR fidelity where valid
3. temporal stability
4. normalized reconstruction-kernel/control loss
5. blend loss with extra hard-region weighting
6. recurrent rollout loss
7. edge/thin-feature loss

Raw saturated logits must never be the sole objective.

## Recurrent rollout

Train statefully:
- warmup teacher forcing
- mixed teacher/student recurrent
- full student recurrence

Use 8-frame minimum development unroll and 16/32 frames when feasible. Evaluate much longer sequences.

## Training backend

Do not assume ROCm-on-Windows support for RX 5700 XT training. Auto-select:
- CUDA if another compatible device exists
- DirectML if practical
- CPU fallback

Inference remains D3D12 on Navi10.

## Hard mining

Once a first student exists, oversample high teacher/student-error tiles while retaining enough easy content for proper confidence calibration.

## No fake completion

If full training cannot finish in the Codex run:
- complete the full pipeline
- run a deterministic small training proof
- export and dispatch that model
- provide exact real-training command/config
- document the compute/data blocker
- never ship random placeholder weights as a final result
