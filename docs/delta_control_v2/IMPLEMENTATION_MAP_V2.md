# Implementation map against current repository

Reviewed tree already contains:

```text
src/teacher/gpu_teacher.cpp
src/teacher/provider_i8_native_1080_shader_selector.cpp
src/teacher/provider_query_compat.cpp

tools/teacher/
  audit_provider_schedule.py
  capture_format.py
  compile_provider_i8_native_1080.py
  package_teacher_capture.py
  validate_teacher_capture.py

docs/param4_delta4/
shaders/naviqsr/
shaders/naviprism/
```

Extend these responsibilities instead of creating an unrelated second DX12 framework.

## Suggested additions

```text
include/fsr4n10/
  sequence.h
  oracle.h
  deltacontrol.h

src/sequence/
  f4seq_reader.cpp
  f4seq_writer.cpp
  procedural_sequence.cpp

src/teacher/
  gpu_teacher_sequence.cpp
  teacher_timestamps.cpp

src/fsr3/
  fsr3_reference.cpp
  fsr3_capture.cpp
  fsr3_shader_selector.cpp

src/deltacontrol/
  exact_post_replay.cpp
  control_grid.cpp
  bilateral_slice.cpp
  analytic_control.cpp
  shift1x1.cpp
  temporal_control_cache.cpp
  multi_exit_router.cpp
  deltacontrol_runtime.cpp

shaders/deltacontrol/
  control_grid_predict.hlsl
  bilateral_slice_post.hlsl
  analytic_control.hlsl
  shift1x1_block.hlsl
  control_delta.hlsl
  tile_error_router.hlsl
  temporal_control_reuse.hlsl

tools/sequence/
  make_f4seq.py
  validate_f4seq.py
  make_procedural_suite.py

tools/dataset/
  build_training_shards.py
  validate_training_shard.py
  sample_hard_tiles.py

tools/oracles/
  replay_post.py
  control_bandwidth.py
  control_pyramid.py
  analytic_control.py
  control_pca.py
  kernel_codebook.py
  delta_basis.py
  offset_basis.py
  residual_sparsity.py
  temporal_reuse.py
  multi_exit.py
  run_oracle_suite.py

training/deltacontrol/
  model.py
  shift_blocks.py
  dataset.py
  losses.py
  train.py
  export.py
  evaluate.py
```

Codex may adapt filenames to repo style, but must not collapse responsibilities into one monolithic source file.

## CMake/test targets

Add explicit targets/tests for:
- f4seq validation
- stateful teacher sequence smoke
- exact POST replay
- FSR3 aligned capture
- oracle deterministic fixtures
- control-grid D3D12 smoke
- temporal reuse reset/cut
- multi-exit routing
- long stateful dispatch stress

## Artifact directories

```text
artifacts/sequences/
artifacts/captures/
artifacts/datasets/
artifacts/oracles/
artifacts/deltacontrol/
```

Commit:
- manifests
- small deterministic fixtures
- JSON/Markdown results
- tiny representative images when appropriate

Ignore by default:
- large captures
- training shards
- large checkpoints
- temporary profiling output

## Existing code reuse rules

1. Reuse existing D3D12 device, descriptor, resource and timestamp helpers.
2. Reuse current provider build and capture overlays.
3. Keep upstream source checkout unmodified; continue generated overlay strategy.
4. Extend current capture schema only through explicit versioning/optional fields.
5. Preserve normal-vs-instrumented output equality tests.
6. Keep all prior NaviQSR/NaviPRISM tests passing.
