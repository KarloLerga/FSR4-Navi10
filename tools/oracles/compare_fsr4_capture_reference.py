#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
from tools.teacher.capture_format import validate_capture  # noqa: E402


def load_pair(path: Path):
    validate_capture(path)
    with zipfile.ZipFile(path, "r") as z:
        m = json.loads(z.read("capture.json"))
        if "reference_rgb" not in m["arrays"]:
            raise ValueError(f"{path}: reference_rgb missing; regenerate capture after patch")
        out = {}
        for name in ("final_rgb", "reference_rgb"):
            d = m["arrays"][name]
            out[name] = np.frombuffer(z.read(d["path"]), dtype=np.dtype(d["dtype"])).reshape(d["shape"]).astype(np.float32)
        return int(m["metadata"]["frame_index"]), out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("captures", nargs="+", type=Path)
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()

    frames = []
    for p in args.captures:
        idx, a = load_pair(p)
        d = np.abs(a["final_rgb"] - a["reference_rgb"])
        frames.append({
            "frame_index": idx,
            "exact_fraction": float(np.mean(a["final_rgb"] == a["reference_rgb"])),
            "within_1e_3_fraction": float(np.mean(d <= 1e-3)),
            "max_absolute_error": float(d.max(initial=0)),
            "mean_absolute_error": float(d.mean()),
            "rms_error": float(np.sqrt(np.mean(d * d))),
        })

    close = all(f["within_1e_3_fraction"] >= 0.99999 and f["max_absolute_error"] <= 0.0025
                for f in frames)
    report = {
        "schema": "f4n10.instrumented-reference-numeric.v1",
        "capture_count": len(frames),
        "numerically_close": close,
        "frames": frames,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"numerically_close": close, "frames": len(frames)}))
    return 0 if close else 2


if __name__ == "__main__":
    raise SystemExit(main())
