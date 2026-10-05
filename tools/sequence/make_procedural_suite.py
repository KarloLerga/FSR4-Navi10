from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

try:
    import numpy as np
except ImportError as error:  # pragma: no cover - environment diagnostic
    raise SystemExit("make_procedural_suite requires NumPy") from error

from f4seq_format import F4SeqError, build_f4seq


def halton(index: int, base: int) -> float:
    result = 0.0
    fraction = 1.0
    while index:
        fraction /= base
        result += fraction * (index % base)
        index //= base
    return result


def generate(output: Path, width: int, height: int, frames_count: int, seed: int) -> dict[str, object]:
    if not (0 < width <= 16384 and 0 < height <= 16384 and 2 <= frames_count <= 10000):
        raise F4SeqError("width/height must be 1..16384 and frames must be 2..10000")
    y, x = np.mgrid[0:height, 0:width].astype(np.float32)
    x_norm = x / max(1.0, float(width - 1))
    y_norm = y / max(1.0, float(height - 1))
    frames: list[dict[str, object]] = []
    source_config = {
        "generator": "delta-control-v2-mixed-procedural-v1",
        "width": width,
        "height": height,
        "frame_count": frames_count,
        "seed": seed,
        "families": ["static_convergence", "camera_pan", "moving_geometry", "disocclusion",
                     "shading_change", "repeating_detail", "reset_cut"],
    }
    source_hash = hashlib.sha256(
        Path(__file__).read_bytes() + json.dumps(source_config, sort_keys=True).encode("utf-8")
    ).hexdigest()
    metadata = {
        "sequence_id": f"procedural-mixed-{seed}",
        "seed": seed,
        "render_size": [width, height],
        "output_size": [width, height],
        "preset": "native",
        "source_kind": "procedural_synthetic",
        "source_hash": source_hash,
        "motion_vector_convention": "current_to_previous_render_pixels_unjittered",
        "depth_convention": "forward_zero_to_one",
    }
    with tempfile.TemporaryDirectory(prefix="f4n10-f4seq-") as temporary:
        root = Path(temporary)
        for frame_index in range(frames_count):
            frame_dir = root / "input" / f"{frame_index:06d}"
            frame_dir.mkdir(parents=True)
            cut_index = frames_count // 2
            camera_cut = frame_index == cut_index
            pan = np.float32(0.0 if frame_index < cut_index else (frame_index - cut_index) * 0.75)
            scene_x = x - pan
            checker = ((np.floor(scene_x / 9.0) + np.floor(y / 9.0) + seed) % 2).astype(np.float32)
            diagonal = np.abs(np.mod(scene_x + y * 0.72 + seed % 47, 53.0) - 26.5) < 0.7
            repeating = np.abs(np.mod(scene_x, 31.0) - 15.5) < 0.8
            moving_x = np.mod(width * 0.22 + frame_index * max(1.0, width / 96.0), float(width))
            moving_bar = np.abs(x - moving_x) < max(1.5, width / 640.0)
            reveal = ((frame_index % 7) in (0, 1)) & (x > width * 0.67) & (x < width * 0.72)
            highlight_center = np.float32(width * (0.28 + 0.36 * ((frame_index % 12) / 11.0)))
            specular = np.exp(-((x - highlight_center) ** 2 / max(4.0, width * width * 0.0008) +
                                (y - height * 0.42) ** 2 / max(4.0, height * height * 0.0012)))
            exposure = np.float32(1.25 if camera_cut else 1.0)
            pulse = np.float32(0.05 * ((frame_index % 5) / 4.0))

            color = np.empty((height, width, 4), dtype="<f2")
            color[..., 0] = np.clip((0.06 + 0.74 * x_norm + 0.08 * checker + pulse) * exposure, 0.0, 2.0)
            color[..., 1] = np.clip((0.07 + 0.68 * y_norm + 0.12 * diagonal + 0.18 * specular) * exposure, 0.0, 2.0)
            color[..., 2] = np.clip((0.10 + 0.36 * checker + 0.30 * repeating + 0.45 * moving_bar) * exposure, 0.0, 2.0)
            color[..., 3] = 1.0

            depth = np.full((height, width), 0.82, dtype="<f4")
            depth[moving_bar] = 0.28
            depth[reveal] = 0.46
            depth[diagonal] = np.minimum(depth[diagonal], 0.62)

            motion = np.zeros((height, width, 2), dtype="<f2")
            motion[..., 0] = -pan
            motion[moving_bar, 0] = -max(1.0, width / 96.0)

            reactive = np.zeros((height, width), dtype=np.uint8)
            reactive[specular > 0.48] = 210
            reactive[moving_bar] = 255
            reactive[reveal] = 255
            composition = np.zeros((height, width), dtype=np.uint8)
            composition[(diagonal | repeating) & (checker > 0)] = 96

            array_data = {
                "color": color.tobytes(order="C"),
                "depth": depth.tobytes(order="C"),
                "motion_vectors": motion.tobytes(order="C"),
                "reactive_mask": reactive.tobytes(order="C"),
                "transparency_composition_mask": composition.tobytes(order="C"),
            }
            source_paths = {}
            for name, data in array_data.items():
                rel = f"input/{frame_index:06d}/{name}.raw"
                (root / rel).write_bytes(data)
                source_paths[name] = rel
            jitter_index = frame_index + 1
            previous_index = max(1, frame_index)
            frames.append({
                "frame_time_delta_ms": 16.666667,
                "jitter_current": [halton(jitter_index, 2) - 0.5, halton(jitter_index, 3) - 0.5],
                "jitter_previous": [halton(previous_index, 2) - 0.5, halton(previous_index, 3) - 0.5],
                "exposure": float(exposure),
                "pre_exposure": 1.0,
                "reset": frame_index == 0 or camera_cut,
                "camera_cut": camera_cut,
                "validity": {"reactive_mask": True, "transparency_composition_mask": True},
                "arrays": source_paths,
            })
        return build_f4seq(output, metadata, frames, root)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate deterministic mixed temporal input frames for pipeline validation.")
    parser.add_argument("output", type=Path, help="output .f4seq")
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--frames", type=int, default=8)
    parser.add_argument("--seed", type=int, default=17)
    args = parser.parse_args()
    try:
        result = generate(args.output, args.width, args.height, args.frames, args.seed)
    except (OSError, F4SeqError, ValueError) as error:
        print(f"make_procedural_suite: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
