# P0 - Complete GPU-Native FSR4 Teacher and Capture

No Param4/Delta4 network should be declared successful before this is complete.

## 1. Stop using CPU pre/post as the teacher

Keep the current CPU image smoke as a regression/reference implementation.

Create a separate GPU teacher path using the pinned upstream FSR4 code.

The upstream source already contains optimized GPU pre and post stages. The provider also contains the actual resource setup, permutation selection and dispatch-size logic.

Do not manually invent the dispatch schedule from tensor dimensions when the provider supplies it.

## 2. Teacher frame graph

Implement approximately:

```text
input resources
   -> optional auto exposure
   -> upstream FSR4 PRE shader
      - temporal reprojection
      - recurrent reprojection
      - model input construction
      - first model/downscale work as upstream defines it
   -> model passes / padding passes in exact provider order
   -> upstream FSR4 POST shader
      - final model block
      - recurrent write
      - anisotropic 3x3 reconstruction
      - temporal blend
   -> optional RCAS only when explicitly comparing that mode
   -> final teacher RGB
```

The precise distinction between generated pass entry points and provider PRE/MODEL/POST IDs must follow `ffx_provider_fsr4_dx12.cpp` and the pinned source, not guessed numbering.

## 3. Reuse existing repository work

Current repo already has:

- model source hashes,
- initializer extraction,
- compiled model entries,
- GPU D3D12 harness,
- resource helpers,
- pass timing.

Extend these. Do not write a second independent DX12 framework.

Recommended new files, adapted to repository style:

```text
include/fsr4n10/fsr4_teacher.h
src/teacher/fsr4_teacher.cpp
src/teacher/fsr4_teacher_capture.cpp
shaders/teacher/ (only project instrumentation wrappers/variants)
tools/teacher/
```

## 4. Instrument without changing teacher output

Create capture-only variants behind a compile define such as:

`F4N10_CAPTURE_TEACHER=1`

Capture the raw four model parameters and recurrent output immediately where upstream POST has them.

Requirements:

- normal teacher build and capture build must produce identical final RGB within a strict numeric tolerance,
- capture UAV writes must not feed back into computation,
- no altered branch/control behavior,
- record shader/source hashes.

## 5. Deterministic temporal input format

Define a versioned capture input container, for example `.f4seq`.

Required per-frame fields:

```text
width / height
render size
output size
preset
frame index
jitter current / previous
motion convention
exposure / pre-exposure
reset flag
color
motion vectors
depth
reactive mask
transparency/composition mask
```

All optional inputs need an explicit validity flag.

Never silently substitute zero for a missing semantic input without recording that fallback in metadata.

## 6. Teacher output container

Define a versioned `.f4cap` or NPZ export containing:

```text
final RGB
reprojected history
current reconstruction source
raw p0..p3
physical rho/sx/sy/blend
recurrent r0..r3
model input channels
optional selected feature tensors
```

Store:

- source commit,
- model preset/tier,
- shader hashes,
- GPU/driver,
- frame sequence hash,
- exact build mode.

## 7. Procedural teacher dataset first

The repository already has a procedural temporal generator.

Expand it so its output can feed the real teacher, including:

- valid depth,
- valid motion vectors,
- jitter sequence,
- reactive regions,
- transparency/composition regions,
- exposure transitions,
- scene cuts.

Required stress cases:

- static subpixel lines,
- slow pan,
- fast pan,
- rotating spokes,
- scrolling UV pattern,
- specular/highlight change without matching geometric MV,
- alpha foliage/particles,
- foreground disocclusion,
- repeating textures,
- thin fence/wire,
- exposure jump,
- resolution change.

## 8. Teacher validation

Before any large training run:

1. compare GPU teacher against current CPU smoke for the subset both support,
2. compare instrumented vs non-instrumented GPU teacher final RGB,
3. run repeated deterministic sequences,
4. run reset/cut tests,
5. run at least 10,000 dispatch/frame-state stress operations,
6. verify no NaN/Inf,
7. save representative frames.

## 9. Teacher timing

Measure separately:

```text
pre
model neural passes
padding/reset passes
post
RCAS if enabled
total
```

Use GPU timestamps and warm-up.

This timing becomes the real baseline. The current ~7.26 ms summed model-pass median remains useful but is not the final baseline.
