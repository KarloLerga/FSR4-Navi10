# Current repository review at 73193bd

## What is genuinely strong now

The GPU-native pinned FSR4 provider path is the most important milestone so far. Capture-only instrumentation now exposes the data needed to turn FSR4 into a real teacher:

PRE/input side:
- input color
- depth
- motion vectors
- seven semantic model-input channels
- exact current reconstruction source
- reprojected history

POST/model side:
- raw p0..p3
- derived physical controls
- recurrent state
- final teacher RGB

Instrumented and ordinary provider output are byte-identical in the current smoke. Repeated reset runs reproduce the taps. Keep this invariant.

The deterministic `.f4cap` format and provenance metadata are good engineering and should remain the audit format.

## What the current smoke does not prove

The current capture is synthetic, native 1920x1080 render/output, reset-driven, and lacks representative temporal history. It does not represent Quality/Balanced/Performance upscaling, 4K output, real temporal convergence, paired FSR3 behavior, or image-quality evidence.

A reset frame is particularly weak for learning temporal policy because previous state/history are not representative of steady-state operation.

## Storage implication

The current 10-array audit package is 211,507,200 bytes per 1920x1080 frame, about 201.7 MiB.

Approximate raw payload:
- 60 frames: 12.69 GB decimal
- 300 frames: 63.45 GB decimal
- 1000 frames: 211.5 GB decimal

Keep `.f4cap` unchanged for audit/reproduction. Add a separate derived sharded training format.

## Physical-control tap rule

The stable tanh/sigmoid equivalents are appropriate capture-only diagnostics, but raw p0..p3 remain canonical. Training should not silently make instrumentation-specific transformed values the only source of truth.

Offline tooling must regenerate physical controls and normalized 3x3 kernels from raw p values using formulas bound to the exact upstream source hash.

## Full timing is still missing

The ~7.7-7.9 ms summed I8 pass timing is valuable, but it is not full-effect timing. Stateful sequences must measure PRE, neural model, padding/reset work, POST, optional RCAS, and total GPU time separately.

## msad4 conclusion

The real RX 5700 XT microbenchmark measured `msad4` at near parity with scalar-u8. Therefore it is not a primary acceleration pillar. SARM may remain if it improves alignment quality, but no architecture should assume SAD hardware produces a major speedup without a new measured kernel win.

## Recurrent state conclusion

The upstream FSR4 provider allocates recurrent state as four-channel 8-bit UNORM. The useful questions are now:
- are all four recurrent dimensions needed?
- is recurrent state spatially low bandwidth?
- can it be projected into a smaller latent state?
- can it be reprojected/reused with sparse refresh?

## Biggest opportunity

The expensive neural graph ultimately chooses a compact local reconstruction policy. The next project question is not merely how to accelerate every original layer. It is how cheaply the teacher's final policy can be represented while preserving final RGB and temporal behavior.

## Instrumentation must not be the performance baseline

The capture implementation expands/repurposes debug resources and performs large readbacks. Byte-identical final RGB proves semantic non-interference in the current smoke, but the extra resource footprint can perturb residency, bandwidth, scheduling and total latency.

Therefore:
- use instrumented provider only for teacher data/correctness captures,
- use the ordinary non-instrumented provider for authoritative performance timing,
- optionally compare ordinary vs instrumented timing only to quantify capture overhead,
- never publish capture-build timing as production FSR4 cost.

## Preset/tier coverage is a new blocker

The current proven provider smoke uses native/1080 I8 selection. The repository source inventory already knows multiple model presets and resolution tiers, but teacher data for 4K Quality/Balanced/Performance must execute the correct upstream preset/tier permutation selected by the provider/API semantics.

Before generating the main dataset, validate provider permutation selection for:
- NativeAA
- Quality
- Balanced
- Performance
- relevant DRS/custom path if later needed

and output tiers corresponding to the upstream 1080/2160/4320 model families.

Record selected shader hashes in every teacher sequence/capture.
