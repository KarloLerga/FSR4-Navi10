"""Numerically verify foldable NaviQSR blocks before model-pack export."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from training.naviqsr.blocks import fold_model
from training.naviqsr.model import NaviQSRNetwork


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--tolerance", type=float, default=2.0e-5)
    args = parser.parse_args()
    checkpoint = torch.load(args.checkpoint, map_location="cpu", weights_only=True)
    config = checkpoint["model_config"]
    model = NaviQSRNetwork(input_channels=int(config["input_channels"]),
                           width=int(config["width"]), blocks=int(config["blocks"]),
                           hf_width=int(config["hf_width"]),
                           polyphase_mode=str(config["polyphase_mode"]))
    model.load_state_dict(checkpoint["model_state"], strict=True)
    model.eval()
    folded = fold_model(model).eval()
    probe = torch.randn((1, int(config["input_channels"]), 32, 40),
                        generator=torch.Generator().manual_seed(5700))
    with torch.no_grad():
        original = model(probe)
        result = folded(probe)
    errors = {name: float((original[name] - result[name]).abs().max())
              for name in ("controls", "residual")}
    passed = max(errors.values()) <= args.tolerance
    print(json.dumps({"max_abs_error": errors, "tolerance": args.tolerance,
                      "passed": passed}, indent=2))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
