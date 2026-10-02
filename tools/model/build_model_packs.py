#!/usr/bin/env python3
"""Wrap generated FP16 parameter blobs in validated aligned model containers."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from model_pack_format import build_from_files, sha256


def build_index(index_path: Path) -> dict[str, Any]:
    index_bytes = index_path.read_bytes()
    index = json.loads(index_bytes.decode("utf-8-sig"))
    if index.get("format") != "fsr4n10-fp16-parameter-pack-index-v1":
        raise ValueError("unsupported parameter-pack index format")

    for combination in index.get("combinations", []):
        manifest_path = index_path.parent / combination["manifest"]
        if sha256(manifest_path.read_bytes()) != combination["manifestSha256"].upper():
            raise ValueError(f"manifest hash mismatch: {manifest_path}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        if manifest["outputSha256"].upper() != combination["outputSha256"].upper():
            raise ValueError(f"parameter blob hash mismatch: {manifest_path.parent / manifest['output']}")
        pack_path = manifest_path.parent / "parameters.f4n10pack"
        pack_record = build_from_files(manifest_path, pack_path)
        pack_record["preset"] = manifest["preset"]
        pack_record["resolutionTier"] = manifest["resolutionTier"]
        pack_record["manifest"] = combination["manifest"]
        pack_record["manifestSha256"] = combination["manifestSha256"]
        combination["modelPack"] = pack_record["path"]
        combination["modelPackBytes"] = pack_record["bytes"]
        combination["modelPackSha256"] = pack_record["sha256"]

    index["containerFormat"] = "fsr4n10-model-pack-v1"
    index["modelPackCount"] = len(index["combinations"])
    index["modelPackBytes"] = sum(item["modelPackBytes"] for item in index["combinations"])
    index_path.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return index


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True, help="parameter-pack index created by extract_fp16_weights.py")
    args = parser.parse_args()
    try:
        index = build_index(args.index)
    except (KeyError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(
        f"Built {index['modelPackCount']} versioned FP16 model packs "
        f"({sum(item['modelPackBytes'] for item in index['combinations'])} bytes total): {args.index}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
