"""Bounds/hash/alignment validator for NQSRPK1 FP16 model packs."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path


MAGIC = b"NQSRPK1\0"
PREFIX = struct.Struct("<8sII")


def validate(path: Path) -> dict[str, object]:
    blob = path.read_bytes()
    if len(blob) < PREFIX.size:
        raise ValueError("truncated model-pack prefix")
    magic, version, header_size = PREFIX.unpack_from(blob)
    if magic != MAGIC or version != 1:
        raise ValueError("unsupported model-pack magic/version")
    header_end = PREFIX.size + header_size
    if header_end > len(blob):
        raise ValueError("truncated model-pack header")
    header = json.loads(blob[PREFIX.size:header_end].decode("utf-8"))
    payload = memoryview(blob)[header_end:]
    if len(payload) != int(header["payload_bytes"]):
        raise ValueError("payload size does not match header")
    ranges = []
    for tensor in header["tensors"]:
        offset, size = int(tensor["offset"]), int(tensor["nbytes"])
        if offset % int(header["alignment"]):
            raise ValueError(f"misaligned tensor: {tensor['name']}")
        if offset < 0 or size < 0 or offset + size > len(payload):
            raise ValueError(f"tensor outside payload: {tensor['name']}")
        if tensor["dtype"] != "float16":
            raise ValueError(f"unexpected tensor dtype: {tensor['name']}")
        expected_values = 1
        for dimension in tensor["shape"]:
            expected_values *= int(dimension)
        if size != expected_values * 2:
            raise ValueError(f"tensor shape/size mismatch: {tensor['name']}")
        digest = hashlib.sha256(payload[offset:offset + size]).hexdigest()
        if digest != tensor["sha256"]:
            raise ValueError(f"tensor hash mismatch: {tensor['name']}")
        ranges.append((offset, offset + size, tensor["name"]))
    ranges.sort()
    for left, right in zip(ranges, ranges[1:]):
        if left[1] > right[0]:
            raise ValueError(f"overlapping tensor ranges: {left[2]} and {right[2]}")
    return {"path": str(path), "sha256": hashlib.sha256(blob).hexdigest(),
            "size_bytes": len(blob), "tensor_count": len(ranges),
            "payload_bytes": len(payload), "valid": True}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pack", type=Path)
    args = parser.parse_args()
    print(json.dumps(validate(args.pack), indent=2))


if __name__ == "__main__":
    main()
