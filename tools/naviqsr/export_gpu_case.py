"""Export one deterministic CPU network/AKR frame for D3D12 shader parity testing."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from training.naviqsr.analytic_reconstruction import analytic_reconstruct
from training.naviqsr.model import NaviQSRNetwork
from training.naviqsr.train import _features, _frame_tensor, _load_sequences


MAGIC = b"NQSRCASE"
HEADER = struct.Struct("<8sIIIIIffff")


def _rgba(array: np.ndarray) -> np.ndarray:
    height, width, channels = array.shape
    output = np.zeros((height, width, 4), dtype=np.float32)
    output[..., :channels] = array.astype(np.float32)
    if channels == 1:
        output[..., 1:3] = output[..., 0:1]
    output[..., 3] = 1.0
    return output


def export_case(checkpoint_path: Path, dataset_root: Path, output_path: Path,
                sequence_index: int, frame_index: int, taps: int) -> dict[str, object]:
    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
    config = checkpoint["model_config"]
    model = NaviQSRNetwork(input_channels=int(config["input_channels"]),
                           width=int(config["width"]), blocks=int(config["blocks"]),
                           hf_width=int(config["hf_width"]),
                           polyphase_mode=str(config["polyphase_mode"]))
    model.load_state_dict(checkpoint["model_state"], strict=True)
    model.eval()
    sequences = _load_sequences(dataset_root)
    if sequence_index < 0 or sequence_index >= len(sequences):
        raise ValueError("sequence index is outside the dataset")
    sequence = sequences[sequence_index]
    if frame_index < 0 or frame_index >= sequence["lr_rgb"].shape[0]:
        raise ValueError("frame index is outside the selected sequence")

    previous_output = None
    previous_jitter = None
    selected = None
    with torch.no_grad():
        for index in range(frame_index + 1):
            features = _features(sequence, index, torch.device("cpu"))
            target = _frame_tensor(sequence["hr_rgb"][index], torch.device("cpu"))
            motion = _frame_tensor(sequence["motion"][index], torch.device("cpu"))
            reactive = _frame_tensor(sequence["reactive"][index], torch.device("cpu"))
            transparency = _frame_tensor(sequence["transparency"][index], torch.device("cpu"))
            jitter = torch.as_tensor(sequence["jitter"][index], dtype=torch.float32)[None]
            reset = bool(sequence["reset"][index])
            valid_value = 0.0 if reset else 1.0
            valid = torch.full_like(reactive, valid_value)
            history = torch.zeros_like(target) if reset or previous_output is None else previous_output
            prior_jitter = jitter if reset or previous_jitter is None else previous_jitter
            prediction = model(features)
            result = analytic_reconstruct(
                features[:, :3], prediction["controls"], prediction["residual"],
                int(sequence["scale"]), history_hr=history, motion_lr=motion,
                current_jitter=jitter, previous_jitter=prior_jitter,
                history_valid=valid, reactive_lr=reactive,
                transparency_lr=transparency, taps=taps)
            previous_output = result["output"]
            previous_jitter = jitter
            selected = {"features": features, "prediction": prediction,
                        "target": target, "motion": motion,
                        "reactive": reactive, "transparency": transparency,
                        "history": history, "output": result["output"],
                        "jitter": jitter, "previous_jitter": prior_jitter,
                        "valid": valid, "scale": int(sequence["scale"])}
    assert selected is not None

    def hwc(tensor: torch.Tensor, channels: slice | None = None) -> np.ndarray:
        value = tensor[0] if tensor.ndim == 4 else tensor
        if channels is not None:
            value = value[channels]
        return np.ascontiguousarray(value.detach().cpu().float().permute(1, 2, 0).numpy(),
                                    dtype=np.float32)

    controls = hwc(selected["prediction"]["controls"])
    controls_a = _rgba(controls[..., :4])
    controls_b = _rgba(controls[..., 4:8])
    current = _rgba(hwc(selected["features"][:, :3]))
    residual = _rgba(hwc(selected["prediction"]["residual"]))
    history = _rgba(hwc(selected["history"]))
    motion = np.ascontiguousarray(hwc(selected["motion"]), dtype=np.float32)
    reactive = hwc(selected["reactive"])[..., 0]
    transparency = hwc(selected["transparency"])[..., 0]
    validity = np.full_like(reactive, float(not bool(sequence["reset"][frame_index])))
    masks = np.stack((reactive, transparency, validity, np.zeros_like(validity)), axis=-1)
    reference = hwc(selected["output"])
    arrays = (current, controls_a, controls_b, residual, history, motion, masks, reference)
    low_h, low_w = current.shape[:2]
    scale = int(selected["scale"])
    jitter = selected["jitter"].cpu().numpy()[0]
    previous_jitter = selected["previous_jitter"].cpu().numpy()[0]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as stream:
        stream.write(HEADER.pack(MAGIC, 1, low_w, low_h, scale, taps,
                                 float(jitter[0]), float(jitter[1]),
                                 float(previous_jitter[0]), float(previous_jitter[1])))
        for array in arrays:
            stream.write(np.ascontiguousarray(array, dtype="<f4").tobytes())
    digest = hashlib.sha256(output_path.read_bytes()).hexdigest()
    metadata = {"format": "naviqsr-gpu-case-v1", "case": output_path.name,
                "sha256": digest, "size_bytes": output_path.stat().st_size,
                "checkpoint": str(checkpoint_path), "sequence": sequence_index,
                "frame": frame_index, "lr_size": [low_w, low_h],
                "hr_size": [low_w * scale, low_h * scale], "scale": scale,
                "taps": taps, "motion_convention": "prev_lr = curr_lr + motion + jitter_prev - jitter_curr",
                "arrays": [list(array.shape) for array in arrays]}
    output_path.with_suffix(output_path.suffix + ".json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sequence", type=int, default=0)
    parser.add_argument("--frame", type=int, default=1)
    parser.add_argument("--taps", type=int, choices=(4, 5, 8), default=5)
    args = parser.parse_args()
    print(json.dumps(export_case(args.checkpoint, args.dataset, args.output,
                                 args.sequence, args.frame, args.taps), indent=2))


if __name__ == "__main__":
    main()
