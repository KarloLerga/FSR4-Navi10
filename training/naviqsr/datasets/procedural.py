"""Deterministic, analytic temporal stress sequences for NaviQSR.

Motion vectors use LR-pixel units and the convention
    previous_position = current_position + motion + previous_jitter - current_jitter.
Colors are linear scene values multiplied by the recorded exposure.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np


def _halton(index: int, base: int) -> float:
    result = 0.0
    fraction = 1.0 / base
    while index:
        result += fraction * (index % base)
        index //= base
        fraction /= base
    return result


def _camera(frame: int, cut_frame: int, seed: int, width: int, height: int) -> tuple[float, ...]:
    epoch = int(cut_frame >= 0 and frame >= cut_frame)
    local_frame = frame - cut_frame if epoch else frame
    phase = (seed % 997) * 0.001 + epoch * 1.73
    pan_x = 0.38 * local_frame + 3.3 * math.sin(local_frame * 0.19 + phase)
    pan_y = 1.8 * math.sin(local_frame * 0.13 + phase * 0.7)
    angle = 0.006 * math.sin(local_frame * 0.11 + phase)
    return pan_x, pan_y, angle


def _camera_forward(x: np.ndarray, y: np.ndarray, frame: int, cut_frame: int,
                    seed: int, width: int, height: int) -> tuple[np.ndarray, np.ndarray]:
    pan_x, pan_y, angle = _camera(frame, cut_frame, seed, width, height)
    cx, cy = width * 0.5, height * 0.5
    dx, dy = x - cx, y - cy
    c, s = math.cos(angle), math.sin(angle)
    return c * dx - s * dy + cx + pan_x, s * dx + c * dy + cy + pan_y


def _camera_inverse(x: np.ndarray, y: np.ndarray, frame: int, cut_frame: int,
                    seed: int, width: int, height: int) -> tuple[np.ndarray, np.ndarray]:
    pan_x, pan_y, angle = _camera(frame, cut_frame, seed, width, height)
    cx, cy = width * 0.5, height * 0.5
    dx, dy = x - cx - pan_x, y - cy - pan_y
    c, s = math.cos(angle), math.sin(angle)
    return c * dx + s * dy + cx, -s * dx + c * dy + cy


def _screen_motion(world_x: np.ndarray, world_y: np.ndarray, previous_world_x: np.ndarray,
                   previous_world_y: np.ndarray, frame: int, cut_frame: int,
                   seed: int, width: int, height: int) -> tuple[np.ndarray, np.ndarray]:
    previous_x, previous_y = _camera_forward(
        previous_world_x, previous_world_y, max(0, frame - 1), cut_frame,
        seed, width, height)
    current_x, current_y = _camera_forward(world_x, world_y, frame, cut_frame,
                                            seed, width, height)
    return previous_x - current_x, previous_y - current_y


def _render(x: np.ndarray, y: np.ndarray, frame: int, cut_frame: int, seed: int,
            width: int, height: int, exposure: float) -> dict[str, np.ndarray]:
    epoch = int(cut_frame >= 0 and frame >= cut_frame)
    phase = (seed % 991) * 0.017 + epoch * 0.91
    world_x, world_y = _camera_inverse(x, y, frame, cut_frame, seed, width, height)
    prev_frame = max(0, frame - 1)
    prev_world_x, prev_world_y = _camera_inverse(
        x, y, prev_frame, cut_frame, seed, width, height)

    checker = ((np.floor((world_x + phase * 11.0) / 9.0)
                + np.floor((world_y - phase * 7.0) / 9.0)) % 2.0)
    texture = 0.5 + 0.5 * np.sin(world_x * 0.19 + phase) * np.sin(world_y * 0.23 - phase)
    base = 0.12 + 0.11 * checker + 0.09 * texture
    rgb = np.stack((base * 0.72, base * 0.86, base), axis=-1).astype(np.float32)
    depth = np.full(x.shape, 0.92, dtype=np.float32)
    motion_x, motion_y = _screen_motion(
        world_x, world_y, prev_world_x, prev_world_y, frame, cut_frame,
        seed, width, height)
    reactive = np.zeros(x.shape, dtype=np.float32)
    transparency = np.zeros(x.shape, dtype=np.float32)

    def composite(alpha: np.ndarray, color: tuple[float, float, float], z: float,
                  mv_x: np.ndarray | None = None, mv_y: np.ndarray | None = None,
                  reactive_strength: float = 0.0, transparent: bool = False) -> None:
        nonlocal rgb, depth, motion_x, motion_y, reactive, transparency
        a = np.clip(alpha.astype(np.float32), 0.0, 1.0)
        layer = np.asarray(color, dtype=np.float32)
        rgb = rgb * (1.0 - a[..., None]) + layer * a[..., None]
        coverage = a > 0.25
        if z < 0.92:
            depth = np.where(coverage, z, depth)
            if mv_x is not None and mv_y is not None:
                motion_x = np.where(coverage, mv_x, motion_x)
                motion_y = np.where(coverage, mv_y, motion_y)
        reactive = np.maximum(reactive, a * reactive_strength)
        if transparent:
            transparency = np.maximum(transparency, a)

    # Fine grid/fence pattern: a stationary, high-frequency opaque surface.
    fence_x = np.abs(np.mod(world_x + 0.27 * world_y + 4.0, 13.0) - 6.5)
    fence_y = np.abs(np.mod(world_y + 0.20 * world_x + 2.0, 15.0) - 7.5)
    fence_alpha = np.maximum(np.clip(0.55 - fence_x, 0.0, 1.0),
                             np.clip(0.48 - fence_y, 0.0, 1.0))
    composite(fence_alpha, (0.08, 0.25, 0.19), 0.67)

    # Thin, subpixel wire and a moving specular highlight.
    wire_y = height * 0.63 + 0.035 * (world_x - width * 0.5)
    wire_alpha = np.clip(0.55 - np.abs(world_y - wire_y), 0.0, 1.0)
    composite(wire_alpha, (0.72, 0.66, 0.52), 0.52)
    stripe_y = height * 0.38 + 6.0 * math.sin(frame * 0.17 + phase) + 0.12 * (world_x - width * 0.5)
    stripe_alpha = np.clip(0.52 - np.abs(world_y - stripe_y), 0.0, 1.0)
    composite(stripe_alpha, (2.5, 2.15, 1.45), 0.48, reactive_strength=0.85)

    # Rotating thin spokes. Motion is analytically derived from the prior phase.
    cx, cy = width * 0.5, height * 0.5
    dx, dy = world_x - cx, world_y - cy
    spoke_angle = frame * 0.041 + phase
    local_x = math.cos(spoke_angle) * dx + math.sin(spoke_angle) * dy
    local_y = -math.sin(spoke_angle) * dx + math.cos(spoke_angle) * dy
    radius = np.sqrt(dx * dx + dy * dy)
    theta = np.arctan2(local_y, local_x)
    spoke_dist = np.abs(np.sin(9.0 * theta)) * np.maximum(radius, 1.0)
    spoke_alpha = np.clip(0.8 - spoke_dist, 0.0, 1.0)
    spoke_alpha *= np.clip(radius - 9.0, 0.0, 1.0) * np.clip(height * 0.46 - radius, 0.0, 1.0)
    prev_spoke_angle = max(0, frame - 1) * 0.041 + phase
    pcos, psin = math.cos(prev_spoke_angle), math.sin(prev_spoke_angle)
    previous_spoke_x = pcos * local_x - psin * local_y + cx
    previous_spoke_y = psin * local_x + pcos * local_y + cy
    spoke_mv_x, spoke_mv_y = _screen_motion(
        world_x, world_y, previous_spoke_x, previous_spoke_y, frame,
        cut_frame, seed, width, height)
    composite(spoke_alpha, (0.76, 0.32, 0.10), 0.40,
              spoke_mv_x, spoke_mv_y, reactive_strength=0.35)

    # Repeated translucent leaf cards. Their translation and layer mask are deterministic.
    leaf_vx, leaf_vy = 1.35, -0.24
    leaf_x = world_x - leaf_vx * frame
    leaf_y = world_y - leaf_vy * frame
    cell_x = np.floor(leaf_x / 18.0)
    cell_y = np.floor(leaf_y / 14.0)
    center_x = cell_x * 18.0 + 7.5 + 1.8 * np.sin(cell_y * 2.17 + phase)
    center_y = cell_y * 14.0 + 6.0 + 1.3 * np.cos(cell_x * 1.73 - phase)
    ellipse = ((leaf_x - center_x) / 5.8) ** 2 + ((leaf_y - center_y) / 2.1) ** 2
    leaf_alpha = np.clip((1.06 - ellipse) * 3.2, 0.0, 0.72)
    prev_leaf_x = leaf_x + leaf_vx
    prev_leaf_y = leaf_y + leaf_vy
    leaf_mv_x, leaf_mv_y = _screen_motion(
        world_x, world_y, prev_leaf_x, prev_leaf_y, frame,
        cut_frame, seed, width, height)
    composite(leaf_alpha, (0.12, 0.48, 0.13), 0.31,
              leaf_mv_x, leaf_mv_y, reactive_strength=0.72, transparent=True)

    # Moving particles, each with exact translational motion.
    rng = np.random.default_rng(seed + 7919 * epoch)
    for particle in range(10):
        px = float(rng.uniform(0.08, 0.92) * width) + frame * (0.38 + 0.04 * particle)
        py0 = float(rng.uniform(0.12, 0.88) * height)
        py = py0 + 2.8 * math.sin(frame * 0.12 + particle * 1.7)
        radius_p = 1.15 + (particle % 3) * 0.38
        particle_alpha = np.clip((radius_p + 0.55 - np.sqrt((world_x - px) ** 2 + (world_y - py) ** 2)) * 1.6, 0.0, 1.0)
        prev_px = px - (0.38 + 0.04 * particle)
        prev_py = py0 + 2.8 * math.sin(max(0, frame - 1) * 0.12 + particle * 1.7)
        pmv_x, pmv_y = _screen_motion(
            world_x, world_y, world_x - px + prev_px, world_y - py + prev_py,
            frame, cut_frame, seed, width, height)
        composite(particle_alpha, (1.1, 0.62, 0.15), 0.18,
                  pmv_x, pmv_y, reactive_strength=1.0, transparent=True)

    # Low-amplitude transparent scrolling overlay stresses composition inputs.
    overlay = np.clip(0.32 + 0.23 * np.sin(world_x * 0.31 + frame * 0.21)
                      * np.sin(world_y * 0.17 - frame * 0.13), 0.0, 0.55)
    composite(overlay, (0.07, 0.14, 0.30), 0.14,
              reactive_strength=0.82, transparent=True)

    rgb *= np.float32(2.0 ** exposure)
    return {
        "rgb": np.maximum(rgb, 0.0).astype(np.float32),
        "depth": depth.astype(np.float32),
        "motion": np.stack((motion_x, motion_y), axis=-1).astype(np.float32),
        "reactive": reactive[..., None].astype(np.float32),
        "transparency": transparency[..., None].astype(np.float32),
    }


def render_sequence(width: int = 64, height: int = 36, scale: int = 2,
                    frames: int = 8, seed: int = 1) -> dict[str, np.ndarray | str | int]:
    if width < 16 or height < 16 or scale not in (2, 3, 4) or frames < 2:
        raise ValueError("width/height must be >=16, scale must be 2/3/4, and frames >=2")
    out_w, out_h = width * scale, height * scale
    cut_frame = frames // 2 if frames >= 4 else -1
    exposure_frame = max(1, (frames * 2) // 3)
    hr_y, hr_x = np.mgrid[0:out_h, 0:out_w]
    hr_x = hr_x.astype(np.float32) + 0.5
    hr_y = hr_y.astype(np.float32) + 0.5

    # Each LR sample averages a scale-by-scale grid inside that pixel's footprint.
    lr_y, lr_x = np.mgrid[0:height, 0:width]
    lr_x = lr_x.astype(np.float32)
    lr_y = lr_y.astype(np.float32)
    supersample_offsets = np.arange(scale, dtype=np.float32) + 0.5

    hr_frames: list[np.ndarray] = []
    lr_frames: list[np.ndarray] = []
    depth_frames: list[np.ndarray] = []
    motion_frames: list[np.ndarray] = []
    reactive_frames: list[np.ndarray] = []
    transparency_frames: list[np.ndarray] = []
    jitters: list[tuple[float, float]] = []
    exposures: list[float] = []
    resets: list[int] = []
    validities: list[int] = []

    for frame in range(frames):
        jitter_x = _halton(frame + 1, 2) - 0.5
        jitter_y = _halton(frame + 1, 3) - 0.5
        exposure = 0.72 if frame >= exposure_frame else 0.0
        reset = int(frame == 0 or frame == cut_frame)
        hr = _render(hr_x, hr_y, frame, cut_frame, seed, out_w, out_h, exposure)

        lr_rgb = np.zeros((height, width, 3), dtype=np.float32)
        for sy in supersample_offsets:
            for sx in supersample_offsets:
                sample_x = (lr_x * scale + sx + jitter_x * scale).astype(np.float32)
                sample_y = (lr_y * scale + sy + jitter_y * scale).astype(np.float32)
                sample = _render(sample_x, sample_y, frame, cut_frame, seed,
                                 out_w, out_h, exposure)
                lr_rgb += sample["rgb"]
        lr_rgb /= float(scale * scale)

        center_x = (lr_x * scale + scale * 0.5 + jitter_x * scale).astype(np.float32)
        center_y = (lr_y * scale + scale * 0.5 + jitter_y * scale).astype(np.float32)
        low_fields = _render(center_x, center_y, frame, cut_frame, seed,
                             out_w, out_h, exposure)
        # Motion uses the documented current-to-previous convention in render-pixel units.
        low_fields["motion"] /= float(scale)
        if reset:
            low_fields["motion"].fill(0.0)
        hr_frames.append(hr["rgb"].astype(np.float16))
        lr_frames.append(lr_rgb.astype(np.float16))
        depth_frames.append(low_fields["depth"][..., None].astype(np.float16))
        motion_frames.append(low_fields["motion"].astype(np.float16))
        reactive_frames.append(low_fields["reactive"].astype(np.float16))
        transparency_frames.append(low_fields["transparency"].astype(np.float16))
        jitters.append((jitter_x, jitter_y))
        exposures.append(exposure)
        resets.append(reset)
        validities.append(0 if reset else 1)

    return {
        "hr_rgb": np.stack(hr_frames),
        "lr_rgb": np.stack(lr_frames),
        "depth": np.stack(depth_frames),
        "motion": np.stack(motion_frames),
        "reactive": np.stack(reactive_frames),
        "transparency": np.stack(transparency_frames),
        "jitter": np.asarray(jitters, dtype=np.float32),
        "exposure": np.asarray(exposures, dtype=np.float32),
        "reset": np.asarray(resets, dtype=np.uint8),
        "history_valid": np.asarray(validities, dtype=np.uint8),
        "seed": seed,
        "scale": scale,
        "motion_convention": "prev_lr = curr_lr + motion + jitter_prev - jitter_curr",
    }


def generate_dataset(output: Path, sequences: int, frames: int, width: int,
                     height: int, scale: int, seed: int) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    entries = []
    for index in range(sequences):
        sequence_seed = seed + index * 104729
        data = render_sequence(width, height, scale, frames, sequence_seed)
        path = output / f"sequence_{index:04d}.npz"
        np.savez_compressed(path, **data)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        entries.append({"file": path.name, "sha256": digest, "seed": sequence_seed,
                        "frames": frames, "lr_size": [width, height],
                        "hr_size": [width * scale, height * scale]})
    manifest = {
        "format": "naviqsr-procedural-v1",
        "generator": "training/naviqsr/datasets/procedural.py",
        "motion_convention": "prev_lr = curr_lr + motion + jitter_prev - jitter_curr",
        "color_space": "linear scene RGB multiplied by exposure",
        "sequences": entries,
    }
    manifest_path = output / "index.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sequences", type=int, default=4)
    parser.add_argument("--frames", type=int, default=8)
    parser.add_argument("--width", type=int, default=64, help="LR width")
    parser.add_argument("--height", type=int, default=36, help="LR height")
    parser.add_argument("--scale", type=int, choices=(2, 3, 4), default=2)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()
    if args.sequences < 1:
        parser.error("--sequences must be positive")
    manifest = generate_dataset(args.output, args.sequences, args.frames,
                                args.width, args.height, args.scale, args.seed)
    print(json.dumps({"output": str(args.output), "sequences": len(manifest["sequences"]),
                      "frames_per_sequence": args.frames,
                      "manifest_sha256": hashlib.sha256((args.output / "index.json").read_bytes()).hexdigest()},
                     indent=2))


if __name__ == "__main__":
    main()
