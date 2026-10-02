"""Export one CPU NaviQSR network frame for D3D12 convolution parity testing."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

import numpy as np
import torch
from torch import nn

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from training.naviqsr.blocks import fold_model
from training.naviqsr.analytic_reconstruction import analytic_reconstruct
from training.naviqsr.model import NaviQSRnetwork
from training.naviqsr.polyphase import pack_features
from training.naviqsr.train import _features, _frame_tensor, _load_sequences


MAGIC = b"NQSRFRM2"
HEADER = struct.Struct("<8s16I5f")
LAYER = struct.Struct("<14I")


def export_case(checkpoint_path: Path, dataset_root: Path, output_path: Path,
                sequence_index: int, frame_index: int,
                taps: int = 5, fold_tolerance: float = 2.0e-5) -> dict[str, object]:
    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
    config = checkpoint["model_config"]
    if config.get("polyphase_mode") != "raw":
        raise ValueError("the first D3D12 network path currently supports raw 2x polyphase only")
    model = NaviQSRnetwork(input_channels=int(config["input_channels"]),
                           width=int(config["width"]), blocks=int(config["blocks"]),
                           hf_width=int(config["hf_width"]), polyphase_mode="raw")
    model.load_state_dict(checkpoint["model_state"], strict=True)
    model.eval()
    folded = fold_model(model).eval()

    sequences = _load_sequences(dataset_root)
    if not 0 <= sequence_index < len(sequences):
        raise ValueError("sequence index is outside the dataset")
    sequence = sequences[sequence_index]
    if not 0 <= frame_index < sequence["lr_rgb"].shape[0]:
        raise ValueError("frame index is outside the selected sequence")
    features = _features(sequence, frame_index, torch.device("cpu"))
    if features.shape[-1] % 2 or features.shape[-2] % 2:
        raise ValueError("network input dimensions must be even")
    if taps not in (4, 5, 8):
        raise ValueError("analytic reconstruction supports 4, 5, or 8 taps")

    with torch.no_grad():
        reference = model(features)
        folded_reference = folded(features)
        fold_error = max(float((reference[key] - folded_reference[key]).abs().max())
                         for key in ("controls", "residual"))
    if not np.isfinite(fold_error) or fold_error > fold_tolerance:
        raise RuntimeError(f"reference fold error {fold_error:.8g} exceeds {fold_tolerance:.8g}")

    # Quantize the folded parameters once. The GPU consumes FP16 storage and accumulates FP32.
    with torch.no_grad():
        for parameter in folded.parameters():
            parameter.copy_(parameter.half().float())

    # Build temporal history and output with the same quantized folded network as the GPU graph.
    previous_output = None
    previous_jitter = None
    selected = None
    with torch.no_grad():
        for current_frame in range(frame_index + 1):
            frame_features = _features(sequence, current_frame, torch.device("cpu"))
            prediction = folded(frame_features)
            target = _frame_tensor(sequence["hr_rgb"][current_frame], torch.device("cpu"))
            motion = _frame_tensor(sequence["motion"][current_frame], torch.device("cpu"))
            reactive = _frame_tensor(sequence["reactive"][current_frame], torch.device("cpu"))
            transparency = _frame_tensor(sequence["transparency"][current_frame], torch.device("cpu"))
            jitter = torch.as_tensor(sequence["jitter"][current_frame], dtype=torch.float32)[None]
            reset = bool(sequence["reset"][current_frame])
            history = torch.zeros_like(target) if reset or previous_output is None else previous_output
            prior_jitter = jitter if reset or previous_jitter is None else previous_jitter
            valid = torch.full_like(reactive, 0.0 if reset or previous_output is None else 1.0)
            result = analytic_reconstruct(
                frame_features[:, :3], prediction["controls"], prediction["residual"],
                int(sequence["scale"]), history_hr=history, motion_lr=motion,
                current_jitter=jitter, previous_jitter=prior_jitter,
                history_valid=valid, reactive_lr=reactive,
                transparency_lr=transparency, taps=taps)
            selected = {"features": frame_features,
                        "packed": pack_features(frame_features, "raw"),
                        "prediction": prediction, "history": history,
                        "output": result["output"], "jitter": jitter,
                        "previous_jitter": prior_jitter, "valid": valid,
                        "reset": reset}
            previous_output = result["output"]
            previous_jitter = jitter
    assert selected is not None
    features = selected["features"]
    packed = selected["packed"]

    layer_records: list[tuple[int, ...]] = []
    weight_parts: list[np.ndarray] = []
    weight_elements = 0

    def add_conv(conv: nn.Conv2d, source_a: int, *, relu: bool = False,
                 residual: bool = False) -> int:
        nonlocal weight_elements
        out_channels, in_channels, kernel_h, kernel_w = conv.weight.shape
        if kernel_h != kernel_w or kernel_h not in (1, 3):
            raise ValueError("D3D12 network smoke supports only 1x1 and 3x3 convolutions")
        weight_offset = weight_elements
        weight = np.ascontiguousarray(conv.weight.detach().cpu().numpy(), dtype="<f2")
        weight_parts.append(weight.reshape(-1))
        weight_elements += weight.size
        bias_offset = weight_elements
        bias = np.ascontiguousarray(conv.bias.detach().cpu().numpy(), dtype="<f2")
        weight_parts.append(bias.reshape(-1))
        weight_elements += bias.size
        output_id = len(layer_records)
        output_width, output_height = packed.shape[-1], packed.shape[-2]
        if source_a == 1:
            output_width, output_height = features.shape[-1], features.shape[-2]
        elif source_a >= 2:
            source_layer = layer_records[source_a - 2]
            output_width, output_height = source_layer[4], source_layer[5]
        layer_records.append((0, source_a, source_a, output_id,
                              output_width, output_height, in_channels, 0,
                              out_channels, kernel_h, weight_offset, bias_offset,
                              int(relu), int(residual)))
        return output_id + 2

    # The model uses the same folded residual blocks on the LF stem and after merging HF.
    current_source = add_conv(folded.stem, 0)
    for block in folded.blocks:
        current_source = add_conv(block.conv, current_source, relu=True, residual=True)
    low_frequency_source = current_source

    high_frequency_source = add_conv(folded.hf_stem[0], 1, relu=True)
    high_frequency_source = add_conv(folded.hf_stem[2], high_frequency_source, relu=True)
    pool_output_id = len(layer_records)
    low_width, low_height = packed.shape[-1], packed.shape[-2]
    layer_records.append((1, low_frequency_source, high_frequency_source,
                          pool_output_id, low_width, low_height,
                          int(config["width"]), int(config["hf_width"]),
                          int(config["width"]) + int(config["hf_width"]),
                          0, 0, 0, 0, 0))
    current_source = pool_output_id + 2

    current_source = add_conv(folded.merge, current_source)
    for block in folded.blocks:
        current_source = add_conv(block.conv, current_source, relu=True, residual=True)
    add_conv(folded.control_head, current_source)
    add_conv(folded.residual_head, current_source)

    weights = (np.concatenate(weight_parts).astype("<f2", copy=False)
               if weight_parts else np.empty((0,), dtype="<f2"))
    if weights.size & 1:
        weights = np.pad(weights, (0, 1), constant_values=0).astype("<f2", copy=False)
    controls = np.ascontiguousarray(selected["prediction"]["controls"][0].cpu().numpy(),
                                    dtype="<f4")
    residual = np.ascontiguousarray(selected["prediction"]["residual"][0].cpu().numpy(),
                                    dtype="<f4")
    history = np.ascontiguousarray(selected["history"][0].cpu().numpy(), dtype="<f4")
    reference_image = np.ascontiguousarray(selected["output"][0].cpu().numpy(), dtype="<f4")
    input_channels, height, width = features.shape[1:]
    packed_array = np.ascontiguousarray(packed[0].cpu().numpy(), dtype="<f4")
    feature_array = np.ascontiguousarray(features[0].cpu().numpy(), dtype="<f4")
    arrays = (packed_array, feature_array, weights, controls, residual,
              history, reference_image)
    current_jitter = selected["jitter"].cpu().numpy()[0]
    previous_jitter = selected["previous_jitter"].cpu().numpy()[0]
    scale = int(sequence["scale"])
    history_valid = float(selected["valid"].max().item() > 0.5)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as stream:
        stream.write(HEADER.pack(
            MAGIC, 2, width, height, input_channels, int(config["width"]),
            int(config["hf_width"]), len(layer_records), packed_array.size,
            feature_array.size, weights.size, controls.size, residual.size,
            history.size, reference_image.size, scale, taps,
            float(current_jitter[0]), float(current_jitter[1]),
            float(previous_jitter[0]), float(previous_jitter[1]), history_valid))
        for record in layer_records:
            stream.write(LAYER.pack(*record))
        for array in arrays:
            stream.write(array.tobytes(order="C"))

    digest = hashlib.sha256(output_path.read_bytes()).hexdigest()
    metadata = {
        "format": "naviqsr-network-gpu-case-v2",
        "case": output_path.name,
        "sha256": digest,
        "size_bytes": output_path.stat().st_size,
        "checkpoint": str(checkpoint_path),
        "dataset": str(dataset_root),
        "sequence": sequence_index,
        "frame": frame_index,
        "input_size": [width, height],
        "polyphase_size": [width // 2, height // 2],
        "polyphase_mode": "raw",
        "scale": scale,
        "taps": taps,
        "history_valid": history_valid,
        "layers": len(layer_records),
        "fp16_weight_elements": int(weights.size),
        "fp32_fold_max_abs_error": fold_error,
        "reference": "folded FP16-quantized parameters, FP32 activations/accumulation",
        "arrays": [list(array.shape) for array in arrays],
    }
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
    parser.add_argument("--fold-tolerance", type=float, default=2.0e-5)
    args = parser.parse_args()
    print(json.dumps(export_case(args.checkpoint, args.dataset, args.output,
                                 args.sequence, args.frame, args.taps,
                                 args.fold_tolerance), indent=2))


if __name__ == "__main__":
    main()
