# FSR4 scratch and first-divergence diagnostics

This is a debug-only experiment for investigating the current scalar O0
repeatability failure. It compares deterministic scratch fills, optional
global UAV barriers, and the earliest FSR4 model-pass prefix where captured
scratch bytes differ. It does not change model weights or default dispatch
behavior, and it does not establish image quality or a production fix.

The pinned AMD checkout stays unchanged. Prefix and barrier variants use
generated CMake build overlays. Both controls default to off. A prefix run
still executes POST after truncating the model, so its RGB is invalid and the
harness refuses to write `.f4cap` teacher captures in prefix mode.

## Run

Start with the bounded campaign and include the barrier comparison:

```powershell
.\scripts\run-fsr4-race-bisector.ps1 `
  -Repository $PWD.Path `
  -Sequence build\release\delta-control-smoke.f4seq `
  -MaxPass 3 `
  -IncludeBarrierBuild
```

The script uses separate ignored build trees under
`build\fsr4n10-race-bisector`. The campaign starts fresh harness processes for
`off`, `zero`, and `a5` scratch modes, captures the requested frame's complete
scratch buffer for both provider contexts, and repeats each case twice. The
bounded run stores roughly a few gigabytes of raw scratch data. Use
`-MaxPass 12` after reviewing the initial run and available disk space.

Results are written to `results-standard\campaign.json` and
`results-standard\analysis.json`, with equivalent files for
`results-global-barrier`. With `-IncludeBarrierBuild`,
`variant-comparison.json` compares matching seed/pass/repeat records and checks
that the input sequence hashes align. Per-run stdout, stderr, sequence reports,
and scratch buffers remain under the ignored build directory. Failed runs leave
partial reports and stop the script for inspection.

## Controls

- `FSR4N10_SCRATCH_INIT=off|zero|a5|5a|ones` fills scratch before each provider
  dispatch. `off` is the unseeded control.
- `FSR4N10_LAST_MODEL_PASS=0..12` is available only in builds configured with
  `FSR4N10_ENABLE_PASS_PREFIX_DIAGNOSTIC=ON`. Prefix zero means PRE only; 1–12
  mean the selected final neural pass. POST still executes.
- `FSR4N10_TRACE_SCRATCH_DIR=<directory>` saves instrumented and ordinary
  scratch snapshots after the selected prefix or full dispatch.
- `FSR4N10_TRACE_FRAME=0` selects the frame to capture.
- `FSR4N10_FORCE_GLOBAL_UAV_BARRIER=ON` builds the diagnostic backend overlay
  that inserts a global UAV barrier after each compute dispatch.

## Read results carefully

`first_repeat_divergent_prefix` and
`first_instrumented_vs_ordinary_divergent_prefix` are separate signals. The
scratch snapshot is taken after POST, so a changed prefix identifies the
earliest differing *observed prefix*, not necessarily the exact store that
first diverged inside a neural pass. Compare seeded runs when reasoning about
uninitialized bytes; untouched bytes from different fill patterns are
expected to differ.

If zero and `a5` change ordinary full-model RGB with identical inputs, inspect
for read-before-write behavior. If seeded scratch still diverges across
repeats, uninitialized scratch alone cannot explain the repeatability failure.
If a global barrier changes the result, investigate ordering at the affected
operator before considering any production change. A matching scratch hash
does not prove FSR4 parity: full-model repeatability, instrumented/reference
numeric agreement, and real-scene quality remain separate gates. O1–O13 stay
locked unless the existing acceptance criteria pass.

Source review and prior diagnostic evidence are summarized in
[`RACE_BISECTOR_RESEARCH.md`](RACE_BISECTOR_RESEARCH.md).

## RX 5700 XT measurement (2026-10-08)

The eight-frame synthetic sequence had hash
`a06357453979901689f4f9c8ff2400a1efe5b9547e017a7fa4cf5219ba157ec2`.
Both Release builds ran all 84 cases with no process failures. The test machine
was Windows 11 x64, RX 5700 XT driver `32.0.21045.1000`, MSVC `19.51.36248.0`,
and the CMake-selected DXC `1.8.2502.11`.
An additional ordinary Release build passed with both diagnostic options
confirmed `OFF`.

| Build | Cases | First repeat-divergent prefix, all seeds | First instrumented/ordinary scratch mismatch, all seeds |
|---|---:|---:|---:|
| Standard | 84/84 | 11 | 11 |
| Global UAV barrier | 84/84 | 11 | 11 |

For `off`, `zero`, and `a5`, every comparison through prefix 10 matched across
the two fresh-process repeats and between instrumented/ordinary contexts.
Prefix 11 was the first observed scratch mismatch; the snapshot is after POST,
so the exact differing write could be in pass 11 or a POST write that depends
on it. Zero initialization did not remove repeat divergence. The full RGB
hashes were not repeatable for either provider context under any seed in
either build. On identical inputs, switching from `zero` to `a5` changed
ordinary and instrumented RGB hashes on all eight frames.

The global-barrier build kept the first observed mismatch at prefix 11. In the
cross-build comparison, inputs matched in all 84 paired cases. Captured scratch
and final RGB differed between the two builds for each full-model seed/repeat
pair; scratch differences were confined to prefixes 11 and 12 plus the full
run. This is compatible with timing/order sensitivity, but the existing
repeatability failure means it does not prove that barriers caused the change
or identify a production fix. O0 remains closed and O1-O13 remain locked.

Machine-readable reports are in
[`artifacts/results/fsr4-race-bisector/`](../artifacts/results/fsr4-race-bisector/).
Raw 20,880,256-byte-per-context scratch dumps remain in the ignored
`build/fsr4n10-race-bisector/` directory.
