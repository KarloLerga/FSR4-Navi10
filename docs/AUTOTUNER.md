# Automated tuning design

The user does not want a manual series of one-off experiments. The project therefore contains a bounded automated tuner that is run by Codex during the same implementation session and can be rerun later.

## Candidate generation
Start from a small evidence-driven candidate set per pass:
- fp16 compat canonical layout, wave32
- fp16 compat prepacked layout, wave32
- fp16 compat selected wave64 variant
- fp16 compat fused/split variant where operator graph supports it
- fp16 high-precision equivalent when it passes quality
- reference INT8 candidate

Only add a new dimension when ISA/resource/timing data suggests a bottleneck. Avoid combinatorial explosion.

## Two-stage selection
### Stage 1: pass-local
- validate pass output against required reference input/output
- warm up
- execute repeated dispatches using identical resources
- collect GPU timestamps
- store median, p10/p90, standard deviation
- reject invalid/unstable candidate

### Stage 2: full-pipeline
Construct candidate full backends from the best few pass-local choices. Benchmark full multi-frame FSR4. The globally fastest quality-valid combination wins.

## Cache key
Tuning data key includes:
- adapter LUID/device ID
- driver version
- model source hash
- shader pack hash/DXC version
- output tier/preset

Stale cache is ignored, never blindly reused.

## Quality first
No candidate enters timing selection unless its output meets the pass/final quality gate. High-precision candidates that intentionally differ use their own approved gate.
