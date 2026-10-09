# Pass1 intrinsic recovery results

## Scope

This records the diagnostic package `FSR4-Navi10-Intrinsic-Recovery-3ed1c9a`
on the project branch at base commit
`3ed1c9a53b779382d466f6b95ef26d9d14536965`. The package's embedded prompt was
reviewed as archive content; repository instructions and the user's request
remain authoritative. The package introduced only build-local shader overlays
and diagnostics. No pinned `third_party/` source was modified.

The GPU runs used an AMD Radeon RX 5700 XT, driver `0x00200000523503e8`, the
pinned FidelityFX source commit
`01446e6a74888bf349652fcf2cbf5f642d30c2bf`, and sequence SHA-256
`a06357453979901689f4f9c8ff2400a1efe5b9547e017a7fa4cf5219ba157ec2`.
Every candidate was compared with the shared scalar reference and identical
Pass0 inputs. The independent inference used 128 sampled coordinates and all
16 output channels (2,048 raw accumulator values).

## Results

The exact best signedness model treated the input bytes as signed and the
weight bytes as unsigned: input mask `0x0`, weight mask `0xF`, and 2,048/2,048
exact lanes across `acc0_0..3`, with zero maximum error. This explains the
sampled raw accumulator captures; it does not by itself establish the
hardware's intended arithmetic or match to AMD reference behavior.

All seven builds (`native` plus six experiments) matched the scalar reference
at the first fused-DOT4 tap on 256 sampled pixels. The next gate separated
the candidates:

| Candidate | `acc0_0` exact lanes | Final Pass1 exact lanes | O0 numeric gate |
|---|---:|---:|---|
| `native` | 1/512 | — | Not run; `acc0_0` failed |
| `native_zero` | 1/512 | — | Not run; `acc0_0` failed |
| `native_swap` | 1/512 | — | Not run; `acc0_0` failed |
| `native_swap_zero` | 1/512 | — | Not run; `acc0_0` failed |
| `unpack_dot` | 512/512 | 2,048/2,048 | Failed |
| `unpack_scalar` | 512/512 | 2,048/2,048 | Failed |
| `unsigned_bias_3dot` | 512/512 | 2,048/2,048 | Failed |

The four failing accumulator variants had maximum absolute `acc0_0` error
84,224. The three exact Pass1 candidates all used the same Pass0 inputs and
then passed the eight-frame repeatability check. The unchanged O0 numeric gate
still failed for each: CPU POST found 2,073,600/2,073,600 model pixels
non-finite at each audited frame (0, 4, and 7). RGB replay matching itself
does not make those intermediate values numerically valid.

Provider manifests confirm the variant builds changed Pass1 shader payloads;
the other provider payload hashes match the corresponding native `dot0`
build. Selector metadata changes are recorded separately in the isolation
report. No candidate replaces the production DOT4 path.

## Validation and limits

The archive package tests passed 13/13, the full Python suite passed 132/132,
and the ordinary Release build and CTest passed 1/1. The existing CMake cache
keeps the experimental mode empty, Pass 11 guard OFF, scalar DOT4 OFF, and
prefix diagnostics OFF. No performance or ISA measurement was made for these
candidates. The synthetic O0 gate remains closed, and no AMD-reference image
quality or game-readiness claim follows.

Compact JSON evidence is in
[`artifacts/results/pass1-intrinsic-recovery/`](../artifacts/results/pass1-intrinsic-recovery/).
Raw captures and build trees remain ignored under `build/p1fix/`.
