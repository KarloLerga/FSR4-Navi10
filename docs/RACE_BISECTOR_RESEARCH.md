# Upstream grounding & separate hypotheses

Repo baseline: `KarloLerga/FSR4-Navi10@5b22fd0` (private, read through GitHub app).

Original AMD FSR4 provider is pinned from `01446e6a74888bf349652fcf2cbf5f642d30c2bf`.
The reference copy is:

- https://github.com/Rolaand-Jayz/FSR-4.0.2-reference/blob/main/Kits/FidelityFX/upscalers/fsr4/dx12/ffx_provider_fsr4_dx12.cpp
- https://github.com/Rolaand-Jayz/FSR-4.0.2-reference/blob/main/Kits/FidelityFX/backend/dx12/ffx_dx12.cpp
- https://github.com/Rolaand-Jayz/FSR-4.0.2-reference/blob/main/Kits/FidelityFX/upscalers/fsr4/include/gpu/fsr4/ffx_fsr4upscaler_resources.h
- https://github.com/Rolaand-Jayz/FSR-4.0.2-reference/blob/main/Kits/FidelityFX/upscalers/fsr4/dx12/ml2code_runtime/storage.hlsli

## Confirmed

- CPU POST/GPU POST agree with captured scalar p0..p3 and data: POST is not the
  current origin of run-to-run nondeterminism.
- Isolated 256/256 signed-DOT4 matches: it disproves a simple unconditional
  signed-DOT4 semantic mismatch on these inputs, but says nothing definitive
  about nonlinear end-to-end neural arithmetic, writes and indices.
- Scratch buffer resource ID is 22, initialized as `UNINITIALIZED`; source
  includes a commented-out clearing block. An uninitialized allocation does
  not prove it is read before first write.
- Backend's `addBarrier()` inserts UAV barriers for repeated UAV use, except
  skip barriers used only by WMMA padding subpasses; diagnostic *global*
  barrier is therefore a falsification test, not automatically a fix.
- Generated `storage.hlsli` uses 4-byte dword loads/stores for quantized I8.
  This does not rule out overlap between multiple shader workgroups writing
  the same dword, but there is no such overlap proven yet.

## Open

- First diverging ML pass (could be PRE, all-pass check required).
- Existence of a within-dispatch scratch race, incorrect thread indexing,
  invalid tensor padding, etc.
- Whether scratch fill seeds affect output and whether UAV barriers eliminate
  divergence.
- Whether full engine jitter/velocity/HDR contracts are valid for games.
- Quantitative real-scene image quality and actual upscaler latency.

## Reading results safely

`analysis.json.first_by_seed[*].first_repeat_divergent_prefix` is a *prefix
indicator* and the scratch dump is observed **after** POST. Do not interpret
it as the exact write inside the named pass without verifying that the POST
pass does not overwrite the region. Use GPU captures to see exact operator
boundaries. `first_instrumented_vs_ordinary_divergent_prefix` is a distinct
signal. The `off` seed is not a deterministic control.
