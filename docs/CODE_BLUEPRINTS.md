# Code blueprints and interface decisions

The `blueprints/` folder contains interface shapes, not finished release code. Codex should use them to avoid redesigning basic boundaries, then move/refine them into the real `include/`, `src/` and `shaders/` trees.

## Core API
Keep backends behind `IBackend`. The reference and optimized paths must be switchable without recreating unrelated harness infrastructure. A context may need backend-specific resources; backend create/destroy owns them.

## Model pack
Use a versioned, bounds-checked model pack with SHA-256 provenance. The exact tensor metadata may require extending `TensorRecord`; backward-compatible version bumps are preferred over ad-hoc side files.

## Telemetry
All benchmark/autotuning output should have stable machine-readable schema. Add fields rather than emitting human-only logs.

## HLSL
`navi10_fp16_common.hlsli` intentionally contains only a tiny blueprint. The compatibility quantization function is NOT authoritative; Codex must replace it with exact formulas from the upstream operator implementation and add tests before using it.
