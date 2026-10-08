# FSR4 I8 Native 1080p: Pass 11 boundary violation and suspected GPU write/write race

Date: 2026-10-08. Private baseline `KarloLerga/FSR4-Navi10@7671af74b2c0038848d8983f0748ecccf227183c`.

## Critical new source-level finding

The pinned AMD 4.0.2 generated 1080p I8 Native model invokes
`FNB_CT2D_ADD<32, 1>(...)` on **neural pass 11**. Its GPU entry point uses
`[numthreads(64, 1, 1)]`. Its input tensor dimensions are `(480,270,32)`;
its output dimensions `(960,540,16)` with a packed **16 bytes per output
pixel**, row stride **15,360 bytes** and scratch base **12,441,600 bytes**.

The non-WMMA provider explicitly schedules
`dispatchSizes[10] = { ceil(480/64), 270, 1 }` and `dispatchSizes[11] =
dispatchSizes[10]`. Thus 8 * 64 = **512 threads** are launched per row. X
threads **480 through 511** do not correspond to valid input pixels.

The `<32,1>` overload in `FNB_CT2D_ADD.hlsli` does not check these bounds
before reading the input. It also computes output pixel coordinates:

```
poBase2D = SV_DispatchThreadID.xy * 2 + localOffset[i]
localOffset = {(0,0), (1,0), (0,1), (1,1)}
```

and unconditionally writes `output.storage.Store4(output.OffsetOf(...),
storeDwords)`. Valid output X is 0..959. Invalid input X 480 therefore
writes output X 960, which is *one full output row stride beyond valid X*.
Because the tensor is linearized using 16 bytes/pixel and row stride
15,360, that address maps onto **output X=0 of the following row**. The
remaining invalid lanes cover output X=0..63 of the following row.

### Exact, source-based witness matching the observed report

The baseline diagnostic (zero seed, ordinary/instrumented) first diverges at
scratch byte offset **13,240,320**. This is exactly:

```
outputScratchBase + 52 * outputRowStride
12,441,600 + 52 * 15,360 = 13,240,320
```

Two GPU threads inside the same pass may write to this byte:

| Writer | Dispatch thread `(x,y)` | 2x local offset | Semantic output `(x,y)` | Physical scratch location |
|---|---|---|---|---|
| Intended row 52 | `(0,26)` | `(0,0)` | `(0,52)` | row 52, x=0 |
| Invalid prior row | `(480,25)` | `(0,1)` | `(960,51)` | row 52, x=0 |

The second writer is outside the **logical output tensor**, but inside
allocated scratch memory because the out-of-range X is linearized. This is a
specific within-dispatch **write/write collision**, not just reading random
uninitialized bytes. A barrier between dispatches cannot order threads
writing the same address inside a dispatch. The source/geometry/capture
correlation is now supported by the RX 5700 XT campaign: baseline variation
maps into the predicted alias region, and adding only logical bounds checks
restores scratch and full-run repeatability in both guarded arithmetic modes.
This is GPU evidence for the bounds-race hypothesis, while O0 parity and
quality remain separate gates.

The baseline observed per-row changed byte counts frequently cluster near
400-900, within the 64-pixel x 16-byte = 1,024-byte predicted overlap window.
`tools/diagnostics/analyze_pass11_alias.py` quantifies the overlap against
raw snapshots rather than merely asserting it. In the completed RX 5700 XT
campaign every baseline mismatch mapped wholly into this predicted alias zone.

## Minimal, semantically justified source fix

Only for the FNB specialized `<32,1>` operator (not the `<64,2>` or WMMA
variants), insert both checks:

```hlsl
// Immediately after the specialization _Static_asserts, before any load:
if (any(computeShaderParams.dispatchThreadID.xy >= input.logicalSize.xy))
    return;

// In its 2x2 output loop, before output/inputAdd reads and stores:
const uint2 poBase2D = computeShaderParams.dispatchThreadID.xy * 2 + pk;
if (any(poBase2D >= output.logicalSize.xy))
    continue;
```

The patch does *not* change network weights, quantization, scheduler group
counts, temporal history math, precision, model channels or POST behavior.
Existing valid threads produce their original arithmetic, apart from any
separate runtime problem revealed by removing the race.

`tools/teacher/fnb_bounds_overlay.py` copies the operator to a build-local
include-override directory. The pinned `third_party/fidelityfx-fsr4-source`
checkout is not modified. The shader compiler receives that directory FIRST
in its model include search path. FidelityFX_SC resolves the nested quoted
operator include to the upstream file despite `-I` order, so a build-local copy
of `passes_1080.hlsl` redirects only the Pass 11 include to a uniquely named
guarded operator file, preventing resolution to the same-named upstream file.
The compiler records and checks the actual Pass 11 operator dependency before
accepting a build. The CMake flag defaults to `OFF`.

## Why successful process exits are not a correctness check

The GPU may happily read/write a *valid resource address* that corresponds
to an invalid **tensor coordinate**, so the D3D12 driver need not fault.
The earlier 84/84 diagnostic run count showed robust process execution, but
not correct geometry or model parameter parity. The bounds campaign adds
scratch, frame-hash, and alias-map evidence described below.

## Campaign and pass/fail discrimination

Build three variants: `baseline_scalar` (scalar dot4, unguarded),
`guard_scalar` (same arithmetic, guarded), and `guard_intrinsic` (native dot4,
guarded). All use original literal POST math and no global UAV barrier.
Do not mix algorithm/precision changes with the geometry repair.

For each variant, run 2 scratch initializations (`zero`, `a5`), prefixes
10/11/12/full, 3 fresh processes: 24 runs/variant, 72 GPU runs total.
`tools/diagnostics/run_pass11_guard_campaign.py` retains every individual
stdout/stderr, per-frame hashes, input hashes and scratch snapshot; it checks
the emitted shader manifest reports the expected guard mode.

Before trusting run outcomes, compare generated reflected shader headers with
`verify_shader_diff.py`: the pass-11 shader artifact MUST differ between
guarded and unguarded scalar builds with *unchanged upstream hashes*.

`analyze_pass11_alias.py` maps mismatching scratch offsets to the predicted
first-64-pixel overlap area. `evaluate_pass11_guard.py` reports separate
status for local pass11 scratch stability and full stateful RGB repeatability.
A `candidate_fixed` flag is NOT an O0 pass; teacher eligibility remains false.

### Expected evidence

1. Baseline still reproduces pass11 scratch nondeterminism.
2. Guarded scalar mode has repeatable pass11 scratch and no differences
   between instrumented and ordinary for same input (preferred).
3. Guarded intrinsic mode also repeatable. If only scalar fixes it,
   investigate native arithmetic/precision with full pass11 evidence.
4. Full final RGB becomes repeatable across independent processes and
   different scratch seed values with same source input.
5. Existing O0 capture parity, independent CPU/GPU POST, source-equation finite
   values and representative sequence tests pass unchanged.

If (2) succeeds but (4)/(5) fail, **do not discard the bounds fix**; it can be
necessary but not sufficient. Inspect the first divergence in pass12, POST,
PRE history/recurrent and next-frame state using **validated guard build**.

## Additional integrity safeguards

- Repo HEAD must descend from `7671af7`, or installer refuses to apply.
- All textual source anchors are counted exactly and verified before any file
  changes. Unknown generated source fails closed.
- Native 1080 pass11 contract verifies entrypoint `[numthreads(64,1,1)]`,
  input/output shapes, scratch base and call to `FNB_CT2D_ADD<32,1>`.
- All shader and provider source hashes are retained in existing manifests.
- The patcher does not change a user-owned checkout of FidelityFX sources.
- Debug build trees and large captures remain ignored beneath `build/`.

## Measured RX 5700 XT result (2026-10-08)

The baseline scalar, guarded scalar, and guarded intrinsic Release builds all
compiled from pinned FidelityFX source commit
`01446e6a74888bf349652fcf2cbf5f642d30c2bf`. A dependency-file check proved
that guarded Pass 11 compiled the build-local operator, while the baseline
resolved the upstream operator. The Pass 11 content-addressed payload
changed. Selector-header hashes/order also changed for Pass 0, Pass 13, and
RCAS, but those three selectors retained the same payload digest sets; the
other 27 payload sets were unchanged. The separate ordinary Release
configuration retains `FSR4N10_PASS11_BOUNDS_GUARD=OFF`.

The campaign ran 24 cases per variant: zero/A5 scratch initialization,
pass-10/11/12/full prefixes, and three fresh processes. All 72 processes
completed on the RX 5700 XT with matching sequence/input provenance. Baseline
Pass 10 snapshots repeated, then Pass 11 was the first divergent prefix.
Across the eight baseline alias comparisons, every changed byte was in the
predicted output spill area; the first changed address in the ordinary A5
repeat comparison was byte `13,240,320`, the source-derived row-52 collision
above. The guarded scalar and intrinsic builds had no differing bytes in
their scratch comparisons, and each was repeatable across full runs, exact
between instrumented and ordinary output, and invariant to the zero/A5 seed.
The exact machine-readable cases, alias maps, selector diff, and evaluation
are retained in `artifacts/results/fsr4-pass11-guard/`.

Each guarded arithmetic mode is internally repeatable, but scalar and
intrinsic outputs are not bit-identical to each other: their prefix-10
scratch and all eight full-run RGB frame hashes differ. This campaign did not
establish cross-mode numeric equivalence or quality. The existing O0 teacher
gate remains false, the input is procedural synthetic content, and neither
this fix nor its performance measurements make FSR4 ready for game use.

The source matcher and compiler guard remain fail-closed against unexpected
upstream changes. The pinned AMD checkout is unmodified. Native FP16
optimizations, full game integration, quality versus AMD reference, and
O1-O13 remain separate engineering gates.
