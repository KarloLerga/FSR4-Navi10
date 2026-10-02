# Research notes that motivated the design

These are engineering context, not implementation truth. Codex should use fetched source and local measurements as authority.

1. AMD's current FidelityFX/FSR SDK documentation lists FSR Upscaling 4.1.1 as an ML upscaler integrated through the FSR API and signed binary distribution. This means current 4.1.x is not the editable production base for this project.

2. FidelityFX SDK 2.0.0 release history introduced FSR 4.0.2. A source-bearing AMD commit (`01446e6a74888bf349652fcf2cbf5f642d30c2bf`) is publicly referenced by multiple research projects. Public mirrors describe the tree as containing FSR4 model HLSL, ML2Code runtime, provider and INT8/FP8 model variants.

3. Public complete-port work on Apple GPUs demonstrates that the model can be represented with a full FP16 backend while retaining a reference INT8 path and pass-by-pass numerical validation. Hardware/toolchain differ from Navi10, so only the workflow concept transfers.

4. AMD's RDNA performance guide explicitly recommends true 16-bit types via DXC `-enable-16bit-types` to access double-rate 16-bit math where supported. It also recommends compute access patterns such as 8x8-style blocks for coalescing.

5. LLVM's current gfx10.1 documentation makes gfx1010 dot-instruction support more nuanced than the simplistic claim “all RDNA1 lacks DP4A.” gfx1011/gfx1012 have explicit restrictions that are not worded identically for gfx1010. Therefore this project does not base its architecture on an unverified instruction-support assumption: it compiles, inspects ISA and measures both paths.

6. Public FSR4 source-analysis projects report a mixed model where many INT8 passes use packed dot operations, while FP8 paths rely on newer wave-matrix machinery. Navi10 has no reason to emulate RDNA4 WMMA; a purpose-built vector FP16 path is the chosen design.

7. RGP supports RX 5000 and DirectX 12; RGA can produce AMD ISA/resource statistics. They are appropriate validation tools for this project.
