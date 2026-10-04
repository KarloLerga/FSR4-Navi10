# FSR4-Navi10 - NaviPRISM Research Addendum

This is the third architecture addendum for the existing FSR4-Navi10 project.

It must be integrated without deleting existing work:
- current I8 FSR4 execution/smoke path,
- full FSR4 FP16 work,
- NaviQSR / QSSR-inspired work,
- model-pack validation,
- pass catalog,
- tests,
- current benchmark and output files.

The new architecture is called NaviPRISM: Primitive Reconstruction with Indexed Steerable Models.

Central hypothesis:

Use FSR4 as an offline teacher, but perform most production-frame reconstruction with inexpensive primitives Navi10 already has in hardware: SAD pattern matching, texture/LUT lookups, Gather/bilinear sampling, compact temporal history, analytic or learned local filters, FP16 only where it materially helps, and neural/SADNet fallbacks only for difficult regions.

Required architecture families after integration:
1. full_fsr4_fp16 - full quality/reference/teacher path.
2. naviqsr_* - existing QSSR-inspired low-spatial neural paths.
3. naviprism_filter - normal easy path, no conventional CNN convolution over most pixels.
4. naviprism_sadnet - sparse hard-tile additive/SAD correction path.
5. naviprism_phase - optional phase-separated temporal evidence reservoir.
6. auto - measured quality-safe routing between the above.

NaviPRISM is not claimed to be globally novel. It is a project-specific synthesis of public research plus Navi10-specific engineering.

This document is preserved as technical design input. The companion Codex workflow prompt was reviewed separately and was not copied into repository instructions.
