"""Evaluate a checkpoint on temporal sequences and save metrics/images."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import torch
from torch.nn import functional as F
from PIL import Image

try:
    from .analytic_reconstruction import analytic_reconstruct, warp_history
    from .train import _features, _frame_tensor, _load_sequences
    from .model import NaviQSRnetwork
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from training.naviqsr.analytic_reconstruction import analytic_reconstruct, warp_history
    from training.naviqsr.train import _features, _frame_tensor, _load_sequences
    from training.naviqsr.model import NaviQSRnetwork


def _psnr(output: torch.Tensor, target: torch.Tensor) -> float:
    mse = torch.mean((output.float() - target.float()) ** 2).item()
    return float("inf") if mse == 0.0 else -10.0 * float(np.log10(mse))


def _global_ssim(output: torch.Tensor, target: torch.Tensor) -> float:
    x, y = output.float(), target.float()
    mu_x, mu_y = x.mean(), y.mean()
    var_x, var_y = x.var(unbiased=False), y.var(unbiased=False)
    covariance = ((x - mu_x) * (y - mu_y)).mean()
    peak = max(1.0, float(target.max().item()))
    c1, c2 = (0.01 * peak) ** 2, (0.03 * peak) ** 2
    value = ((2 * mu_x * mu_y + c1) * (2 * covariance + c2)
             / ((mu_x.square() + mu_y.square() + c1) * (var_x + var_y + c2)))
    return float(value.item())


def _save_preview(tensor: torch.Tensor, path: Path) -> None:
    image = tensor[0].detach().cpu().permute(1, 2, 0).numpy().astype(np.float32)
    # A fixed monotonic preview curve; metrics are computed on the untouched linear data.
    display = np.clip(image / (1.0 + np.maximum(image, 0.0)), 0.0, 1.0)
    display = np.power(display, 1.0 / 2.2)
    Image.fromarray(np.uint8(np.clip(display * 255.0 + 0.5, 0, 255))).save(path)


def validate(checkpoint_path: Path, dataset_root: Path,
             output_root: Path, taps: int = 5) -> dict[str, object]:
    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
    cfg = checkpoint["model_config"]
    model = NaviQSRnetwork(input_channels=int(cfg["input_channels"]),
                           width=int(cfg["width"]), blocks=int(cfg["blocks"]),
                           hf_width=int(cfg["hf_width"]),
                           polyphase_mode=str(cfg["polyphase_mode"]))
    model.load_state_dict(checkpoint["model_state"], strict=True)
    model.eval()
    output_root.mkdir(parents=True, exist_ok=True)
    records = []
    with torch.no_grad():
        for sequence_index, sequence in enumerate(_load_sequences(dataset_root)):
            previous_output = None
            previous_jitter = None
            temporal_error = []
            outputs = []
            for frame in range(sequence["lr_rgb"].shape[0]):
                features = _features(sequence, frame, torch.device("cpu"))
                target = _frame_tensor(sequence["hr_rgb"][frame], torch.device("cpu"))
                motion = _frame_tensor(sequence["motion"][frame], torch.device("cpu"))
                reactive = _frame_tensor(sequence["reactive"][frame], torch.device("cpu"))
                transparency = _frame_tensor(sequence["transparency"][frame], torch.device("cpu"))
                jitter = torch.as_tensor(sequence["jitter"][frame], dtype=torch.float32)[None]
                reset = bool(sequence["reset"][frame])
                valid = torch.full_like(reactive, 0.0 if reset else 1.0)
                history = torch.zeros_like(target) if reset or previous_output is None else previous_output
                prior_jitter = jitter if reset or previous_jitter is None else previous_jitter
                prediction = model(features)
                result = analytic_reconstruct(
                    features[:, :3], prediction["controls"], prediction["residual"],
                    int(sequence["scale"]), history_hr=history, motion_lr=motion,
                    current_jitter=jitter, previous_jitter=prior_jitter,
                    history_valid=valid, reactive_lr=reactive,
                    transparency_lr=transparency, taps=taps)
                output = result["output"]
                bilinear = F.interpolate(features[:, :3].float(), size=target.shape[-2:],
                                         mode="bilinear", align_corners=False)
                psnr = _psnr(output, target)
                ssim = _global_ssim(output, target)
                record = {"sequence": sequence_index, "frame": frame,
                          "reset": reset, "psnr_db": psnr, "global_ssim": ssim,
                          "bilinear_psnr_db": _psnr(bilinear, target),
                          "bilinear_global_ssim": _global_ssim(bilinear, target)}
                if not reset and previous_output is not None:
                    warped = warp_history(previous_output, motion, int(sequence["scale"]),
                                          jitter, prior_jitter)
                    previous_gt = _frame_tensor(sequence["hr_rgb"][frame - 1], torch.device("cpu"))
                    warped_gt = warp_history(previous_gt, motion, int(sequence["scale"]),
                                             jitter, prior_jitter)
                    valid_mask = F.interpolate((1.0 - reactive).clamp(0, 1),
                                               size=output.shape[-2:], mode="nearest")
                    err = (((output - warped) - (target - warped_gt)).abs()
                           * valid_mask).sum() / (valid_mask.sum() * 3.0).clamp_min(1.0)
                    record["temporal_warp_error"] = float(err)
                    temporal_error.append(float(err))
                records.append(record)
                outputs.append(output.cpu().numpy()[0].transpose(1, 2, 0).astype(np.float16))
                _save_preview(output, output_root / f"sequence_{sequence_index:03d}_frame_{frame:04d}.png")
                previous_output = output
                previous_jitter = jitter
            np.save(output_root / f"sequence_{sequence_index:03d}_output.npy",
                    np.stack(outputs), allow_pickle=False)
    values = [item for item in records if "psnr_db" in item]
    summary = {
        "checkpoint": str(checkpoint_path), "dataset": str(dataset_root),
        "frames": len(records),
        "mean_psnr_db": float(np.mean([item["psnr_db"] for item in values])),
        "mean_global_ssim": float(np.mean([item["global_ssim"] for item in values])),
        "bilinear_mean_psnr_db": float(np.mean([item["bilinear_psnr_db"] for item in values])),
        "bilinear_mean_global_ssim": float(np.mean([item["bilinear_global_ssim"] for item in values])),
        "mean_temporal_warp_error": (float(np.mean(temporal_error)) if temporal_error else None),
        "metrics_scope": "procedural temporal data; global SSIM is an image-level summary, not a local-window SSIM implementation",
        "frames_detail": records,
    }
    (output_root / "validation.json").write_text(json.dumps(summary, indent=2) + "\n",
                                                 encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--taps", type=int, choices=(4, 5, 8), default=5)
    args = parser.parse_args()
    print(json.dumps(validate(args.checkpoint, args.dataset, args.output, args.taps), indent=2))


if __name__ == "__main__":
    main()
