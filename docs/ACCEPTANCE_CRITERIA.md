# Definition of done

Codex must not declare the project complete until the applicable criteria below are met.

## A. Setup/provenance
- [ ] Bootstrap script works on the user's Windows workspace or clearly records the single unavoidable manual/elevation blocker.
- [ ] Upstream AMD FSR4 source-bearing commit/tree is fetched or the documented license-preserving fallback is pinned.
- [ ] `third_party/LOCK.json` contains commit hashes and relevant asset SHA-256 values.
- [ ] DXC version, GPU, driver, Windows and compiler information are recorded.

## B. Build
- [ ] Clean Release configure/build succeeds from command line.
- [ ] Debug/RelWithDebInfo build succeeds at least once.
- [ ] No release-path TODO/FIXME/stub remains.
- [ ] Generated shader/model artifacts can be reproduced from source commands.

## C. Reference implementation
- [ ] Complete FSR4 4.0.2 reference pipeline executes in standalone harness.
- [ ] All actual upstream model passes are represented.
- [ ] Multi-frame history/reset behavior works.
- [ ] Reference output is repeatable.

## D. FP16 model toolchain
- [ ] Canonical manifest generated for each supported preset/tier targeted in the source.
- [ ] INT8/FP8-to-FP16 conversion implemented from exact upstream formulas.
- [ ] Generated FP16 model pack has versioning, bounds checks and hashes.
- [ ] Conversion unit tests pass.

## E. Complete FP16 execution
- [ ] `fp16_compat` implements every FSR4 model pass; no INT8 dot path required to execute it.
- [ ] `fp16_high_precision` implements every model pass or cleanly aliases a compatible pass where there is no semantic distinction.
- [ ] True 16-bit HLSL is enabled and production ISA inspection confirms expected 16-bit operations in representative hot kernels.
- [ ] No NaNs/Infs/device removal across stress run.

## F. Quality
- [ ] `fp16_compat` meets `NUMERICS_AND_QUALITY.md` gates across deterministic sequences.
- [ ] Temporal reset/disocclusion/static tests pass.
- [ ] Any high-precision differences are documented with metrics and visual diffs.
- [ ] Default backend never selects a variant that fails quality gate.

## G. Navi10 optimization
- [ ] Pass-specialized generated HLSL exists for production backend.
- [ ] Wave/threadgroup/layout/fusion candidate system is bounded and automated.
- [ ] RGA or equivalent ISA/resource reports are captured for important selected kernels when tooling supports it.
- [ ] No unexplained scratch spills remain in major hot kernels, or they are documented as unavoidable with evidence.
- [ ] Resource lifetime map and barrier strategy are documented.

## H. Performance
- [ ] GPU timestamps report per-pass and total effect times.
- [ ] Warmup and repeated samples are used.
- [ ] `hybrid_auto` is selected from validated candidates based on local RX 5700 XT measurements.
- [ ] Final `RESULTS.md` compares reference_i8, fp16_compat, fp16_high_precision and hybrid_auto at available 1080p/1440p/4K tiers/presets.
- [ ] No unmeasured performance claim is presented as fact.

There is no requirement to hit a fabricated multiplier. If a path is slower, it is reported honestly and not selected.

## I. FSR API adapter
- [ ] `fsr4n10_ffxapi.dll` exports required public API functions.
- [ ] Smoketest dynamically loads it, queries it, creates context, dispatches and destroys context.
- [ ] Unsupported descriptors return deterministic errors, not crashes.
- [ ] DLL is clearly marked unsigned/custom; AMD signature is never forged.

## J. Packaging
- [ ] `release/` contains runnable harness, adapter/core binaries, model/shader packs, config, docs and notices.
- [ ] `scripts/package.ps1` recreates release from clean build.
- [ ] `README.md` explains how to run harness and what the result means.
- [ ] `RESULTS.md` contains measured final data.
- [ ] `THIRD_PARTY_NOTICES.md` is complete.

## K. Stability
- [ ] At least 10,000 standalone dispatches or equivalent sustained stress sequence completes without GPU device removal, memory growth or output corruption.
- [ ] Context create/destroy loop test passes repeatedly.
- [ ] Reset mid-sequence passes.
- [ ] Debug layer reports no unresolved D3D12 correctness errors in validation run.

## L. Final honesty
If a required feature is blocked solely by external signing/proprietary restrictions, `RESULTS.md` states exactly what is blocked and the standalone/custom API path is still finished. Do not label a scaffold or partial network “complete.”
