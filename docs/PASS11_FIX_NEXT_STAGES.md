# Technical continuation plan after Pass11 repair

This note is not a claim that the user already has a high-quality/fast FSR4 on
Navi10. It is the shortest defensible route to that result, based on the
source-grounded CPU/GPU oracle and stateful pipelines already implemented.

## A. O0 - production-grade deterministic teacher prerequisite

Only after the patched NativeAA/1080 I8 provider stabilizes:

- Repeat normal (global UAV barrier OFF) runs in separate processes with
  original intrinsic dot4 AND scalar dot4. Report all 8 frame RGB hashes,
  recurrent state, model semantic inputs, raw outputs and physical controls.
- Check `input_semantic_channels` first, then the model output, then POST,
  then history/recurrent textures, using paired captures from identical
  sequences; record the earliest different resource and pass.
- Do not use O0 as the proxy for human-visible image quality: continue with
  real game-engine input captures with correct jitter, depth, motion vector
  conventions, reactive/transparency masks and exposure.
- If instrumented vs reference parity still fails, inspect compilation and
  tap side effects, registered resource states, preExposure and memory
  lifetime. Keep the separate numerical CPU/GPU POST oracle; do not change
  tolerances or fake zeros to get a pass.
- Preserve FSR3.1.5 C/H accumulation taps as an independent reference; do
  not equate FSR3 image output to AMD FSR4 ground truth.

## B. Audit all 18 generated I8 variant sources

Run `tools/diagnostics/audit_i8_pass11_coverage.py` against the pinned FSR4
sources. The scanner flags source geometries where the 32/1 FNB transposed
convolution is run on nonmultiples of 64 in the non-WMMA path. It is
*conservative*: an unknown source layout yields an "unknown" record, not a
false claim of safety. Review each flagged preset/tier before enabling a new
mode. Test Native, Quality, Balanced, Performance, DRS and UltraPerformance
separately and respect their own input resolutions, temporal histories and
model parameters. Preserve the original AMD weights.

A more complete model compiler should generate a machine-readable descriptor
from each HLSL pass: its tensors with logical extents, storage strides, base
offset, backing byte size, threadgroup shape and source operator. Build a
read/write interval map per dispatch; prove that all launched threads write
inside the logical output extent and that independent waves/groups have
unique write destinations unless intentional atomics are used. Treat padding
and fused transposed convolutions specially. This turns the discovered
pass11 bug into a general future regression detector rather than a one-off
workaround.

## C. GPU-native pipeline

Only once O0 passes on original AMD source equations:

1. Migrate PRE and POST from CPU to D3D12 shaders while keeping C++ reference
   as oracle. Eliminate unnecessary GPU-to-CPU transfers and fence waits.
2. Keep the original temporal history/recurrent semantics (including reset,
   camera cut and preExposure) across all frames. Do not reset every frame
   just to obtain a good static screenshot.
3. Use GPU timestamp queries per logical phase. Separate CPU overhead,
   fence waits, memory traffic, scratch allocation and neural shader times.
4. Compare finite state variables and output image quality with upstream AMD
   I8 FSR4 before any alternative approximate backend is evaluated.
5. Measure occupancy, VGPR/SGPR pressure, LDS, cache traffic and wave
   scheduling on gfx1010 with Radeon GPU Profiler/RGA, not assumptions from
   RDNA4 peak throughput.

## D. FP16 / optimized Navi10 path without losing image quality

- Prototype a separate FP16 convolution implementation. Convert original
  I8 weights with the *correct per-tensor scales*; do not simply reinterpret
  packed INT8 as FP16. Keep FP32 accumulation/renormalization where required
  by error budgets. Native `dot4` correctness has already passed its oracle;
  FP16 is an alternate performance candidate, not automatically faster.
- Preserve unmodified AMD output as the teacher reference. Attribute PSNR,
  SSIM and temporal quality metrics against real scenes, including foliage,
  thin lines, motion disocclusion, transparency, small text and shimmering.
- Compare mixed precision at per-layer granularity. The fastest acceptable
  candidate may mix I8 dot4 and FP16 rather than convert every layer to FP16.
- Investigate scratch buffer liveness-based reuse AFTER the write-overlap
  analysis passes. Reclaim only ranges provably dead at each dispatch;
  accidental aliasing is exactly the bug class being fixed here.
- Consider kernel fusion, tensor layout repacking and group sizes only with
  synchronized, deterministic reference results; keep independent baseline
  builds and GPU timings. Quality regressions are gate failures, not tradeoff
  by default.

## E. FFX API compatibility and game integration

- Implement the actual FFX API provider adapter with correct resource formats,
  flags, shaders, state tracking, transitions, native game-engine render
  resolution, full 1080/2160/4320 tiers and motion-vector conventions.
- Do not claim generic injector compatibility with every DX12 game. Anti-cheat
  protected titles and unsupported temporal injection paths are excluded.
- Retain a safe opt-out and fallback if any GPU preflight or validation gate
  fails. Never emit wrong output that masquerades as good FSR4.
- Publish FPS and image quality comparisons only after fully controlled,
  representative GPU native tests and real input videos.

## Exact first action after this handoff

Apply this ZIP on a private branch; compile guarded `<32,1>`; assert the
compiled Pass11 artifact changed; run 72-run focused campaign; inspect
`pass11_guard_evaluation.json`, `alias_map.json` and all 8-frame hashes;
then run the existing unchanged O0 gate on the stable branch. No unrelated
optimizations should obscure the race fix before O0 is resolved.
