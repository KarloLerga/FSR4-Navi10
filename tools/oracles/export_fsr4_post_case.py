#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import struct
import sys
import zipfile
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
from tools.teacher.capture_format import validate_capture  # noqa: E402

MAGIC = b"F4POST01"
VERSION = 1
HEADER = struct.Struct("<8s7I4f")


def load_capture(path: Path):
    validate_capture(path)
    with zipfile.ZipFile(path, "r") as z:
        manifest = json.loads(z.read("capture.json"))
        arrays = {}
        for name in ("current_reconstruction_source", "reprojected_history",
                     "raw_model_parameters", "final_rgb"):
            d = manifest["arrays"][name]
            arrays[name] = np.frombuffer(z.read(d["path"]), dtype=np.dtype(d["dtype"])).reshape(d["shape"])
    return manifest["metadata"], arrays


def rgba32(a: np.ndarray, alpha: float = 0.0) -> np.ndarray:
    a = np.asarray(a, dtype=np.float32)
    out = np.empty((*a.shape[:-1], 4), np.float32)
    out[..., :a.shape[-1]] = a
    if a.shape[-1] < 4:
        out[..., a.shape[-1]:] = np.float32(alpha)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("capture", type=Path)
    ap.add_argument("output", type=Path)
    args = ap.parse_args()

    meta, a = load_capture(args.capture)
    rw, rh = int(meta["render_width"]), int(meta["render_height"])
    ow, oh = int(meta["output_width"]), int(meta["output_height"])
    exposure = float(meta["exposure"])
    pre = float(meta["pre_exposure"])
    if exposure == 0.0:
        exposure = 1.0
    exposure_value = exposure / pre
    jx, jy = map(float, meta["jitter_current"])

    source = rgba32(a["current_reconstruction_source"])
    history = rgba32(a["reprojected_history"])
    params = rgba32(a["raw_model_parameters"])
    reference = rgba32(a["final_rgb"])

    header = HEADER.pack(MAGIC, VERSION, rw, rh, ow, oh, 0, 0,
                         jx, jy, exposure_value, 0.0)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("wb") as f:
        f.write(header)
        for arr in (source, history, params, reference):
            f.write(np.ascontiguousarray(arr, dtype="<f4").tobytes())

    print(f"wrote {args.output}: render={rw}x{rh}, output={ow}x{oh}, exposure={exposure_value:g}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
