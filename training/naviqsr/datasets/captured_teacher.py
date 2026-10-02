"""Validate and load full-FSR4 teacher captures in the canonical NPZ schema."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np


REQUIRED = {"lr_rgb", "hr_rgb", "depth", "motion", "jitter", "teacher_hr"}


def load_teacher_capture(path: Path) -> dict[str, np.ndarray | dict[str, object]]:
    with np.load(path, allow_pickle=False) as archive:
        missing = REQUIRED.difference(archive.files)
        if missing:
            raise ValueError(f"teacher capture is missing required arrays: {sorted(missing)}")
        arrays = {name: archive[name].copy() for name in archive.files}
    frames = arrays["lr_rgb"].shape[0]
    for name in ("hr_rgb", "depth", "motion", "jitter", "teacher_hr"):
        if arrays[name].shape[0] != frames:
            raise ValueError(f"capture frame count mismatch for {name}")
    if arrays["teacher_hr"].shape != arrays["hr_rgb"].shape:
        raise ValueError("teacher output must match the high-resolution target shape")
    metadata = {"file": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "frames": frames,
                "feature_keys": sorted(key for key in arrays if key.startswith("teacher_feature__"))}
    return {**arrays, "capture_metadata": metadata}


def write_capture_index(directory: Path, output: Path) -> None:
    files = sorted(directory.glob("*.npz"))
    records = []
    for path in files:
        arrays = load_teacher_capture(path)
        metadata = arrays["capture_metadata"]
        records.append({"file": path.name, "sha256": metadata["sha256"],
                        "frames": metadata["frames"], "features": metadata["feature_keys"]})
    output.write_text(json.dumps({"format": "naviqsr-teacher-capture-index-v1",
                                  "captures": records}, indent=2) + "\n", encoding="utf-8")
