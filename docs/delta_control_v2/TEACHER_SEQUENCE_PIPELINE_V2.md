# Multi-frame teacher sequence pipeline V2

## New versioned input container

Implement `f4n10.sequence.v2` with extension `.f4seq`.

The same sequence object must be consumable by:
- FSR4 provider teacher
- FSR3.1.5 reference
- Param4/DeltaControl candidates
- future game/renderer captures

Required sequence metadata:
- sequence id and deterministic seed/source hash
- frame count
- render/output dimensions
- preset/scale factor
- frame time delta
- jitter current/previous
- exposure/pre-exposure
- reset/camera cut
- motion-vector convention
- depth convention
- optional reactive/T&C validity
- per-frame content hashes

## Required operating points

Use source/API-derived render-size rounding. At minimum cover:

1080p output:
- Quality
- Balanced
- Performance

1440p output:
- Quality
- Balanced
- Performance

2160p output, primary user target:
- Quality, nominal 2560x1440 input
- Balanced, exact source/API-derived dimensions
- Performance, nominal 1920x1080 input

Never fake 4K by resizing an already-upscaled 1080p teacher result.

## Jitter

Use the pinned FSR API/query helper where possible. Canonical phase-count sanity checks:
- Quality 1.5x: 18
- Balanced 1.7x: 23
- Performance 2.0x: 32
- Ultra Performance 3.0x: 72

Steady-state sequences should include at least two full jitter cycles. Recommended minimums:
- Quality: >=72 frames
- Balanced: >=92 frames
- Performance: >=128 frames

Also add >=512-frame long validation and >=10,000 total stateful dispatch stress across reset/cut cases.

## Procedural sequence families

A. static convergence
- fine checker
- thin diagonal wires
- subpixel text-like strokes
- static high-frequency texture
- stationary camera with jitter

B. camera motion
- slow constant pan
- accelerating pan
- rotation
- zoom
- fast camera movement

C. geometry motion
- moving foreground/background
- crossing thin objects
- rotating/articulated approximation

D. disocclusion
- foreground reveal
- repeated occlusion/reveal
- moving depth edge

E. shading without matching geometric motion
- moving specular highlight
- scrolling UV
- emissive pulse
- animated texture

F. alpha/reactive
- foliage-like alpha cards
- particles
- transparent/composition content

G. ambiguous repetition
- fences
- repetitive grids
- moire

H. state discontinuities
- camera cut
- exposure jump
- resolution/scale change
- reset

## Teacher output strategy

For selected audit frames, write complete `.f4cap` packages.

For long sequences, stream provider outputs directly into the derived training shard format. Do not create hundreds of 200+ MB audit packages by default.

## Warmup and convergence

Report separately:
- reset/cold frames
- convergence frames
- steady state

Do not include cold/reset cost in steady-state quality or latency unless explicitly reporting it.

## GPU timestamps

Add provider timestamp ranges:
- teacher.pre_us
- teacher.model_us
- teacher.padding_us
- teacher.post_us
- teacher.rcas_us
- teacher.total_us

Exclude compilation, PSO creation, CPU packaging, readback, and file I/O.
