"""Reconstruction, edge, and temporally warped objectives."""

from __future__ import annotations

import torch
from torch.nn import functional as F

from .analytic_reconstruction import warp_history


def charbonnier(prediction: torch.Tensor, target: torch.Tensor,
                epsilon: float = 1.0e-3) -> torch.Tensor:
    return torch.sqrt((prediction.float() - target.float()).square() + epsilon * epsilon).mean()


def gradient_loss(prediction: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
    px = prediction[..., :, 1:] - prediction[..., :, :-1]
    py = prediction[..., 1:, :] - prediction[..., :-1, :]
    tx = target[..., :, 1:] - target[..., :, :-1]
    ty = target[..., 1:, :] - target[..., :-1, :]
    return F.l1_loss(px.float(), tx.float()) + F.l1_loss(py.float(), ty.float())


def temporal_warp_loss(current_output: torch.Tensor, previous_output: torch.Tensor,
                       current_target: torch.Tensor, previous_target: torch.Tensor,
                       motion_lr: torch.Tensor, scale: int,
                       current_jitter: torch.Tensor, previous_jitter: torch.Tensor,
                       valid_lr: torch.Tensor) -> torch.Tensor:
    warped_output = warp_history(previous_output, motion_lr, scale,
                                 current_jitter, previous_jitter)
    warped_target = warp_history(previous_target, motion_lr, scale,
                                 current_jitter, previous_jitter)
    valid = F.interpolate(valid_lr.float(), size=current_output.shape[-2:],
                           mode="nearest").clamp(0.0, 1.0)
    denominator = (valid.sum() * current_output.shape[1]).clamp_min(1.0)
    error = ((current_output.float() - warped_output)
             - (current_target.float() - warped_target)).abs()
    return (error * valid).sum() / denominator


def total_loss(output: torch.Tensor, target: torch.Tensor,
               previous_output: torch.Tensor | None = None,
               previous_target: torch.Tensor | None = None,
               motion_lr: torch.Tensor | None = None, scale: int = 2,
               current_jitter: torch.Tensor | None = None,
               previous_jitter: torch.Tensor | None = None,
               valid_lr: torch.Tensor | None = None,
               teacher_target: torch.Tensor | None = None) -> tuple[torch.Tensor, dict[str, float]]:
    reconstruction = charbonnier(output, target)
    edges = gradient_loss(output, target)
    temporal = output.new_zeros(())
    if (previous_output is not None and previous_target is not None
            and motion_lr is not None and current_jitter is not None
            and previous_jitter is not None and valid_lr is not None):
        temporal = temporal_warp_loss(output, previous_output, target,
                                      previous_target, motion_lr, scale,
                                      current_jitter, previous_jitter, valid_lr)
    teacher = (charbonnier(output, teacher_target)
               if teacher_target is not None else output.new_zeros(()))
    total = reconstruction + 0.12 * edges + 0.20 * temporal + 0.10 * teacher
    return total, {"reconstruction": float(reconstruction.detach()),
                   "gradient": float(edges.detach()), "temporal": float(temporal.detach()),
                   "teacher": float(teacher.detach()), "total": float(total.detach())}
