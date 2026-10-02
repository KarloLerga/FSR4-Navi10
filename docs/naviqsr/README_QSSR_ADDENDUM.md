# FSR4-Navi10 — QSSR / NaviQSR Research Addendum

This package is an **addendum** to the existing `FSR4-Navi10` Codex handoff.

Do **not** replace or discard the work already in progress. The existing dense/reference FSR4 path remains mandatory and becomes:

1. the correctness/reference implementation,
2. the quality teacher for distillation,
3. the dense fallback for invalid temporal state,
4. the benchmark against which NaviQSR is judged.

The new work adds a second architecture family, `NaviQSR`, aimed specifically at RX 5700 XT / Navi10. It combines:

- a QSSR-inspired low-spatial-resolution neural trunk,
- FP16 packed math,
- invertible polyphase / optional Haar feature decomposition,
- separate low/high-frequency processing,
- structural re-parameterization,
- jitter-phase specialization,
- teacher-guided analytic reconstruction,
- motion-compensated latent caching,
- tile-sparse recomputation with dense fallback,
- optional Winograd / low-rank kernels selected only when measured faster,
- hardware-in-the-loop architecture selection on the actual RX 5700 XT.

## What to do

1. Copy this package into the root of the existing `FSR4-Navi10` repository.
2. Paste the entire contents of `CODEX_INTEGRATE_QSSR_ADDENDUM.txt` into the currently running local Codex session.
3. Do not manually delete current code.
4. Codex must read all documents under `docs/` in this addendum before changing architecture.

The key design decision is:

> **Do not force the full FSR4 U-Net to be the only production algorithm. Keep it as teacher/reference, but build a much cheaper RDNA1-native network whose neural network predicts reconstruction decisions, not necessarily the final RGB image.**

The strongest new experimental path is called **MCLD-AKR**:

- **MCLD** = Motion-Compensated Latent Delta reuse
- **AKR** = Analytic Kernel Reconstruction

This is an engineering synthesis of several public ideas. It is **not claimed as a novel patented invention**, and the public sources/patent inspirations are documented in `docs/SOURCES_QSSR.md`.
