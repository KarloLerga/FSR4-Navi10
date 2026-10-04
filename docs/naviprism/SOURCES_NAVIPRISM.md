# Public Sources

Microsoft HLSL msad4:
https://learn.microsoft.com/windows/win32/direct3dhlsl/dx-graphics-hlsl-msad4

The HLSL reference documents the four shifted alignments, zero-reference masking, and the 65,535 accuracy bound. The pinned example in that page is covered by `tests/test_msad4_reference.py`.

Microsoft DirectX feature improvements:
https://learn.microsoft.com/windows-hardware/drivers/display/directx-feature-improvements-in-windows-8

AMD RDNA 1.0 ISA:
https://developer.amd.com/wp-content/resources/RDNA_Shader_ISA.pdf

RGA 2.14.2.7 disassembles the Navi10-targeted `msad4` and SARM shaders to `v_mqsad_u32_u8` (quad-byte masked SAD with packed 32-bit accumulation). The same RGA run found no `v_mqsad_*_u8` instruction in the manually scalar or FP16-difference benchmark variants. These are offline compiler results for `gfx1010`; GPU timing is recorded separately in `NAVIPRISM_RESULTS.md`.

RAISR:
https://arxiv.org/abs/1606.01299
https://research.google/people/peymanmilanfar/

LeRF:
https://openaccess.thecvf.com/content/CVPR2023/html/Li_Learning_Steerable_Function_for_Efficient_Image_Resampling_CVPR_2023_paper.html
https://lerf.pages.dev/

MuLUT:
https://github.com/ddlee-cn/MuLUT

RCLUT:
https://openaccess.thecvf.com/content/ICCV2023/html/Liu_Reconstructed_Convolution_Module_Based_Look-Up_Tables_for_Efficient_Image_Super-Resolution_ICCV_2023_paper.html

HKLUT:
https://www.ijcai.org/proceedings/2024/95
https://github.com/jasonli0707/hklut

IQ-LUT:
https://arxiv.org/abs/2604.07000

AdderSR:
https://openaccess.thecvf.com/content/CVPR2021/html/Song_AdderSR_Towards_Energy_Efficient_Image_Super-Resolution_CVPR_2021_paper.html
https://github.com/huawei-noah/AdderNet

SeemoRe:
https://proceedings.mlr.press/v235/zamfir24a.html
https://eduardzamfir.github.io/seemore/

Unreal TSR:
https://dev.epicgames.com/documentation/unreal-engine/temporal-super-resolution-in-unreal-engine
https://dev.epicgames.com/documentation/unreal-engine/temporal-super-resolution-frequently-asked-questions-for-unreal-engine
