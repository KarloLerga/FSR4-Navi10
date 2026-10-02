"""Train-time over-parameterized blocks and inference folding."""

from __future__ import annotations

import torch
from torch import nn
from torch.nn import functional as F


class ReparamBlock(nn.Module):
    """Linear 1x1 -> 3x3 -> 1x1 chain with only one final activation."""

    def __init__(self, channels: int, expansion: int | None = None):
        super().__init__()
        hidden = expansion or channels
        self.conv1 = nn.Conv2d(channels, hidden, 1, bias=True)
        self.conv2 = nn.Conv2d(hidden, channels, 3, padding=1,
                               padding_mode="replicate", bias=True)
        self.conv3 = nn.Conv2d(channels, channels, 1, bias=True)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return F.relu(x + self.conv3(self.conv2(self.conv1(x))))


class FoldedResidualBlock(nn.Module):
    """Equivalent single spatial convolution plus the residual identity."""

    def __init__(self, convolution: nn.Conv2d):
        super().__init__()
        self.conv = convolution

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return F.relu(x + self.conv(x))


def fold_reparam_block(block: ReparamBlock) -> FoldedResidualBlock:
    """Compose the three linear kernels and biases, then add the identity."""
    if block.conv1.kernel_size != (1, 1) or block.conv2.kernel_size != (3, 3) \
            or block.conv3.kernel_size != (1, 1):
        raise ValueError("expected a 1x1 -> 3x3 -> 1x1 reparameterization block")
    if block.conv1.in_channels != block.conv3.out_channels:
        raise ValueError("residual fold requires equal input/output channels")
    device = block.conv1.weight.device
    dtype = block.conv1.weight.dtype
    w1 = block.conv1.weight[:, :, 0, 0]
    w2 = block.conv2.weight
    w3 = block.conv3.weight[:, :, 0, 0]
    kernel = torch.einsum("on,nmxy,mi->oixy", w3, w2, w1)
    b1 = block.conv1.bias
    b2 = block.conv2.bias
    b3 = block.conv3.bias
    b2_folded = torch.einsum("nmxy,m->n", w2, b1) + b2
    bias = w3 @ b2_folded + b3
    convolution = nn.Conv2d(block.conv1.in_channels, block.conv3.out_channels,
                            3, padding=1, padding_mode="replicate", bias=True)
    convolution = convolution.to(device=device, dtype=dtype)
    with torch.no_grad():
        convolution.weight.copy_(kernel)
        convolution.bias.copy_(bias)
    convolution.train(block.training)
    return FoldedResidualBlock(convolution)


def fold_model(model: nn.Module) -> nn.Module:
    """Replace each training chain with a single equivalent 3x3 operation."""
    folded = __import__("copy").deepcopy(model)
    if not hasattr(folded, "blocks"):
        raise ValueError("model has no reparameterizable blocks")
    folded.blocks = nn.Sequential(*(fold_reparam_block(block) for block in folded.blocks))
    return folded
