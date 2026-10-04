"""Fold and pack a trained NaviQSR checkpoint as true FP16 tensors."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
import sys
from pathlib import Path

import numpy as np
import torch

try:
    from .blocks import fold_model
    from .model import NaviQSRNetwork
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from training.naviqsr.blocks import fold_model
    from training.naviqsr.model import NaviQSRNetwork


MAGIC = b"NQSRPK1\0"
PREFIX = struct.Struct("<8sII")
ALIGNMENT = 16


def _align(value: int) -> int:
    return (value + ALIGNMENT - 1) & ~(ALIGNMENT - 1)


def export_checkpoint(checkpoint_path: Path, output_path: Path,
                      fold_tolerance: float = 2.0e-5) -> dict[str, object]:
    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
    if checkpoint.get("format") != "naviqsr-checkpoint-v1":
        raise ValueError("unsupported NaviQSR checkpoint format")
    config = checkpoint["model_config"]
    model = NaviQSRNetwork(
        input_channels=int(config["input_channels"]), width=int(config["width"]),
        blocks=int(config["blocks"]), hf_width=int(config["hf_width"]),
        polyphase_mode=str(config["polyphase_mode"]))
    model.load_state_dict(checkpoint["model_state"], strict=True)
    model.eval()
    folded = fold_model(model).eval()
    height, width = 24, 32
    generator = torch.Generator(device="cpu").manual_seed(5700)
    probe = torch.randn((1, int(config["input_channels"]), height, width),
                        generator=generator)
    with torch.no_grad():
        reference = model(probe)
        folded_result = folded(probe)
        fold_error = max(float((reference[key] - folded_result[key]).abs().max())
                         for key in ("controls", "residual"))
    if not math.isfinite(fold_error) or fold_error > fold_tolerance:
        raise RuntimeError(f"structural fold error {fold_error:.8g} exceeds {fold_tolerance:.8g}")

    tensor_records = []
    payload = bytearray()
    for name, tensor in sorted(folded.state_dict().items()):
        values = tensor.detach().cpu().numpy().astype("<f2", copy=False)
        encoded = values.tobytes(order="C")
        aligned_offset = _align(len(payload))
        payload.extend(b"\0" * (aligned_offset - len(payload)))
        payload.extend(encoded)
        tensor_records.append({"name": name, "shape": list(values.shape),
                               "dtype": "float16", "layout": "contiguous",
                               "offset": aligned_offset, "nbytes": len(encoded),
                               "sha256": hashlib.sha256(encoded).hexdigest()})

    header = {
        "format": "NaviQSRModelPack",
        "version": 1,
        "architecture": {**config, "folded": True,
                          "fold_form": "residual_rep3x3",
                          "fp16_storage": True,
                          "polyphase_stride": 2,
                          "analytic_controls": ["s0", "s1", "s2", "alpha_logit",
                                                "clamp_logit", "residual_gate_logit",
                                                "detail_gain", "history_confidence"]},
        "training": checkpoint.get("training", {}),
        "fold_max_abs_error_fp32": fold_error,
        "alignment": ALIGNMENT,
        "payload_bytes": len(payload),
        "tensors": tensor_records,
    }
    encoded_header = json.dumps(header, sort_keys=True, separators=(",", ":")).encode("utf-8")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(PREFIX.pack(MAGIC, 1, len(encoded_header)) + encoded_header + payload)
    pack_hash = hashlib.sha256(output_path.read_bytes()).hexdigest()
    manifest = {"pack": output_path.name, "sha256": pack_hash,
                "size_bytes": output_path.stat().st_size, "header": header}
    manifest_path = output_path.with_suffix(output_path.suffix + ".json")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return {"pack": str(output_path), "sha256": pack_hash,
            "manifest": str(manifest_path), "size_bytes": output_path.stat().st_size,
            "tensor_count": len(tensor_records), "fold_max_abs_error_fp32": fold_error}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fold-tolerance", type=float, default=2.0e-5)
    args = parser.parse_args()
    print(json.dumps(export_checkpoint(args.checkpoint, args.output,
                                       args.fold_tolerance), indent=2))


if __name__ == "__main__":
    main()
