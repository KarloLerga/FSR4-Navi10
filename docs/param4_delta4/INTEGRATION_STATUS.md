# Param4 / Delta4 Integration Status

This directory retains the reviewed technical documents from the supplied addendum. The embedded integration prompt and unreviewed reference programs were not imported. The archive manifest and hashes are in `ADDENDUM_SOURCE_MANIFEST.json`.

The addendum proposes two separate experimental paths:

- **Param4** predicts the four FSR4 reconstruction controls and four recurrent values while retaining FSR4 pre/post semantics.
- **Delta4** reuses FSR3 temporal signals and predicts a correction toward a GPU FSR4 teacher.

These are candidate architectures, not implementations of AMD's FSR4. Claims in the retained research documents are proposals until checked against the pinned FSR4 provider/source or measured on the RX 5700 XT.

## Current repository state

- The native/1080 I8 provider shader set and static D3D12 provider now build from pinned FSR4 source. The harness executes the provider's PRE/model/POST graph on the RX 5700 XT; a synthetic gradient/checkerboard run twice with reset produces the same final-output SHA-256.
- The existing harness executes the I8 model graph on synthetic/model-input data. Its image smoke still performs preprocessing and postprocessing on the CPU.
- The provider smoke does not expose raw model controls or recurrent values and uses synthetic input. A real-scene capture, aligned FSR3 captures, Param4/Delta4 training, and quality measurements are not present yet.
- Existing NaviQSR and NaviPRISM results remain independent and do not qualify as Param4/Delta4 evidence.

The implementation order is therefore teacher path and capture first, then capture validation/oracle analysis, then Param4/Delta4 model work. Never infer teacher quality from control error or a synthetic smoke.
