# Mandatory code-review checklist

Codex must run this checklist before calling the project complete. Treat every item as a release blocker unless explicitly documented otherwise.

## FP16 / HLSL correctness
- Production FP16 shaders compile with DXC `-enable-16bit-types` and use `float16_t`/vectors where native 16-bit arithmetic/storage is intended.
- Inspect DXIL and, when possible, RGA ISA to ensure hot FP16 expressions were not silently widened to FP32.
- Do not use `min16float` as a substitute for required binary16 semantics.
- Explicitly control casts around literals, accumulators, clamp/min/max, activation functions and residual additions; a single FP32 literal must not accidentally promote an entire hot expression.
- Define deliberate accumulator precision per operator. If FP16 accumulation causes unacceptable drift, use the narrowest higher-precision accumulator only where quality evidence requires it.
- Check overflow, underflow, saturation, denorm behavior, rounding and signed-zero behavior against the reference at quantization boundaries.
- No NaN/Inf may be introduced for finite reference inputs.

## D3D12 correctness
- Constant-buffer offsets obey 256-byte CBV alignment.
- Upload/copy/resource footprints use D3D12 alignment requirements and queried footprints rather than guessed pitch values.
- Descriptor handles are never used after heap recycling.
- Every resource has an explicit lifetime and state; debug tracking agrees with barriers.
- UAV visibility barriers are emitted only when required, but every real producer/consumer hazard is covered.
- Aliased placed resources receive correct aliasing barriers.
- Do not alias resources that persist across frames/history.
- Command allocators/lists are not reset before their GPU fence has completed.
- Readback buffers are not read until the corresponding queue fence completes.
- PSOs/root signatures are created once/cached; do not create them per frame.
- No GPU resource or descriptor allocation occurs in the hot per-dispatch path unless unavoidable and measured.
- Device removal enables DRED diagnostics in debug/development builds.
- Validation run with D3D12 debug layer must finish without corruption/error severity messages attributable to project code.

## Model and tensor correctness
- Tensor dimensions/strides/layouts originate from the fetched source/manifests; no guessed magic dimensions are allowed in handwritten runtime code.
- Weight extraction validates every byte range against source blob length.
- Every model pack has source hashes and conversion version metadata.
- FP16 conversion is deterministic and reproducible.
- Prepacking changes layout only, not tensor values.
- Quantization/dequantization semantics in compat mode match source formulas, including scale placement and rounding/clamp order.
- Residual/skip connections consume the exact logical tensor version expected by the source graph.
- Pass fusion must not change an operation's observable precision boundary unless using the separately validated high-precision backend.

## Temporal-upscaling correctness
- Preserve exact reset/history invalidation behavior.
- Preserve jitter units/sign and render-vs-display coordinate convention.
- Preserve motion-vector units/scales and low-resolution/full-resolution mode.
- Preserve depth convention (including inverted depth flags if present).
- Preserve pre-exposure/exposure sequencing.
- Optional reactive/transparency inputs must map exactly as the upstream contract expects.
- Resolution change/context resize must invalidate/reallocate the correct history resources.
- RCAS/auto-exposure/SPD are not accidentally executed twice or omitted.
- Validation includes multi-frame moving patterns, disocclusion, reset, camera pan, resolution changes and static convergence—not only one-frame images.

## Thread-group / wave correctness
- Never assume all D3D12 GPUs expose a fixed wave width. Navi10 candidates may request wave size only when supported by compiler/hardware path.
- Generated wave32 and any wave64 candidates must have separate shader hashes/metadata.
- Group shared memory usage must be statically bounded and stay within target limits.
- All group barriers are uniform; no barrier may sit in divergent control flow.
- Bounds handling must remain correct on non-multiple-of-group image dimensions.
- Avoid bank-conflict-prone LDS layouts where a simple padding/transposition fixes them.

## Performance-measurement correctness
- Use GPU timestamp queries, converted using queue timestamp frequency.
- Do not include CPU waits, command-list submission latency, readback copies or screenshot writing inside measured GPU intervals.
- Warm up PSOs/shaders/caches before recording steady-state data.
- Store raw samples, not only an average.
- Report median plus spread (mean, p10/p90 and standard deviation or equivalent).
- Benchmark backends using identical inputs, resolution, model tier, history state and command-queue conditions.
- Re-run suspicious winners; do not select variants from a single timing sample.
- Cache autotune decisions using at least GPU identity, driver version, shader/model pack hashes, preset/tier and output resolution bucket.
- Re-tune after any relevant hash/driver change.
- End-to-end frame/network time is the deciding performance metric. A microkernel win that makes the full path slower must be rejected.

## Hybrid-auto correctness
- `hybrid_auto` may select only candidates that already passed numerical/temporal gates.
- Full `fp16_compat` remains buildable and runnable even if hybrid chooses an INT8 candidate for some passes.
- Selection is per real pass/tier/preset; do not extrapolate blindly from one operator.
- Selected plan is serialized and human-readable with timings and hashes.
- Provide a command/config option to force reference, FP16 compat, high precision, or hybrid for debugging.

## Packaging/security/provenance
- Release does not include research repositories, third-party setup scripts, downloaded installers or files whose redistribution license is uncertain.
- Do not call the project DLL an AMD-signed DLL and do not bypass signature checks by patching Windows/driver security.
- Never modify GPU VBIOS, firmware, driver binaries, registry power limits or OS security settings.
- All third-party versions/commits/licenses used by the build are recorded.
- Build/release artifacts record project git revision, model/source hashes, DXC version and shader pack hash.
- A clean checkout plus documented fetch/bootstrap/build commands reproduces the release.

## Final source hygiene
- No TODO/FIXME/placeholder/mock remains in release-path code.
- No swallowed HRESULT/exception/failed command that can affect correctness.
- No unexplained magic constants where generated/source-derived metadata should be used.
- No generated file is hand-edited as the only source of a change.
- Debug-only validation paths are compiled out or disabled appropriately in Release without removing essential runtime checks.
