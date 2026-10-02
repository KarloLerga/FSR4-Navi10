# NaviQSR training and reference tools

This directory contains a PyTorch reference for the separately named NaviQSR network. It is not yet the D3D12 runtime and does not replace the full FSR4 path. The synthetic sequence renderer provides deterministic ground truth and exact analytic motion for its simple 2D layers. It is a stress/correctness dataset, not a substitute for captured game content.

## Setup

From the repository root, create an isolated Python 3.11 environment and install the pinned CPU stack:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r training/naviqsr/requirements.txt
```

Backend selection prefers CUDA when available, then DirectML if `torch-directml` is installed and passes an operator smoke, then CPU. This project does not assume Windows ROCm support for the RX 5700 XT.

## Procedural sequence, training, validation, and export

```powershell
.\.venv\Scripts\python.exe -m training.naviqsr.datasets.procedural --output build/naviqsr/procedural --sequences 4 --frames 8 --width 64 --height 36 --scale 2 --seed 1
.\.venv\Scripts\python.exe -m training.naviqsr.train --dataset build/naviqsr/procedural --output build/naviqsr/training --steps 64 --backend auto
.\.venv\Scripts\python.exe -m training.naviqsr.validate --checkpoint build/naviqsr/training/naviqsr_checkpoint.pt --dataset build/naviqsr/procedural --output build/naviqsr/validation
.\.venv\Scripts\python.exe tools/naviqsr/fold_reparam.py --checkpoint build/naviqsr/training/naviqsr_checkpoint.pt
.\.venv\Scripts\python.exe tools/naviqsr/build_model_pack.py --checkpoint build/naviqsr/training/naviqsr_checkpoint.pt --output build/naviqsr/model.nqsrpack
.\.venv\Scripts\python.exe tools/naviqsr/validate_model_pack.py build/naviqsr/model.nqsrpack
```

The pack stores contiguous FP16 tensors, 16-byte-aligned offsets, per-tensor hashes, architecture/control metadata, and a sidecar SHA-256. The exporter folds the 1x1 → 3x3 → 1x1 chain and checks FP32 output equivalence first. This is not proof of FP16 image-quality equivalence; the D3D12 loader, GPU dispatch, generated ISA audit, teacher features, and RX 5700 XT measurements remain separate acceptance gates.

`validation.json` reports linear-light PSNR, a global image-level SSIM summary, and motion-warp temporal error on the procedural sequence. It also writes PNG previews and FP16 NPY frames. It does not report FLIP/LPIPS or FSR4 teacher comparison.

The first 256-update smoke evaluated on its training data, so its 21.0118 dB PSNR result is in-sample only. The follow-up used independent procedural seeds: 8x8 training frames with seed 17, 4x8 holdout frames with seed 9001, and 4,096 CPU updates. The 32-frame holdout scored 21.0219 dB mean PSNR versus 20.9377 dB for bilinear, and 0.70981 mean global SSIM versus 0.70928. The 0.0842 dB PSNR gain is not a meaningful quality result and the synthetic set does not represent game content. DirectML was unavailable.

Reproduce the independent-seed run with:

```powershell
.\.venv\Scripts\python.exe -m training.naviqsr.datasets.procedural --output build/naviqsr/holdout-train-data --sequences 8 --frames 8 --width 32 --height 18 --scale 2 --seed 17
.\.venv\Scripts\python.exe -m training.naviqsr.datasets.procedural --output build/naviqsr/holdout-val-data --sequences 4 --frames 8 --width 32 --height 18 --scale 2 --seed 9001
.\.venv\Scripts\python.exe -m training.naviqsr.train --dataset build/naviqsr/holdout-train-data --output build/naviqsr/holdout-train --steps 4096 --backend cpu --width-channels 8 --blocks 1 --hf-width 4 --cpu-threads 4 --log-every 1024
.\.venv\Scripts\python.exe -m training.naviqsr.validate --checkpoint build/naviqsr/holdout-train/naviqsr_checkpoint.pt --dataset build/naviqsr/holdout-val-data --output build/naviqsr/holdout-validation
```

## Analytic reconstruction D3D12 smoke

Export one case from the trained checkpoint and run the analytic reconstruction shader on the RX 5700 XT:

```powershell
.\.venv\Scripts\python.exe tools/naviqsr/export_gpu_case.py --checkpoint build/naviqsr/training/naviqsr_checkpoint.pt --dataset build/naviqsr/procedural --output build/naviqsr/parity-5tap.nqsrtest --sequence 0 --frame 1 --taps 5
build/release/fsr4n10_harness.exe --run-naviqsr-analytic-gpu build/naviqsr/parity-5tap.nqsrtest
```

Repeat with `--taps 4` or `--taps 8` to select the other compiled variants. The harness checks one small output against the PyTorch analytic reference and reports 5 warmups plus 20 timestamped dispatch measurements, GPU/driver ID, and DXIL hash. The measurement excludes the PyTorch network convolutions and all frame-graph work. The remaining GPU/reference error is small but nonzero; it is not bit-exact parity.

## network convolution D3D12 smoke

Export the trained raw-polyphase network layers and compare GPU controls/residuals against the FP16-quantized folded PyTorch reference:

```powershell
.\.venv\Scripts\python.exe tools/naviqsr/export_network_gpu_case.py --checkpoint build/naviqsr/holdout-train/naviqsr_checkpoint.pt --dataset build/naviqsr/holdout-train-data --output build/naviqsr/network.nqsrframe --sequence 0 --frame 1
build/release/fsr4n10_harness.exe --run-naviqsr-network-gpu build/naviqsr/network.nqsrframe
```

All 9 convolution/pool-concat layers run on the RX 5700 XT with the checkpoint weights stored as FP16. Activations and accumulation use FP32; the harness reports GPU timestamps for the network graph after 5 warmups and 20 measured runs. Preprocessing and phase packing are done by the CPU case exporter. The GPU smoke currently reads the custom `.nqsrframe` case; it does not load the production `.nqsrpack` directly or join network inference with AKR and RGB output.

## QRISP and teacher captures

The local QRISP importer reads PNG/EXR modalities from a user-prepared manifest. It never downloads the data or accepts terms; see [QRISP_IMPORT.md](../../docs/naviqsr/QRISP_IMPORT.md). Teacher NPZ capture bundles can be schema/hash-checked with `training.naviqsr.datasets.captured_teacher`; the current FSR4 harness still lacks teacher output/intermediate capture hooks. The network convolution and analytic reconstruction GPU smokes are separate; their control tensors are currently exchanged through a CPU-generated test case, not a joined frame graph.
