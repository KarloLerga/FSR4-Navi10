# Guarded I8 numeric bisector execution (2026-10-08)

## Scope and provenance

Executed the supplied numeric-bisector package on the existing private branch
`fix/fsr4-pass11-nhws-bounds-race`, baseline commit
`afbd264958f94d7c5b146c51c5f7e2d02f8e5e0c`. The pinned FidelityFX source is
`01446e6a74888bf349652fcf2cbf5f642d30c2bf`. Hardware was an AMD Radeon RX
5700 XT; the harness reports driver version `0x00200000523503e8`.

All GPU comparisons used the same eight-frame procedural 1920x1080 sequence,
SHA-256
`a06357453979901689f4f9c8ff2400a1efe5b9547e017a7fa4cf5219ba157ec2`.
Inputs aligned across builds and each arithmetic mode was repeatable. These
are synthetic diagnostics, not rendered-game or quality measurements.

## Findings

Both guarded full-provider arithmetic modes completed their 28-case numeric
campaigns with no process failures. The first different declared model output
tensor is Pass 1, `slice_2` (`960 x 540 x 16`, 8,294,400 bytes). At that
boundary, 8,294,292 bytes differ (99.9987%). The first coordinate is
`(x=0, y=0, channel=0)`, with signed-I8 values 127 for intrinsic and 25 for
scalar. The maximum absolute difference is 152 signed-I8 units; the mean
absolute difference is 125.8808 units, or 3.4681 after the recorded tensor
scale. This is a large arithmetic-path disagreement, not a one-bit rounding
difference.

The isolated Pass 1 hybrid changed only the Pass 1 compiled model payload;
30 other shader selectors were unchanged. Both its intrinsic baseline and
hybrid completed all six requested cases without failures. Its first valid
output difference from intrinsic also occurs at Pass 1. This localizes the
observed change to the selected shader, but does not establish which path is
correct against AMD reference arithmetic.

The unchanged O0 checks produced different gate outcomes by arithmetic mode:

| Guarded provider | Required O0 steps | Existing teacher gate | CPU POST replay |
|---|---:|---:|---|
| Intrinsic DOT4 | Failed | Closed | Failed: non-finite model intermediates at 2,073,600/2,073,600 pixels on frames 0 and 4, and 2,073,544/2,073,600 on frame 7 |
| Scalar signed-I8 DOT4 | Passed | Passed | Passed: 0 non-finite pixels; max absolute error 0.0004883, 0.0009766, and 0.0009766 on frames 0, 4, and 7 |

Sequence capture, repeatability, GPU POST, reference instrumentation parity,
and the 256-vector native-DOT4 conformance check passed in both O0 variants.
The intrinsic teacher gate remains closed because its literal CPU POST replay
has invalid intermediate values despite matching the captured RGB output. The
scalar gate passing is evidence for this synthetic sequence only. The small
DOT4 conformance probe does not explain the full Pass 1 shader disagreement or
prove either compiled path matches AMD's reference execution.

Production defaults are unchanged:

- `FSR4N10_PASS11_BOUNDS_GUARD=OFF`
- `FSR4N10_FORCE_SCALAR_DOT4=OFF`
- `FSR4N10_SCALAR_DOT4_PASS_SET=""`

No arithmetic override was selected for normal builds. This work makes no
visual-quality, game-readiness, or performance claim. A representative
rendered sequence and an independent Pass 1 arithmetic oracle remain needed.

## Compiler path note

FFX_SC failed to resolve the build-local Pass 11 include when the shadow shader
was under an absolute path 163 characters long, while the same overlay
compiled at 144 characters. The original long default for the one-command
orchestrator would therefore fail before the GPU campaign. Its default output
was shortened to `build/i8diag`; an isolated Pass 11 compile from that path
passed. An explicit `-Output` should also keep the generated overlay path
short.

## Reproduction and records

The complete run was executed with:

```powershell
.\scripts\run-i8-complete-investigation.ps1 `
  -Repository C:\src\FSR4-Navi10 `
  -Sequence C:\src\FSR4-Navi10\build\release\delta-control-smoke.f4seq `
  -Output C:\src\FSR4-Navi10\build\i8run `
  -Repeats 2 -TraceFrame 0
```

After installation, the same script defaults to `build/i8diag`. Its summary
returns a failing status because the unchanged intrinsic O0 gate failed; the
failure is retained, while the guarded scalar O0 gate passed.

Compact machine-readable reports are in
`artifacts/results/i8-numeric-bisector/`. Full campaign JSON, logs, GPU dumps,
and captures remain under ignored `build/i8run/`.
