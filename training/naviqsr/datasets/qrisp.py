"""Import user-supplied QRISP files into NaviQSR NPZ sequence format.

This importer never downloads QRISP and never accepts its research license.
The caller supplies an explicit per-frame manifest after obtaining lawful access.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image


def _resolve(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (root / path).resolve()


def _read_rgb(path: Path) -> np.ndarray:
    image = np.asarray(Image.open(path).convert("RGB"), dtype=np.float32) / 255.0
    return np.where(image <= 0.04045, image / 12.92,
                    ((image + 0.055) / 1.055) ** 2.4).astype(np.float32)


def _resize(array: np.ndarray, size: tuple[int, int], mode: str) -> np.ndarray:
    width, height = size
    if array.shape[1] == width and array.shape[0] == height:
        return array.astype(np.float32, copy=False)
    if mode == "rgb":
        channels = []
        for channel in range(array.shape[-1]):
            image = Image.fromarray(array[..., channel].astype(np.float32), mode="F")
            channels.append(np.asarray(image.resize(size, Image.Resampling.BILINEAR),
                                       dtype=np.float32))
        return np.stack(channels, axis=-1)
    result = []
    for channel in range(array.shape[-1]):
        image = Image.fromarray(array[..., channel].astype(np.float32), mode="F")
        result.append(np.asarray(image.resize(size, Image.Resampling.BILINEAR), dtype=np.float32))
    return np.stack(result, axis=-1)


def _read_depth(path: Path, size: tuple[int, int]) -> np.ndarray:
    rgba = np.asarray(Image.open(path).convert("RGBA"), dtype=np.float32)
    # QRISP packs the normalized 32-bit depth into four 8-bit PNG channels.
    normalized = (rgba[..., 0] / 255.0 + rgba[..., 1] / (255.0 ** 2)
                  + rgba[..., 2] / (255.0 ** 3) + rgba[..., 3] / (255.0 ** 4))
    resized = _resize(normalized[..., None], size, "linear")
    return np.clip(resized, 0.0, 1.0).astype(np.float32)


def _read_motion(path: Path, size: tuple[int, int],
                 channel_config: dict[str, str], y_sign: float) -> np.ndarray:
    try:
        import OpenEXR
    except ImportError as exc:
        raise RuntimeError("QRISP motion EXR import requires OpenEXR; install training/naviqsr/requirements-qrisp.txt") from exc
    with OpenEXR.File(str(path), separate_channels=True) as exr:
        channels = {name: channel.pixels.copy() for name, channel in exr.channels().items()}
    vertical_name = channel_config.get("vertical", "R")
    horizontal_name = channel_config.get("horizontal", "G")
    if vertical_name not in channels or horizontal_name not in channels:
        raise ValueError(f"motion EXR {path} lacks channels {vertical_name}/{horizontal_name}; found {sorted(channels)}")
    vertical = np.asarray(channels[vertical_name], dtype=np.float32)
    horizontal = np.asarray(channels[horizontal_name], dtype=np.float32)
    if vertical.ndim != 2 or horizontal.ndim != 2 or vertical.shape != horizontal.shape:
        raise ValueError(f"motion EXR {path} has unsupported channel shapes")
    width, height = size
    motion = np.stack((horizontal * width, vertical * height * y_sign), axis=-1)
    return _resize(motion, size, "linear").astype(np.float32)


def _nested_value(data: Any, path: str) -> Any:
    value = data
    for component in path.split("."):
        if component.isdecimal():
            value = value[int(component)]
        else:
            value = value[component]
    return value


def _load_camera_jitter(root: Path, segment: dict[str, Any], frame_index: int,
                        frame: dict[str, Any]) -> tuple[float, float]:
    if "jitter" in frame:
        value = frame["jitter"]
    elif segment.get("camera_json") and segment.get("jitter_path"):
        camera = json.loads(_resolve(root, segment["camera_json"]).read_text(encoding="utf-8"))
        path = segment["jitter_path"].replace("{frame}", str(frame_index))
        value = _nested_value(camera, path)
    else:
        raise ValueError(f"segment {segment.get('name', '<unnamed>')} frame {frame_index} has no jitter mapping")
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError("jitter must be a two-element [x, y] LR-pixel offset")
    return float(value[0]), float(value[1])


def import_manifest(manifest_path: Path, output_root: Path,
                    license_confirmed: bool) -> dict[str, Any]:
    if not license_confirmed:
        raise PermissionError("QRISP is research-use licensed; review its terms yourself and pass --license-confirmed only if applicable")
    manifest_path = manifest_path.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_root = _resolve(manifest_path.parent, manifest.get("source_root", "."))
    output_root.mkdir(parents=True, exist_ok=True)
    sequence_records = []
    frame_total = 0
    for sequence_index, segment in enumerate(manifest["segments"]):
        frames = segment["frames"]
        if len(frames) < 2:
            raise ValueError(f"segment {segment.get('name', sequence_index)} needs at least two frames")
        scale = int(segment.get("scale", 2))
        if scale not in (2, 3, 4):
            raise ValueError("segment scale must be 2, 3, or 4")
        first_low = _read_rgb(_resolve(source_root, frames[0]["lr_color"]))
        low_h, low_w = first_low.shape[:2]
        high_w, high_h = low_w * scale, low_h * scale
        lows, highs, depths, motions = [], [], [], []
        jitters, exposures, resets = [], [], []
        source_hashes = []
        for frame_index, frame in enumerate(frames):
            low_path = _resolve(source_root, frame["lr_color"])
            target_path = _resolve(source_root, frame["hr_target"])
            depth_path = _resolve(source_root, frame["depth_png"])
            motion_path = _resolve(source_root, frame["motion_exr"])
            low = first_low if frame_index == 0 else _read_rgb(low_path)
            low = _resize(low, (low_w, low_h), "rgb")
            high = _read_rgb(target_path)
            if high.shape[:2] != (high_h, high_w):
                raise ValueError(f"target frame must be {high_w}x{high_h}: {target_path}")
            depth = _read_depth(depth_path, (low_w, low_h))
            motion = _read_motion(motion_path, (low_w, low_h),
                                  segment.get("motion_channels", {}),
                                  float(segment.get("motion_y_sign", -1.0)))
            lows.append(low.astype(np.float16))
            highs.append(high.astype(np.float16))
            depths.append(depth.astype(np.float16))
            motions.append(motion.astype(np.float16))
            jitters.append(_load_camera_jitter(source_root, segment, frame_index, frame))
            exposures.append(float(frame.get("exposure", 0.0)))
            resets.append(int(frame_index == 0 or frame.get("reset", False)))
            for source_file in (low_path, target_path, depth_path, motion_path):
                source_hashes.append({"path": str(source_file),
                                      "sha256": hashlib.sha256(source_file.read_bytes()).hexdigest()})

        frame_count = len(frames)
        sequence = {
            "lr_rgb": np.stack(lows), "hr_rgb": np.stack(highs),
            "depth": np.stack(depths), "motion": np.stack(motions),
            # QRISP has no required reactive/transparency modality; default to zero and
            # keep MCLD confidence conservative for this source.
            "reactive": np.zeros((frame_count, low_h, low_w, 1), dtype=np.float16),
            "transparency": np.zeros((frame_count, low_h, low_w, 1), dtype=np.float16),
            "jitter": np.asarray(jitters, dtype=np.float32),
            "exposure": np.asarray(exposures, dtype=np.float32),
            "reset": np.asarray(resets, dtype=np.uint8),
            "history_valid": np.asarray([0 if flag else 1 for flag in resets], dtype=np.uint8),
            "seed": sequence_index, "scale": scale,
            "motion_convention": "prev_lr = curr_lr + motion + jitter_prev - jitter_curr",
        }
        output_path = output_root / f"qrisp_{sequence_index:04d}.npz"
        np.savez_compressed(output_path, **sequence)
        sequence_records.append({"name": segment.get("name", output_path.stem),
                                 "file": output_path.name,
                                 "sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
                                 "frames": frame_count, "lr_size": [low_w, low_h],
                                 "hr_size": [high_w, high_h],
                                 "source_sha256": source_hashes})
        frame_total += frame_count
    index = {"format": "naviqsr-qrisp-import-v1", "source_license": "research use only; user-confirmed",
             "source_manifest": str(manifest_path), "sequences": sequence_records,
             "frame_count": frame_total,
             "note": "No data were downloaded or licensed by this importer; reactive/transparency masks are unavailable and default to zero."}
    (output_root / "index.json").write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    return index


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True,
                        help="explicit per-segment/per-frame mapping; see docs/naviqsr/QRISP_IMPORT.md")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--license-confirmed", action="store_true",
                        help="confirm that you independently reviewed and accepted the applicable research-use terms")
    args = parser.parse_args()
    index = import_manifest(args.manifest, args.output, args.license_confirmed)
    print(json.dumps({"output": str(args.output), "sequences": len(index["sequences"]),
                      "frames": index["frame_count"]}, indent=2))


if __name__ == "__main__":
    main()
