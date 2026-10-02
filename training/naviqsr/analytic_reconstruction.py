"""Differentiable AKR reference: SPD Gaussian taps, history clamp and blend."""

from __future__ import annotations

import torch
from torch.nn import functional as F


def _base_grid(width: int, height: int, device: torch.device,
               dtype: torch.dtype) -> torch.Tensor:
    ys = (torch.arange(height, device=device, dtype=dtype) + 0.5) * (2.0 / height) - 1.0
    xs = (torch.arange(width, device=device, dtype=dtype) + 0.5) * (2.0 / width) - 1.0
    gy, gx = torch.meshgrid(ys, xs, indexing="ij")
    return torch.stack((gx, gy), dim=-1)[None]


def warp_history(history_hr: torch.Tensor, motion_lr: torch.Tensor, scale: int,
                 current_jitter: torch.Tensor | None = None,
                 previous_jitter: torch.Tensor | None = None) -> torch.Tensor:
    """Warp HR history using LR-pixel motion and the documented jitter convention."""
    batch, _, height, width = history_hr.shape
    low_h, low_w = motion_lr.shape[-2:]
    motion = F.interpolate(motion_lr.float(), size=(height, width), mode="bilinear",
                           align_corners=False)
    delta = torch.zeros((batch, 2), device=history_hr.device, dtype=torch.float32)
    if current_jitter is not None and previous_jitter is not None:
        delta = previous_jitter.float() - current_jitter.float()
    flow_x = motion[:, 0] + delta[:, 0, None, None]
    flow_y = motion[:, 1] + delta[:, 1, None, None]
    grid = _base_grid(width, height, history_hr.device, torch.float32).expand(batch, -1, -1, -1).clone()
    grid[..., 0] += flow_x * (2.0 / low_w)
    grid[..., 1] += flow_y * (2.0 / low_h)
    return F.grid_sample(history_hr.float(), grid, mode="bilinear",
                         padding_mode="border", align_corners=False)


def _tap_offsets(taps: int) -> tuple[tuple[float, float], ...]:
    axial = ((1.0, 0.0), (-1.0, 0.0), (0.0, 1.0), (0.0, -1.0))
    diagonal = ((0.70710678, 0.70710678), (-0.70710678, 0.70710678),
                (0.70710678, -0.70710678), (-0.70710678, -0.70710678))
    if taps == 4:
        return axial
    if taps == 5:
        return ((0.0, 0.0),) + axial
    if taps == 8:
        return axial + diagonal
    raise ValueError("analytic reconstruction supports 4, 5, or 8 taps")


def analytic_reconstruct(lr_rgb: torch.Tensor, controls: torch.Tensor,
                         residual: torch.Tensor, scale: int,
                         history_hr: torch.Tensor | None = None,
                         motion_lr: torch.Tensor | None = None,
                         current_jitter: torch.Tensor | None = None,
                         previous_jitter: torch.Tensor | None = None,
                         history_valid: torch.Tensor | None = None,
                         reactive_lr: torch.Tensor | None = None,
                         transparency_lr: torch.Tensor | None = None,
                         taps: int = 5) -> dict[str, torch.Tensor]:
    batch, _, low_h, low_w = lr_rgb.shape
    out_h, out_w = low_h * scale, low_w * scale
    params = F.interpolate(controls.float(), size=(out_h, out_w), mode="bilinear",
                           align_corners=False)
    residual_hr = F.interpolate(residual.float(), size=(out_h, out_w), mode="bilinear",
                                align_corners=False)
    # Cholesky factors guarantee an SPD metric without predicting an angle.
    l11 = torch.exp2(params[:, 0:1].clamp(-2.0, 2.0))
    l21 = 0.5 * torch.tanh(params[:, 1:2])
    l22 = torch.exp2(params[:, 2:3].clamp(-2.0, 2.0))
    q00 = l11 * l11
    q01 = l11 * l21
    q11 = l21 * l21 + l22 * l22

    base = _base_grid(out_w, out_h, lr_rgb.device, torch.float32).expand(batch, -1, -1, -1).clone()
    samples = []
    weights = []
    for dx, dy in _tap_offsets(taps):
        energy = q00 * (dx * dx) + 2.0 * q01 * (dx * dy) + q11 * (dy * dy)
        weight = torch.exp2((-0.7213475204444817 * energy).clamp(-40.0, 0.0))
        grid = base.clone()
        grid[..., 0] += (2.0 * dx / low_w)
        grid[..., 1] += (2.0 * dy / low_h)
        sample = F.grid_sample(lr_rgb.float(), grid, mode="bilinear",
                               padding_mode="border", align_corners=False)
        samples.append(sample * weight)
        weights.append(weight)
    current = torch.stack(samples, dim=0).sum(dim=0) / torch.stack(weights, dim=0).sum(dim=0).clamp_min(1.0e-6)
    residual_gain = torch.sigmoid(params[:, 5:6]) * torch.tanh(params[:, 6:7])
    current = current + residual_hr * residual_gain * 0.1

    output = current
    warped_history = None
    history_alpha = torch.ones((batch, 1, out_h, out_w), device=current.device, dtype=current.dtype)
    if history_hr is not None and motion_lr is not None:
        warped_history = warp_history(history_hr, motion_lr, scale,
                                      current_jitter, previous_jitter)
        clip_radius = 0.02 + 0.28 * torch.sigmoid(params[:, 4:5])
        clipped_history = torch.maximum(torch.minimum(warped_history,
                                                      current + clip_radius),
                                        current - clip_radius)
        current_alpha = torch.sigmoid(params[:, 3:4])
        confidence = torch.sigmoid(params[:, 7:8])
        validity = torch.ones_like(current_alpha)
        if history_valid is not None:
            validity = F.interpolate(history_valid.float(), size=(out_h, out_w),
                                     mode="nearest")
        if reactive_lr is not None:
            validity = validity * (1.0 - F.interpolate(reactive_lr.float(),
                                                         size=(out_h, out_w), mode="bilinear",
                                                         align_corners=False).clamp(0.0, 1.0))
        if transparency_lr is not None:
            validity = validity * (1.0 - 0.8 * F.interpolate(transparency_lr.float(),
                                                              size=(out_h, out_w), mode="bilinear",
                                                              align_corners=False).clamp(0.0, 1.0))
        history_alpha = (1.0 - (1.0 - current_alpha) * confidence * validity).clamp(0.0, 1.0)
        output = current * history_alpha + clipped_history * (1.0 - history_alpha)

    return {"output": output, "current": current, "warped_history": warped_history,
            "history_alpha": history_alpha, "spd": torch.cat((q00, q01, q11), dim=1)}
