# NaviPRISM - Research Findings and Engineering Conclusions

## Evidence labels

VERIFIED means directly supported by public source/hardware docs.
DERIVED means calculation/inference from verified facts.
PROPOSED means project-specific design requiring validation.

## 1. Filter-bank SR can replace expensive inference

VERIFIED - RAISR learns local reconstruction filters offline and selects one at runtime from a cheap local-image hash. Its classic descriptor includes edge orientation, edge strength, coherence and subpixel/pixel type. The important lesson is that learned reconstruction can be converted into cheap classification plus one selected filter. RAISR reported one to two orders of magnitude faster runtime than strong methods of its era while remaining competitive in image quality.

Project conclusion: train a richer temporal reconstruction filter atlas from FSR4/native-HR captures. Runtime descriptors may include edge orientation/strength/coherence, depth discontinuity, reactive state, refined motion confidence, jitter/subpixel phase, alias-risk and history confidence.

## 2. Learned resampling can approach interpolation cost

VERIFIED - LeRF learns spatially varying steerable resampling functions and accelerates the predictor with LUTs. The published method reports interpolation-like speed while outperforming ordinary interpolation.

Project conclusion: NaviQSR AKR should gain a zero-CNN runtime option:
local descriptor -> LUT/filter parameters -> steerable analytic resampler.

## 3. Large receptive fields do not require huge LUTs

VERIFIED - MuLUT, RCLUT, HKLUT and IQ-LUT show several ways to avoid monolithic exponential LUT storage. RCLUT decouples spatial/channel computation; HKLUT reaches hundred-kilobyte-scale models; IQ-LUT combines interpolation, quantization, residual learning and distillation.

Project conclusion: use factorized spatial/temporal classes, hierarchical backoff tables, interpolated parameters, multiple small stages and residual reconstruction. Do not create one giant Cartesian LUT.

## 4. Navi10 has hardware generic ML upscalers do not target

VERIFIED - DirectX HLSL exposes msad4(reference, source, accum). It compares one 4-byte reference against four byte alignments in an 8-byte source and returns four SAD accumulators. Zero reference bytes are masked and correct accumulation is only guaranteed through 65535.

VERIFIED - AMD RDNA 1.0 ISA documents V_MSAD_U8, V_QSAD_PK_U16_U8 and V_MQSAD_PK_U16_U8.

Project conclusion: repurpose these image/video matching primitives for:
1. residual motion search,
2. descriptor/prototype search,
3. additive/SAD network kernels.

## 5. SARM - SAD-Assisted Residual Motion

PROPOSED - engine motion vectors are a strong prior but do not always represent animated textures, reflections, particles, thin/stochastic detail or missing object motion. Search a tiny local residual neighborhood around the engine MV using msad4. Output dx/dy residual, match confidence and ambiguity.

Refined vector: MV_refined = MV_engine + MV_residual.

Use it for history reprojection, NaviQSR latent reprojection, phase history and hard/easy classification.

## 6. Additive SR can be a hard-region fallback

VERIFIED - AdderSR shows that super-resolution networks can replace multiplication-heavy convolutions with adder/L1 operations and obtain visual quality comparable to CNN baselines in the reported models. It also shows identity mapping/high-frequency handling need explicit care.

Project conclusion: do not convert full FSR4 to AdderNet. Train a small SADNet only on hard tiles. Easy path remains filter/LUT based.

## 7. Binary/logic networks are routers, not default final reconstruction

Image-restoration literature includes binarized restoration units and logic-gate networks. For NaviPRISM their best first use is routing: expert selection, history accept/reject and hard/easy classification. A Hamming router can use XOR + countbits. Only keep it if it beats simple integer hashing on real Navi10.

## 8. Sparse low-rank experts can serve hard regions

VERIFIED - SeemoRe uses efficient expert mining and mixtures of low-rank experts for SR.

Project conclusion: if one hard expert is insufficient, train sparse specialists for thin detail/foliage, speculars, disocclusion and reactive areas. Never evaluate every expert.

## 9. PHR - Polyphase History Reservoir

VERIFIED - Unreal TSR aggregates details into display-resolution history rather than retaining raw samples and has history resurrection.

DERIVED - for exact 2x scaling, four LR phase histories contain 4*W*H color samples, equal to one 2W*2H HR history at equal bytes/sample.

PROPOSED - store four subpixel phase evidence slices instead of immediately averaging all temporal evidence into one HR color. Reproject/validate the phase slices and use THFA/AKR only where evidence is incomplete. This may preserve real jitter-acquired detail and reduce neural hallucination. It must be A/B tested against normal HR history.

## 10. Combined architecture

Current LR color/depth/MV/jitter/masks
 -> cheap descriptor
 -> SARM residual motion + confidence
 -> refined history warp
 -> THFA steerable filter lookup
 -> cheap current/history reconstruction
 -> confidence routing
 -> easy: finish
 -> hard: SADNet or NaviQSR
 -> history validation/blend
 -> HR output.

Optional PHR contributes phase-separated evidence.

## 11. Core architectural success criterion

Most stable/easy pixels should execute zero conventional neural convolution.

Expected cost hierarchy to test:
1. descriptor/hash: tiny,
2. SARM: small,
3. atlas/filter reconstruction: interpolation-like,
4. sparse SADNet: hard tiles only,
5. NaviQSR: rarer fallback,
6. full FSR4 FP16: teacher/reference/debug path.

If nearly every tile routes to SADNet/NaviQSR, NaviPRISM failed its purpose. If the fast path causes visible temporal instability, it also failed.
