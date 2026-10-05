# `f4n10.sequence.v2` input contract

`.f4seq` is a deterministic ZIP64-compatible container with `ZIP_STORED` members. It is the common source for the FSR4 teacher, the pinned FSR3.1.5 provider, and offline tools. The container is an input format; provider output remains in `.f4cap` or later derived shards.

## Members

- `sequence.json`: readable metadata, frame records and per-plane SHA-256 hashes.
- `sequence.bin`: fixed little-endian cross-language index consumed by the native harness.
- `frames/NNNNNN/{color,depth,motion_vectors,reactive_mask,transparency_composition_mask}.raw`: tightly packed row-major planes. Every frame requires color, depth and motion vectors. Optional planes appear only when their validity bit is true; absent data is not represented by a zero-filled plane.

All members must be relative canonical POSIX paths, unencrypted and stored without compression. The validator rejects duplicate/extra/missing members, unsafe paths, size/shape mismatches, non-finite floats, and index, per-plane, ZIP CRC or sequence-hash mismatches. Bounds are 16,384 pixels per dimension, 100,000 frames, 1 GiB per plane and 64 GiB total payload.

## Plane formats

| Plane | Dtype | Shape | Meaning |
|---|---|---|---|
| `color` | little-endian FP16 | `[render_h, render_w, 4]` | Linear scene color and alpha; not display-encoded sRGB |
| `depth` | little-endian FP32 | `[render_h, render_w, 1]` | Forward depth in `[0,1]` for the initial runtime |
| `motion_vectors` | little-endian FP16 | `[render_h, render_w, 2]` | Current-pixel to previous-frame pixel displacement, in render pixels, excluding camera jitter |
| `reactive_mask` | U8 | `[render_h, render_w, 1]` | Optional normalized reactive data, 0..255 |
| `transparency_composition_mask` | U8 | `[render_h, render_w, 1]` | Optional normalized transparency/composition data, 0..255 |

The motion-vector direction and screen-space range match the AMD FSR3 integration contract. V2 requires unjittered vectors: camera jitter is supplied separately, so the FSR3 jitter-cancellation flag remains disabled. FSR expects vectors to identify where a current pixel was located in the previous frame. Jitter offsets are in render-pixel units. The current native FSR4 harness has only the native/1080 shader permutation compiled; the format can represent other dimensions, but that does not imply the current provider can execute them.

## Metadata and binary index

`sequence.json` stores sequence ID, seed, source kind/hash, render/output dimensions, preset and nominal scale, motion/depth conventions, plus for each frame: index, delta time, current/previous jitter, exposure, pre-exposure, reset, camera cut, mask validity, and array descriptors/hashes. `source_kind` is one of `renderer_capture`, `procedural_synthetic`, `imported_buffers`, or `test_fixture`; it prevents a generated fixture from being presented as a captured scene.

`sequence.bin` starts with a 200-byte header (`F4N10SQ2`, version, header/table sizes, frame count, dimensions, preset/scale, seed, source-kind ID, convention IDs, fixed 64-byte ASCII sequence ID, source SHA-256 and sequence SHA-256). It is followed by one 212-byte frame record per input frame: index, reset/cut/mask-valid flags, seven FP32 timing/jitter/exposure values, reserved zeroes, and five 32-byte input-plane hashes in table order. All integers/floats are little endian.

The sequence hash is SHA-256 over the complete binary index with the sequence-hash field zeroed, followed by every present raw input plane in frame order and table order. Thus it covers frame metadata, input bytes and all per-frame hashes while excluding ZIP timestamps and JSON formatting. The index and manifest also carry their own independent SHA-256.

## Tools

```powershell
python tools/sequence/make_procedural_suite.py build/release/delta-control-smoke.f4seq --frames 8
python tools/sequence/validate_f4seq.py build/release/delta-control-smoke.f4seq
```

The procedural generator combines static fine detail, camera pan, moving geometry, a disocclusion strip, shading variation, reactive/composition masks, jitter and a reset/camera cut. It is for format and stateful-pipeline checks only. It is not representative rendered content and cannot clear teacher-quality gates. `pack_f4seq.py` packages renderer-produced raw planes using a JSON description and never synthesizes missing inputs.

FSR3.1.5 version is verified from the pinned SDK header (`third_party/fidelityfx-current/Kits/FidelityFX/upscalers/fsr3/include/ffx_fsr3upscaler.h`); AMD's [FSR 3.1.5 integration manual](https://gpuopen.com/manuals/fidelityfx_sdk/techniques/super-resolution-upscaler/) documents the motion-vector convention.
