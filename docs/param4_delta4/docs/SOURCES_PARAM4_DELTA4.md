# Research Sources - Param4 / Delta4

## Project repository audited

https://github.com/KarloLerga/FSR4-Navi10
Baseline commit for this addendum:
`e739364564fd9d68242b0fdd79e51d8b81b5fcd3`

## FSR4 4.0.2 reference source mirror used for architecture inspection

https://github.com/Rolaand-Jayz/FSR-4.0.2-reference

Key files:

- `Kits/FidelityFX/upscalers/fsr4/include/gpu/fsr4/pre_common.hlsli`
- `Kits/FidelityFX/upscalers/fsr4/include/gpu/fsr4/post_common.hlsli`
- `Kits/FidelityFX/upscalers/fsr4/dx12/ffx_provider_fsr4_dx12.cpp`
- generated v07 I8 model pass files.

The project must continue to preserve source/license provenance and avoid redistributing assets whose redistribution has not been reviewed.

## AMD FidelityFX FSR3 source

https://github.com/GPUOpen-LibrariesAndSDKs/FidelityFX-SDK

Relevant current source:

- `ffx_fsr3upscaler_accumulate.h`
- `ffx_fsr3upscaler_reproject.h`
- `ffx_fsr3upscaler_prepare_reactivity.h`
- `ffx_fsr3upscaler_luma_instability.h`
- `ffx_fsr3upscaler_resources.h`

This demonstrates that FSR3 already calculates the temporal/reactivity/history signals Delta4 needs.

## SCNet - fully 1x1 lightweight SR with spatial shift

Paper:
https://arxiv.org/abs/2307.16140

Public repository:
https://github.com/Aitical/SCNet

Use the architectural concept through a clean-room implementation. Review repository license before copying any source.

## ClassSR - dynamic patch difficulty

CVPR 2021:
https://openaccess.thecvf.com/content/CVPR2021/html/Kong_ClassSR_A_General_Framework_to_Accelerate_Super-Resolution_Networks_by_Data_CVPR_2021_paper.html

Reported up to about 50% FLOP savings on evaluated SR backbones by routing easier image regions through smaller networks.

## Adaptive Patch Exiting

https://arxiv.org/abs/2203.11589

Important engineering point: pixel-wise sparse convolution can have poor practical speedup; patch-level exits are more hardware-friendly.

## ENAF - adaptive patch fusion / multi-exit SR

WACV 2025:
https://openaccess.thecvf.com/content/WACV2025/html/Nguyen_ENAF_A_Multi-Exit_Network_with_an_Adaptive_Patch_Fusion_for_WACV_2025_paper.html

Uses a tiny quality predictor to select early exits based on expected reconstruction quality rather than only handcrafted edge scores.

## PCSR - pixel-level adaptive SR

https://arxiv.org/abs/2407.21448

Useful as evidence that reconstruction capacity can be allocated spatially according to difficulty. GPU implementation must still remain coherent enough for actual latency gains.

## Frequency-aware dynamic SR

ICCV 2021:
https://openaccess.thecvf.com/content/ICCV2021/html/Xie_Learning_Frequency-Aware_Dynamic_Network_for_Efficient_Super-Resolution_ICCV_2021_paper.html

Processes high-frequency regions more expensively while allocating cheap operations to lower-frequency areas; reports around 50% FLOP reduction in example settings while retaining strong performance.

## Classifier Guided Temporal Supersampling

Computer Graphics Forum / Pacific Graphics 2022:
https://diglib.eg.org/items/c4ee97f2-ba2a-4d1b-b334-c0a41e218cee

White-box temporal reconstruction:
- classify occlusion/aliasing/shading-change behavior,
- learn blend weights between current and warped history,
- lower compute/memory than black-box end-to-end alternatives.

This is directly relevant to Delta4 because FSR3 already provides many of those classes/signals.

## Deep Bilateral Learning

SIGGRAPH 2017:
https://research.google/pubs/deep-bilateral-learning-for-real-time-image-enhancement/

Predicts low-resolution coefficients and reconstructs them at high resolution using edge-aware bilateral slicing. This motivates the ControlGrid oracle/architecture.

## Bilateral Grid Learning

CVPR 2021:
https://openaccess.thecvf.com/content/CVPR2021/html/Xu_Bilateral_Grid_Learning_for_Stereo_Matching_Networks_CVPR_2021_paper.html

Shows parameter-free edge-preserving slicing can lift low-resolution learned outputs to high resolution efficiently.

## Fast End-to-End Trainable Guided Filter

CVPR 2018:
https://openaccess.thecvf.com/content_cvpr_2018/html/Wu_Fast_End-to-End_Trainable_CVPR_2018_paper.html

Another low-resolution-prediction/high-resolution-guided-reconstruction reference.

## Kernel prediction / compact kernel encoding

Real-time Monte Carlo Denoising with Weight Sharing Kernel Prediction Network:
https://arxiv.org/abs/2202.05977

Shows that predicting a compact encoding of a spatial filter can materially reduce network throughput while preserving kernel-based reconstruction quality.

## Residual-guided distillation

ResKD:
https://arxiv.org/abs/2006.04719

Motivates predicting the residual knowledge gap and using adaptive inference rather than forcing one tiny model to reproduce an entire large teacher directly.

## Efficient SR distillation examples

DVMSR, CVPRW 2024:
https://openaccess.thecvf.com/content/CVPR2024W/NTIRE/html/Lei_DVMSR_Distillated_Vision_Mamba_for_Efficient_Super-Resolution_CVPRW_2024_paper.html

DIPNet, CVPRW 2023:
https://openaccess.thecvf.com/content/CVPR2023W/NTIRE/papers/Yu_DIPNet_Efficiency_Distillation_and_Iterative_Pruning_for_Image_Super-Resolution_CVPRW_2023_paper.pdf

Efficient INT8 SR deployment-aware teacher-guided training, CVPRW 2026:
https://openaccess.thecvf.com/content/CVPR2026W/MAI/html/Nguyen_Efficient_INT8_Single-Image_Super-Resolution_via_Deployment-Aware_Quantization_and_Teacher-Guided_Training_CVPRW_2026_paper.html
