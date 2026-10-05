# FSR4-Navi10 - DeltaControl V2 / Teacher-Sequence Addendum

Reviewed repository baseline:

- repository: `KarloLerga/FSR4-Navi10`
- reviewed `main` commit: `73193bd34dc0e7f8e060e2ebee902b70d6779570`
- provider instrumentation commit: `2c7141a19b2c87edf84c2d81a9e546c64e12457c`
- target GPU: Radeon RX 5700 XT / Navi10 / gfx1010
- upstream FSR4 source pin already used by the repository: `01446e6a74888bf349652fcf2cbf5f642d30c2bf`

This addendum does not replace the working I8 FSR4 provider, full FSR4 FP16, NaviQSR, NaviPRISM, Param4, or Delta4. It changes the immediate priority.

The project now has enough provider instrumentation to stop guessing about compression. The next run must build real stateful multi-frame FSR4 teacher sequences, pair them with FSR3.1.5, run a comprehensive oracle suite, then implement the cheapest architecture actually supported by measured data.

The primary new candidate is `DeltaControl V2`:

```text
FSR3 temporal semantics or exact FSR4 PRE semantics
                    +
        reprojected previous controls/state
                    |
                    v
          zero/analytic exit
              /          \
            pass         fail
             |             |
             |       coarse ParamGrid
             |             |
             |        quality gate
             |        /          \
             |      pass         fail
             |       |             |
             |       |       Shift1x1 exit
             |       |             |
             +-------+-------- hard tiles
                              |
                           NaviQSR
                              |
                              v
                    source-equivalent FSR4 POST
```

The key verified observation is that FSR4 does not directly emit RGB. Its model emits four reconstruction parameters plus four recurrent-state values. POST converts the four reconstruction parameters into a local anisotropic 3x3 reconstruction filter and a temporal blend. This is a much smaller learning target than reproducing the full U-Net hierarchy or directly predicting RGB.

## Immediate objective

Measure how much of the expensive FSR4 neural body on the local RX 5700 XT can be replaced by:

1. a closed-form or linear control estimator,
2. a coarse edge-aware control grid,
3. a tiny spatial-shift + 1x1 predictor,
4. temporal reuse of previous control decisions,
5. FSR3-derived temporal semantics,
6. sparse hard-tile fallback.

Do not assume any of these is sufficient until multi-frame teacher data proves it.

## Canonical teacher data

`raw_model_parameters` p0..p3 remain canonical teacher controls. `physical_controls` is useful capture/debug output but must be regenerated offline from raw p values using formulas pinned to the exact upstream source hash. Final reconstructed RGB is the semantic authority.

The upstream recurrent provider resource is already `R8G8B8A8_UNORM`. Do not spend another major experiment asking whether FP16 recurrent state can be reduced to 8-bit. Instead investigate recurrent dimension, spatial bandwidth, low-rank/codebook representations, and temporal predictability.

## How to use

Copy this package into the existing repository root. Then paste the complete contents of `CODEX_INTEGRATE_DELTA_CONTROL_V2.txt` into the currently running local Codex session.

Codex must preserve valid commits newer than the reviewed baseline rather than resetting the repository.
