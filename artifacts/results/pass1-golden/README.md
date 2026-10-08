# Pass1 Golden oracle evidence

RX 5700 XT Native/1080 Pass1 diagnostic results from the pinned FSR4 source. The JSON includes the 20-stage sampled CPU-oracle comparisons, 40 GPU campaign manifests, 160 successful fresh-process cases, runner summary, and 4096-case dot4 conformance report. All reports identify the source model by SHA-256. The synthetic sequence SHA-256 and driver/build information are recorded in each campaign manifest.

Large raw scratch/input captures and all per-stage build trees remain under the ignored local `build/p1/` directory. They are intentionally not included here; paths recorded inside campaign/oracle JSON refer to that local output tree. From the repository root, regenerate the sweep with `scripts/run-pass1-golden.ps1 -Repository C:\src\FSR4-Navi10 -Sequence build\release\delta-control-smoke.f4seq -AllStages`.

The evidence finds a raw intrinsic/scalar path difference beginning at `acc0_0`, while the scalar path matches the independent CPU INT32 oracle at all sampled stages. This does not identify which implementation matches AMD hardware arithmetic or prove image quality. The production gate remains closed, and default options remain unchanged.
