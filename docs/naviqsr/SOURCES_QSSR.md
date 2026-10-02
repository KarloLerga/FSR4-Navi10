# Sources for QSSR / NaviQSR Addendum

These are public research/technical sources used to derive the addendum.

## Sony / QSSR

### Sony official QSSR announcement (2026-10-01)
https://blog.playstation.com/2026/10/01/ai-upscaling-is-coming-to-ps5/
Key public statements:
- Quick Spectral Super Resolution (QSSR)
- Project Amethyst collaboration with AMD
- streamlined neural network architecture
- hand-tuned PS5 implementation
- improved detail and temporal stability

### Digital Foundry QSSR article URL
https://www.digitalfoundry.net/news/2026/10/hands-on-with-qssr-ai-driven-upscaling-for-the-standard-ps5
The site was not directly fetchable in the research environment, so performance/FP16 quotations were cross-checked via current mirrors/reporting. Treat the 1.5–1.8 ms result as *extra cost versus Insomniac's prior upscaler*, not total QSSR runtime.

### PS5 official specs
https://blog.playstation.com/2020/11/09/ps5-the-ultimate-faq/
- RDNA2-based GPU
- 10.3 TFLOPS
- 448 GB/s

### RX 5700 XT official AMD specs
https://www.amd.com/en/support/downloads/drivers.html/graphics/radeon-rx/radeon-rx-5000-series/amd-radeon-rx-5700-xt.html
- 9.75 TFLOPS FP32
- 19.51 TFLOPS FP16
- 448 GB/s

---

## Sony efficient super-resolution research

### Sony patent — Image Upscaling Apparatus and Method
https://patents.justia.com/patent/20250005708
Application 20250005708
Inventor: Marcos Conde
Important:
- inverse pixel shuffle
- reduced-spatial deep features
- separate LF/HF branches
- ~75% deep-convolution cost reduction in illustrated half-width/half-height case
- inference structural re-parameterization 1x1 -> 3x3 -> 1x1 to one 3x3

### CVPRW 2023 — Towards Real-Time 4K Image Super-Resolution
https://openaccess.thecvf.com/content/CVPR2023W/NTIRE/html/Zamfir_Towards_Real-Time_4K_Image_Super-Resolution_CVPRW_2023_paper.html
PDF:
https://openaccess.thecvf.com/content/CVPR2023W/NTIRE/papers/Zamfir_Towards_Real-Time_4K_Image_Super-Resolution_CVPRW_2023_paper.pdf
Code:
https://github.com/eduardzamfir/RT4KSR

---

## Temporal feature reuse / sparse CNN

### ReFrame — ICML 2025
https://proceedings.mlr.press/v267/liu25a.html
Project/code:
https://ubc-aamodt-group.github.io/reframe-layer-caching/
Reported average ~1.4x; individual supersampling cases up to ~1.85x depending caching policy.

### MotionDeltaCNN — ICCV 2023
https://openaccess.thecvf.com/content/ICCV2023/html/Parger_MotionDeltaCNN_Sparse_CNN_Inference_of_Frame_Differences_in_Moving_Camera_ICCV_2023_paper.html
Paper:
https://openaccess.thecvf.com/content/ICCV2023/papers/Parger_MotionDeltaCNN_Sparse_CNN_Inference_of_Frame_Differences_in_Moving_Camera_ICCV_2023_paper.pdf

---

## Gaming neural supersampling

### Efficient Neural Supersampling on a Novel Gaming Dataset — ICCV 2023
https://openaccess.thecvf.com/content/ICCV2023/html/Mercier_Efficient_Neural_Supersampling_on_a_Novel_Gaming_Dataset_ICCV_2023_paper.html
PDF:
https://openaccess.thecvf.com/content/ICCV2023/papers/Mercier_Efficient_Neural_Supersampling_on_a_Novel_Gaming_Dataset_ICCV_2023_paper.pdf
Key:
- 4x efficiency claim vs prior approaches at similar accuracy
- motion/depth
- depth-informed motion dilation
- recurrent history
- jitter-conditioned convolution

### QRISP dataset
https://www.qualcomm.com/developer/software/qualcomm-rasterized-images-dataset
Research-use dataset license; do not auto-accept terms.

---

## Neural-guided analytic reconstruction inspiration

### Intel patent — Temporally Amortized Supersampling in Graphics Processing
https://patents.justia.com/patent/20260099895
Important public idea:
- network-guided analytic spatial filter
- anisotropic Gaussian example with 3 parameters
- warped history
- pixel-unshuffle / autoencoder / pixel-shuffle
- temporal blend

This project must not imply Intel endorsed or contributed to NaviQSR.

---

## AMD / RDNA1 implementation

### AMD RDNA Performance Guide
https://gpuopen.com/learn/rdna-performance-guide/
Important:
- true 16-bit types with DXC `-enable-16bit-types`
- packed FP16 considerations
- reduce memory traffic / barriers
- wave and occupancy considerations

### RDNA1 ISA
https://gpuopen.com/wp-content/uploads/2019/08/RDNA_Shader_ISA_7July2019.pdf

---

## FSR4 reverse/reference research

### FSR4 4.0.2 reference mirror used only for architecture research
https://github.com/Rolaand-Jayz/FSR-4.0.2-reference

### RDNA optimization research
https://github.com/lhl/fsr4-rdna3-optimization

Use only source/assets that are lawfully available to the user/project. Do not add unauthorized binaries or bypass signatures/licensing.
