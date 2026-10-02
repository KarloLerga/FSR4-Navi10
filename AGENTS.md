# Repository instructions for Codex

## Mission
Build `FSR4-Navi10`: a DirectX 12 FSR 4.0.2 implementation optimized specifically for AMD Navi10 / gfx1010 / RX 5700 XT, with a quality-preserving FP16-first neural backend and reproducible validation.

## Source of truth
For architecture and implementation requirements use:
- `docs/MASTER_SPEC.md`
- `docs/DECISIONS.md`
- `docs/NAVI10_BACKEND.md`
- `docs/MODEL_PIPELINE.md`
- `docs/NUMERICS_AND_QUALITY.md`
- `docs/BUILD_AND_BOOTSTRAP.md`
- `docs/UPSTREAMS_AND_LICENSE.md`
- `docs/ACCEPTANCE_CRITERIA.md`
- `docs/CODE_REVIEW_CHECKLIST.md`
- `docs/FAILURE_MODES.md`

For long work use the ExecPlan contract in `.agent/PLANS.md`.

## Non-negotiable engineering rules
- Target Windows 11 + DirectX 12 first. Do not spend project time on Vulkan/Linux/macOS.
- Target Navi10/gfx1010 first. Generic compatibility is secondary.
- Compile HLSL with DXC and true 16-bit types (`-enable-16bit-types`) for FP16 paths.
- Preserve a faithful reference backend for differential validation.
- Do not hardcode unsupported assumptions about gfx1010 dot-product support. Verify generated ISA and runtime timings.
- Do not optimize by lowering requested image quality in the default backend.
- Prefer offline specialization/code generation over runtime genericity when it improves Navi10 performance.
- Keep weight/model conversion deterministic and reproducible.
- All generated artifacts must be rebuildable from documented commands.
- Third-party research repositories are references only; do not copy large chunks blindly and do not execute their setup scripts without review.
- Do not commit downloaded tool installers, large upstream repos, captures, or AMD redistributables into this repo unless their license explicitly allows it and MASTER_SPEC requires vendoring. Prefer pinned fetch scripts.
- Never modify the user's GPU firmware, VBIOS, power limits, registry driver internals, or Windows security settings.

## Verification discipline
Every meaningful implementation change must pass the relevant local checks. Final claims require measurements. Keep the latest validated values in `RESULTS.md`; keep raw machine-readable data in `artifacts/results/`.

## Completion behavior
Do not stop at scaffolding. Do not leave TODO/FIXME in release-path code. If a temporary stub is introduced, track it in PROGRESS.md and remove it before final completion.
