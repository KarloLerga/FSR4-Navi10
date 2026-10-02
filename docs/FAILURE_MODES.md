# Failure modes and required recovery behavior

This document anticipates ways a long autonomous implementation can go wrong. Do not stop at the first occurrence; recover, record the reason, and continue.

## Source-bearing FSR4 object cannot be fetched from AMD
1. Record the failed official fetch command/error.
2. Use only the configured documented fallback source mirror.
3. Verify expected FSR4 paths, commit history/provenance where available, and license text/hash before using it.
4. Never execute arbitrary scripts from the mirror as part of bootstrap.
5. Record actual source commit and hashes in `third_party/LOCK.json` and release notices.

## Current FSR API signed DLL cannot be rebuilt/imitated
Expected. Do not patch signature validation or Windows security. Build the project-owned unsigned `fsr4n10_ffxapi.dll` compatibility surface from public headers and document later integration limitations. This must not block the standalone harness/core.

## Reference INT8 shader refuses Navi10 through upstream capability gate
Do not modify the mathematical shader implementation. Bypass only provider/capability-selection glue inside the test harness so the source-visible reference shader can be dispatched directly if D3D12/DXC actually supports the required instructions. If compilation or execution is genuinely unsupported, preserve a CPU/scalar or alternate faithful reference for correctness and document that timing cannot be used as a hardware baseline.

## A shader uses an instruction that DXC cannot target for gfx1010
Generate an equivalent legal HLSL/DXIL implementation for the target backend. Do not emit invalid DXIL or patch validator/security mechanisms. Keep original semantics and validate against the reference.

## FP16 compatibility output diverges
Localize using per-pass/intermediate dumps. Compare the first mismatching pass, then check in this order: layout/stride; weight decoding; scale/zero point; rounding/clamp; accumulator precision; activation; residual ordering; coordinate/bounds. Do not hide the mismatch by weakening quality gates globally.

## FP16 path is slower than expected
Do not abandon FP16. Inspect DXIL/ISA for FP32 promotion, spills, poor wave occupancy, address arithmetic, uncoalesced loads, LDS bank conflicts, excessive barriers and transient traffic. Tune generated specialization. `hybrid_auto` may retain faster validated reference kernels where evidence supports it, but full FP16 remains a required output.

## Fusion makes a pass slower
Reject that fusion variant. The generator must support unfused and multiple fusion candidates. Do not assume fewer dispatches means faster execution.

## RGA cannot analyze installed-driver-specific DXIL
Keep RGA as static guidance and trust actual RX 5700 XT GPU timestamps for final selection. Save DXIL disassembly/compiler metadata. RGA failure must not block runtime correctness/performance work.

## RGP cannot be automated cleanly
Do not make completion depend on manual GUI captures. Use the built-in timestamp/telemetry harness as authoritative automation. RGP is optional deep diagnosis when accessible.

## Winget package ID or GitHub release asset changes
Repair `bootstrap.ps1` in the run. Prefer official vendor download endpoints/release APIs and verify signatures/hashes where available. Do not ask the user to hunt for downloads unless interactive licensing/authentication truly makes automation impossible.

## A dependency install needs reboot
Finish everything possible before reboot. Persist `PROGRESS.md`, `DECISIONS_LOG.md` and `.agent/EXEC_PLAN.md`, then clearly request only the unavoidable reboot. On resume, re-read those files and continue from the next unchecked milestone.

## GPU crash/device removal
Enable DRED, isolate the failing pass/candidate, save recent dispatch plan/config, restore a known-correct backend, fix resource/bounds/synchronization first, then resume tuning. Never repeatedly run a crashing candidate blindly.

## Autotuning produces unstable rankings
Increase warmup/sample count, randomize/alternate candidate order when appropriate, discard outliers using a documented robust rule, and require a minimum practical margin before changing a winner. Prefer the simpler/stabler candidate when times are statistically indistinguishable.

## 4K remains too expensive
Report the measured truth. Do not silently lower model quality, model topology or output resolution in the default FSR4 backend. A separately labeled experimental fast mode may be created only after the quality-preserving implementation is complete.
