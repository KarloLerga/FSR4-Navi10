#!/usr/bin/env python3
"""Replay the pinned FSR4 POST reconstruction math from a validated .f4cap."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from tools.teacher.capture_format import validate_capture  # noqa: E402


def replay_arrays(metadata: dict[str, Any], arrays: dict[str, np.ndarray], *, block_rows: int = 32) -> tuple[np.ndarray, dict[str, Any]]:
    """Evaluate post_common.hlsli::apply_model_filter plus its output conversion.

    This uses float32 intermediates and the source's literal exp-based formulas.
    `np.fmax`/`np.fmin` model the source shader's NaN-tolerant clamp behavior.
    It intentionally does not stabilize the raw logits: doing so would conceal
    a discrepancy between the pinned POST source and captured output.
    """
    if block_rows <= 0:
        raise ValueError("block_rows must be positive")

    output_h = int(metadata["output_height"])
    output_w = int(metadata["output_width"])
    render_h = int(metadata["render_height"])
    render_w = int(metadata["render_width"])
    params = np.asarray(arrays["raw_model_parameters"], dtype=np.float32)
    source = np.asarray(arrays["current_reconstruction_source"], dtype=np.float32)
    history = np.asarray(arrays["reprojected_history"], dtype=np.float32)
    if params.shape != (output_h, output_w, 4):
        raise ValueError("raw_model_parameters dimensions disagree with metadata")
    if history.shape != (output_h, output_w, 3):
        raise ValueError("reprojected_history dimensions disagree with metadata")
    if source.shape != (render_h, render_w, 3):
        raise ValueError("current_reconstruction_source dimensions disagree with metadata")

    scale_x = np.float32(output_w / render_w)
    scale_y = np.float32(output_h / render_h)
    inv_scale_x = np.float32(1.0 / scale_x)
    inv_scale_y = np.float32(1.0 / scale_y)
    jitter_x, jitter_y = (np.float32(x) for x in metadata["jitter_current"])
    exposure = np.float32(metadata["exposure"])
    pre_exposure = np.float32(metadata["pre_exposure"])
    if exposure == 0.0:
        exposure = np.float32(1.0)
    exposure_value = np.float32(exposure / pre_exposure)
    out = np.empty((output_h, output_w, 3), dtype=np.float16)
    nan_model_pixels = 0

    x_out = np.arange(output_w, dtype=np.float32)
    # Keep the operations and constants from post_common.hlsli in float32.
    kernel_factor = np.float32(-0.5 / (0.47 * 0.47))
    with np.errstate(over="ignore", invalid="ignore", divide="ignore", under="ignore"):
        for y0 in range(0, output_h, block_rows):
            y1 = min(output_h, y0 + block_rows)
            y_out = np.arange(y0, y1, dtype=np.float32)[:, None]
            p = params[y0:y1]
            h = history[y0:y1]

            rho = (np.exp(p[:, :, 0]) - np.exp(-p[:, :, 0])) / (
                np.exp(p[:, :, 0]) + np.exp(-p[:, :, 0])
            )
            sx = np.float32(2.0) / (np.float32(1.0) + np.exp(-p[:, :, 1]))
            sy = np.float32(2.0) / (np.float32(1.0) + np.exp(-p[:, :, 2]))
            sx2 = sx * sx
            sy2 = sy * sy
            sxy = sx * sy

            lr_x = (np.float32(-0.5) + inv_scale_x / np.float32(2.0) + x_out * inv_scale_x) + jitter_x
            lr_y = (np.float32(-0.5) + inv_scale_y / np.float32(2.0) + y_out * inv_scale_y) + jitter_y
            center_x = np.rint(lr_x).astype(np.int32)
            center_y = np.rint(lr_y).astype(np.int32)

            total_weight = np.zeros((y1 - y0, output_w), dtype=np.float32)
            weighted_color = np.zeros((y1 - y0, output_w, 3), dtype=np.float32)
            for dy in range(3):
                iy = np.clip(center_y + dy - 1, 0, render_h - 1)
                y_dist = (iy.astype(np.float32) - lr_y) * scale_y
                y_dist2 = y_dist * y_dist
                for dx in range(3):
                    ix = np.clip(center_x + dx - 1, 0, render_w - 1)
                    x_dist = (ix.astype(np.float32) - lr_x) * scale_x
                    x_dist2 = x_dist * x_dist
                    exponent = kernel_factor * (
                        x_dist2 * sx2
                        + np.float32(2.0) * rho * (x_dist * y_dist) * sxy
                        + y_dist2 * sy2
                    )
                    weight = np.exp(exponent)
                    total_weight += weight
                    sample = source[iy, ix] * exposure_value
                    mu = np.float32(0.1174) * np.log(np.float32(1.0) + np.float32(150.0) * sample)
                    mu = np.fmax(mu, np.float32(0.0))
                    weighted_color += mu * weight[:, :, None]

            upsampled = weighted_color / total_weight[:, :, None]
            blend = np.float32(1.0) / (np.float32(1.0) + np.exp(-p[:, :, 3]))
            model_color = upsampled * (np.float32(1.0) - blend[:, :, None]) + h * blend[:, :, None]
            nan_model_pixels += int(np.count_nonzero(~np.isfinite(model_color).all(axis=2)))

            # Pinned FSR4 native/1080 capture profile has RCAS disabled and uses
            # linear input color space, so POST applies RemoveMuLaw/exposure.
            linear = (np.exp(np.float32(8.51788) * model_color) - np.float32(1.0)) / np.float32(150.0)
            linear = np.fmax(linear, np.float32(0.0)) / exposure_value
            final = np.fmin(np.fmax(linear, np.float32(0.0)), np.float32(64000.0))
            out[y0:y1] = final.astype(np.float16)

    return out, {
        "profile": "pinned_fsr4_post_common_linear_rcas_off",
        "render_size": [render_w, render_h],
        "output_size": [output_w, output_h],
        "scale": [float(scale_x), float(scale_y)],
        "jitter_current": [float(jitter_x), float(jitter_y)],
        "exposure_value": float(exposure_value),
        "raw_exp_formula": True,
        "nonfinite_replayed_model_pixels": nan_model_pixels,
        "raw_parameter_min_by_channel": [float(params[:, :, i].min()) for i in range(4)],
        "raw_parameter_max_by_channel": [float(params[:, :, i].max()) for i in range(4)],
    }


def _load_capture_arrays(path: Path) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    validate_capture(path)
    with zipfile.ZipFile(path, "r") as archive:
        manifest = json.loads(archive.read("capture.json"))
        metadata = manifest["metadata"]
        wanted = (
            "current_reconstruction_source",
            "reprojected_history",
            "raw_model_parameters",
            "final_rgb",
        )
        arrays: dict[str, np.ndarray] = {}
        for name in wanted:
            descriptor = manifest["arrays"][name]
            arrays[name] = np.frombuffer(
                archive.read(descriptor["path"]), dtype=np.dtype(descriptor["dtype"])
            ).reshape(descriptor["shape"])
    return metadata, arrays


def replay_capture(path: Path, *, block_rows: int = 32) -> dict[str, Any]:
    metadata, arrays = _load_capture_arrays(path)
    replay, details = replay_arrays(metadata, arrays, block_rows=block_rows)
    reference = arrays["final_rgb"].astype(np.float32)
    replay32 = replay.astype(np.float32)
    absolute = np.abs(replay32 - reference)
    rgb_match = bool(np.count_nonzero(absolute > np.float32(1e-3)) == 0)
    intermediate_finite = details["nonfinite_replayed_model_pixels"] == 0
    return {
        "capture": str(path),
        "frame_index": metadata["frame_index"],
        "sequence_id": metadata["sequence_id"],
        "sequence_hash": metadata["sequence_hash"],
        "provider_source_commit": metadata["source_commit"],
        "shader_hashes": metadata["shader_hashes"],
        **details,
        "reference_finite": bool(np.isfinite(reference).all()),
        "replay_finite": bool(np.isfinite(replay32).all()),
        "reference_zero_fraction": float(np.count_nonzero(reference == 0.0) / reference.size),
        "replay_zero_fraction": float(np.count_nonzero(replay32 == 0.0) / replay32.size),
        "exact_half_match_fraction": float(np.count_nonzero(replay == arrays["final_rgb"]) / replay.size),
        "within_1e_3_fraction": float(np.count_nonzero(absolute <= np.float32(1e-3)) / absolute.size),
        "max_absolute_error": float(absolute.max(initial=0.0)),
        "mean_absolute_error": float(absolute.mean()),
        "rms_error": float(np.sqrt(np.mean(absolute * absolute))),
        "rgb_within_tolerance": rgb_match,
        "numerically_valid": intermediate_finite,
        "passed": rgb_match and intermediate_finite,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("captures", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--block-rows", type=int, default=32)
    args = parser.parse_args()

    results = [replay_capture(path, block_rows=args.block_rows) for path in args.captures]
    first = results[0]
    consistent = all(
        result["sequence_hash"] == first["sequence_hash"]
        and result["provider_source_commit"] == first["provider_source_commit"]
        and result["profile"] == first["profile"]
        for result in results
    )
    report = {
        "schema": "f4n10.fsr4-post-replay-oracle.v1",
        "source": "pinned FSR4 post_common.hlsli::apply_model_filter; literal float32 equations",
        "source_file": "third_party/fidelityfx-fsr4-source/Kits/FidelityFX/upscalers/fsr4/include/gpu/fsr4/post_common.hlsli",
        "source_file_sha256": hashlib.sha256(
            (REPO_ROOT / "third_party/fidelityfx-fsr4-source/Kits/FidelityFX/upscalers/fsr4/include/gpu/fsr4/post_common.hlsli").read_bytes()
        ).hexdigest(),
        "configuration_assumptions": {
            "color_space": "linear",
            "auto_exposure_enabled": False,
            "rcas_enabled": False,
            "exposure_value": "input exposure texture / preExposure; zero input exposure maps to 1",
        },
        "validation": {
            "capture_packages_validated": True,
            "capture_set_consistent": consistent,
            "per_channel_absolute_tolerance": 1e-3,
            "post_rgb_replay_matches": consistent and all(result["rgb_within_tolerance"] for result in results),
            "all_intermediates_numerically_valid": all(result["numerically_valid"] for result in results),
            "all_captures_passed": consistent and all(result["passed"] for result in results),
            "quality_claimed": False,
        },
        "captures": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report["validation"], sort_keys=True))
    for item in results:
        print(
            f"frame {item['frame_index']}: passed={item['passed']} "
            f"rgb_match={item['rgb_within_tolerance']} "
            f"numerically_valid={item['numerically_valid']} "
            f"exact={item['exact_half_match_fraction']:.6f} "
            f"within1e-3={item['within_1e_3_fraction']:.6f} "
            f"max_abs={item['max_absolute_error']:.6g} "
            f"nonfinite_model_pixels={item['nonfinite_replayed_model_pixels']}"
        )
    return 0 if report["validation"]["all_captures_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
