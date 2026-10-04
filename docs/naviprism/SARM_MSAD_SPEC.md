# SARM - SAD-Assisted Residual Motion

## Mandatory ISA validation

Create:
- shaders/microbench/msad4_microbench.hlsl
- tools/msad4_validation.cpp
- tools/dump_msad4_isa.ps1
- tests/test_msad4_reference.py

Validate on RX 5700 XT:
1. msad4 matches scalar reference math.
2. byte alignment/order explicitly unit-tested.
3. DXIL and RGA Navi10 ISA dump stored.
4. confirm native SAD/MSAD-class instructions or record expansion.
5. benchmark against scalar integer SAD and FP16 difference.

Do not assume intrinsic equals hardware speed.

## Zero-byte masking

Microsoft documents that zero reference bytes are masked. Therefore encode valid logical values 0..254 as stored values 1..255. Stored 0 is mask/sentinel only.

Distance is preserved: abs((a+1)-(b+1)) == abs(a-b).

Use this rule for SARM and SADNet data.

## Accumulator safety

Correctness is only guaranteed through 65535.
Maximum one 4-byte SAD contribution is 4*254=1016.
Use MAX_MSAD4_ACCUM_CALLS=48, then spill/add partial totals into wider software accumulators and reset uint4 accumulators.

## Match surfaces

Create current/history input-resolution quantized luma surfaces. Pipeline:
1. pre-exposure normalization,
2. RGB->luma,
3. optional local mean/contrast normalization,
4. clamp,
5. logical quantization 0..254,
6. store 1..255.

Optional descriptors: log-depth and gradient magnitude.

## Starting search geometry

match patch: 4x4
coarse tile: 8x8 LR pixels
dx: -3..+3
dy: -2..+2

Autotune later.

Engine MV predicts center. Search only residual motion.

## Why msad4 maps well

One 4-byte current row plus one 8-byte history span produces four horizontally shifted SAD values in one intrinsic. Four row calls evaluate a 4x4 patch for four X offsets.

## Confidence

Track best and second-best cost. Confidence uses uniqueness plus absolute match quality plus depth/MV/in-bounds/reactive validity.

Do not trust a match merely because its absolute cost is low if several neighboring candidates have nearly identical cost.

## Subpixel residual

For valid neighbor costs use a bounded quadratic fit:
delta = 0.5*(Cminus-Cplus) / max(Cminus - 2*Ccenter + Cplus, eps).
Clamp to [-0.5,+0.5]. Reject low-confidence/boundary/degenerate fits.

## Edge-aware propagation

Compute residual at tile/input scale. Upsample using depth/MV/luma guidance. Never blend foreground and background residual motion across a strong depth edge.

Outputs:
- residualMotion FP16x2
- refinedMotion
- confidence
- debug bestCost/ambiguity.
