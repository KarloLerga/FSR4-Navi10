# FSR4-Navi10 - Param4 / Delta4 Addendum

This addendum is written specifically against public repository commit:

`e739364564fd9d68242b0fdd79e51d8b81b5fcd3`

Repository:
`https://github.com/KarloLerga/FSR4-Navi10`

It does not replace the existing architecture families:

- full FSR4 compatibility / FP16 work,
- NaviQSR,
- NaviPRISM.

It changes the priority of the next engineering run.

The most important new source-level discovery is that FSR4's model does not directly synthesize the final RGB image. The final network output is an 8-channel control/state field. The post stage interprets four channels as parameters of a spatial reconstruction filter and temporal history blend, while the other four channels are recurrent state for the next frame.

Therefore the next major architecture family is:

# Param4

Predict FSR4's actual control/state field with a much cheaper Navi10-native model, while retaining the real FSR4 pre/post semantics.

And the more aggressive derivative is:

# Delta4

Use the open-source FSR3.1 temporal pipeline as a cheap front-end. Reuse signals FSR3 already calculates (current reconstruction, reprojected history, reactive/disocclusion/shading-change/accumulation, luma instability, locks, motion/depth) and predict only the information needed to move the result toward the FSR4 teacher.

The project must first build a genuine GPU-native FSR4 teacher/capture path. No further claims about large Param4/Delta4 networks are valid before that exists.

## New required runtime families

Keep existing modes and add:

- `teacher_fsr4_gpu`
- `param4_exactpre_dense`
- `param4_controlgrid`
- `param4_temporal_delta`
- `delta4_fsr3_control`
- `delta4_basis`
- `delta4_auto`

The addendum also defines several oracle analyses. They must be run before committing to a large architecture. The purpose is to determine what FSR4 actually needs instead of assuming a neural network is necessary everywhere.

## Highest priority

1. Complete exact GPU FSR4 pre/model/post teacher.
2. Capture FSR4 raw control parameters and recurrent state.
3. Run control-field bandwidth/compressibility oracles.
4. Run FSR3-to-FSR4 basis/control oracles.
5. Train a tiny exact-control Param4 network.
6. Implement adaptive/temporal reuse only after the dense Param4 network is quality-qualified.

Do not spend the next run mainly on `msad4` optimization. The real RX 5700 XT measurement at e739364 showed no meaningful speedup over scalar-u8 in the current benchmark.
