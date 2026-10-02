"""Low-spatial NaviQSR network reference model."""

from __future__ import annotations

import torch
from torch import nn

from .blocks import ReparamBlock
from .polyphase import pack_features


class NaviQSRnetwork(nn.Module):
    """LF trunk, shallow HF branch, and compact AKR control/residual heads."""

    def __init__(self, input_channels: int = 11, width: int = 24,
                 blocks: int = 4, hf_width: int = 8,
                 polyphase_mode: str = "raw"):
        super().__init__()
        if input_channels < 3 or width < 4 or blocks < 1 or hf_width < 2:
            raise ValueError("invalid NaviQSR topology")
        if polyphase_mode not in {"raw", "haar", "learned1x1"}:
            raise ValueError(f"unsupported polyphase mode: {polyphase_mode}")
        self.input_channels = input_channels
        self.width = width
        self.block_count = blocks
        self.hf_width = hf_width
        self.polyphase_mode = polyphase_mode
        packed_channels = input_channels * 4
        self.phase_mixer = (nn.Conv2d(packed_channels, packed_channels, 1)
                            if polyphase_mode == "learned1x1" else None)
        self.stem = nn.Conv2d(packed_channels, width, 3, padding=1,
                              padding_mode="replicate")
        self.blocks = nn.Sequential(*(ReparamBlock(width) for _ in range(blocks)))
        self.hf_stem = nn.Sequential(
            nn.Conv2d(input_channels, hf_width, 3, padding=1, padding_mode="replicate"),
            nn.ReLU(inplace=False),
            nn.Conv2d(hf_width, hf_width, 3, padding=1, padding_mode="replicate"),
            nn.ReLU(inplace=False),
        )
        self.merge = nn.Conv2d(width + hf_width, width, 1)
        self.control_head = nn.Conv2d(width, 8, 1)
        self.residual_head = nn.Conv2d(width, 3, 1)
        nn.init.zeros_(self.control_head.weight)
        nn.init.zeros_(self.control_head.bias)
        with torch.no_grad():
            self.control_head.bias.copy_(torch.tensor(
                [1.0, 0.0, 1.0, 1.5, -1.0, -2.0, 0.0, 2.0],
                dtype=self.control_head.bias.dtype))
        nn.init.zeros_(self.residual_head.weight)
        nn.init.zeros_(self.residual_head.bias)

    def forward(self, features: torch.Tensor) -> dict[str, torch.Tensor]:
        if features.ndim != 4 or features.shape[1] != self.input_channels:
            raise ValueError(f"expected BCHW with {self.input_channels} channels")
        if features.shape[-2] % 2 or features.shape[-1] % 2:
            raise ValueError("input width and height must be divisible by two")
        packed = pack_features(features, self.polyphase_mode, self.phase_mixer)
        lf = self.blocks(self.stem(packed))
        hf = self.hf_stem(features)
        hf = torch.nn.functional.avg_pool2d(hf, kernel_size=2, stride=2)
        merged = self.blocks(self.merge(torch.cat((lf, hf), dim=1)))
        return {"controls": self.control_head(merged),
                "residual": self.residual_head(merged)}

    def config(self) -> dict[str, int | str]:
        return {"input_channels": self.input_channels, "width": self.width,
                "blocks": self.block_count, "hf_width": self.hf_width,
                "polyphase_mode": self.polyphase_mode, "control_channels": 8,
                "residual_channels": 3}
