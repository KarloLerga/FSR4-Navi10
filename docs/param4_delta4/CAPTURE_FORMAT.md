# Teacher Capture Package Format

`f4n10.teacher.capture.v1` is a deterministic ZIP package with the `.f4cap` suffix. The root contains `capture.json`; all channel-last arrays are raw little-endian binary files under `arrays/`. The archive uses stored entries so validation can stream bytes without trusting decompression metadata. Capture writes must originate from the GPU teacher path; packaging synthetic data does not make it teacher evidence.

## Manifest

The manifest has four fields:

- `schema`: exactly `f4n10.teacher.capture.v1`.
- `metadata`: sequence/frame identity and sequence hash, input/output sizes, jitter, exposure, reset, motion convention, upstream commit/source hash, compiled shader hashes, GPU/driver and build mode.
- `validity`: explicit booleans for input color, depth, motion vectors, reactive mask and transparency/composition mask. The first three are required and valid. Optional masks are included only when their validity flag is true; missing masks are never silently replaced by zero.
- `arrays`: logical array name to `{path, dtype, shape, sha256}`. The pack command accepts `file` as a source-relative name and writes the content hash and final `path` into the package manifest.

Provider-generated manifests also include `metadata.physical_control_transform`. The synthetic capture tap records stable mathematical tanh/sigmoid equivalents for `(rho, sx, sy, blend)` from the raw p0..p3 values. It is capture-only and does not feed reconstruction. This distinction matters when logits exceed the FP32 exponential range: the stable controls remain finite, while a literal evaluation of the source's exponential tanh expression can overflow. Do not interpret the field as a bitwise readback of an internal provider control buffer.

Float arrays use `<f2` or `<f4`; byte masks may use `|u1`. More scalar integer encodings can be added only with an explicit schema revision. Every array is contiguous and channel-last. All floating values must be finite.

## Required arrays

`input_color`, `depth`, and `motion_vectors` describe render-resolution input. `current_reconstruction_source` is the exact source sampled by FSR4 POST; `reprojected_history` is output-resolution history. The package must also contain `model_input_semantic_channels`, `raw_model_parameters` (p0..p3), `physical_controls` (rho/sx/sy/blend), `recurrent_state` (r0..r3), and `final_rgb`. Control/state arrays are output-resolution HWC with four channels. The model-input spatial shape is recorded rather than guessed by this format.

`reactive_mask` and `transparency_composition_mask` are optional but their validity flags are mandatory. Optional feature tensors may be added under names defined in `tools/teacher/capture_format.py`.

## Validation

`python tools/teacher/validate_teacher_capture.py capture.f4cap` checks archive paths/duplicates, schema and metadata, dtype/shape/byte-count consistency, SHA-256, CRC, required arrays, dimensions, and NaN/Inf values. It emits a JSON summary and exits nonzero on invalid input. `package_teacher_capture.py` builds the deterministic archive from a manifest and a directory of raw arrays, then runs the same validator.

The synthetic RX 5700 XT smoke currently exercises the GPU provider capture taps, instrumented-vs-normal RGB equality, repeated-reset tap determinism, package generation and validation. This package definition remains a transport and audit contract; synthetic input does not substitute for representative real-scene sequences, aligned FSR3 data, temporal stress runs, or quality measurements.
