"""Reversible 2x polyphase and optional Haar feature packing."""

from __future__ import annotations

import torch
from torch import nn


def space_to_depth(x: torch.Tensor) -> torch.Tensor:
    if x.ndim != 4 or x.shape[-2] % 2 or x.shape[-1] % 2:
        raise ValueError("space_to_depth expects BCHW input with even spatial dimensions")
    return torch.pixel_unshuffle(x, 2)


def depth_to_space(x: torch.Tensor) -> torch.Tensor:
    if x.ndim != 4 or x.shape[1] % 4:
        raise ValueError("depth_to_space expects BCHW input with channels divisible by four")
    return torch.pixel_shuffle(x, 2)


def haar_polyphase(rgb: torch.Tensor) -> torch.Tensor:
    """Apply an orthonormal 4-phase Haar matrix to image channels."""
    if rgb.ndim != 4 or rgb.shape[-2] % 2 or rgb.shape[-1] % 2:
        raise ValueError("haar_polyphase expects BCHW input with even spatial dimensions")
    p00 = rgb[..., 0::2, 0::2]
    p01 = rgb[..., 0::2, 1::2]
    p10 = rgb[..., 1::2, 0::2]
    p11 = rgb[..., 1::2, 1::2]
    ll = 0.5 * (p00 + p01 + p10 + p11)
    lh = 0.5 * (p00 - p01 + p10 - p11)
    hl = 0.5 * (p00 + p01 - p10 - p11)
    hh = 0.5 * (p00 - p01 - p10 + p11)
    return torch.cat((ll, lh, hl, hh), dim=1)


def pack_features(x: torch.Tensor, mode: str = "raw",
                  learned_mixer: nn.Module | None = None) -> torch.Tensor:
    """Pack RGB phases and preserve semantic phases without Haar mixing them."""
    if x.shape[1] < 3:
        raise ValueError("NaviQSR input must begin with RGB channels")
    if mode == "raw":
        return space_to_depth(x)
    if mode == "learned1x1":
        if learned_mixer is None:
            raise ValueError("learned1x1 mode requires a learned phase mixer")
        return learned_mixer(space_to_depth(x))
    if mode != "haar":
        raise ValueError(f"unsupported polyphase mode: {mode}")
    rgb = haar_polyphase(x[:, :3])
    semantic = space_to_depth(x[:, 3:]) if x.shape[1] > 3 else None
    return rgb if semantic is None else torch.cat((rgb, semantic), dim=1)


def inverse_haar_polyphase(coefficients: torch.Tensor) -> torch.Tensor:
    if coefficients.ndim != 4 or coefficients.shape[1] % 4:
        raise ValueError("inverse Haar expects BCHW with four phase bands per channel")
    channels = coefficients.shape[1] // 4
    ll, lh, hl, hh = coefficients.split(channels, dim=1)
    p00 = 0.5 * (ll + lh + hl + hh)
    p01 = 0.5 * (ll - lh + hl - hh)
    p10 = 0.5 * (ll + lh - hl - hh)
    p11 = 0.5 * (ll - lh - hl + hh)
    output = coefficients.new_empty((coefficients.shape[0], channels,
                                     coefficients.shape[2] * 2,
                                     coefficients.shape[3] * 2))
    output[..., 0::2, 0::2] = p00
    output[..., 0::2, 1::2] = p01
    output[..., 1::2, 0::2] = p10
    output[..., 1::2, 1::2] = p11
    return output
