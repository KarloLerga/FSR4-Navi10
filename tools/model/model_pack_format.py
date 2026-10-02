"""Deterministic FSR4-Navi10 parameter container writer."""

from __future__ import annotations

import hashlib
import json
import math
import struct
from pathlib import Path
from typing import Any


MAGIC = b"F4N10PK\0"
VERSION = 1
HEADER = struct.Struct("<8sII32s32sIIQQQQ")
TENSOR_RECORD = struct.Struct("<QIIII4IIIQQffff")
ALIGNMENT = 16


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def _align(value: int, alignment: int = ALIGNMENT) -> int:
    return (value + alignment - 1) & ~(alignment - 1)


def _name_hash(name: str) -> int:
    value = 0xCBF29CE484222325
    for byte in name.encode("utf-8"):
        value ^= byte
        value = (value * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return value


def build_model_pack(manifest_bytes: bytes, parameter_bytes: bytes) -> bytes:
    """Build a little-endian, 16-byte-aligned container for a parameter manifest."""
    manifest = json.loads(manifest_bytes.decode("utf-8-sig"))
    if manifest.get("format") != "fsr4n10-fp16-parameter-pack-v1":
        raise ValueError("unsupported parameter manifest format")
    if manifest.get("outputBytes") != len(parameter_bytes):
        raise ValueError("parameter blob size disagrees with manifest")
    if manifest.get("outputSha256", "").upper() != sha256(parameter_bytes):
        raise ValueError("parameter blob hash disagrees with manifest")

    tensor_metadata = manifest.get("tensors")
    if not isinstance(tensor_metadata, list) or not tensor_metadata:
        raise ValueError("manifest must contain at least one tensor")

    names = bytearray()
    checked_tensors: list[dict[str, Any]] = []
    source_ranges: list[tuple[int, int, str]] = []
    tensor_names: set[str] = set()
    if manifest.get("tensorCount") != len(tensor_metadata):
        raise ValueError("tensor count disagrees with manifest records")
    for tensor in tensor_metadata:
        name = tensor.get("name")
        shape = tensor.get("shape")
        if not isinstance(name, str) or not name or "\0" in name:
            raise ValueError("tensor names must be nonempty UTF-8 strings without NUL")
        if name in tensor_names:
            raise ValueError(f"duplicate tensor name: {name}")
        tensor_names.add(name)
        if not isinstance(shape, list) or not 1 <= len(shape) <= 4:
            raise ValueError(f"{name}: tensor rank must be between one and four")
        if any(not isinstance(dimension, int) or dimension <= 0 for dimension in shape):
            raise ValueError(f"{name}: dimensions must be positive integers")
        element_count = math.prod(shape)
        byte_size = element_count * 2
        raw_offset = tensor.get("packOffsetBytes")
        if not isinstance(raw_offset, int) or raw_offset < 0:
            raise ValueError(f"{name}: invalid parameter offset")
        if tensor.get("elementCount") != element_count or tensor.get("packSizeBytes") != byte_size:
            raise ValueError(f"{name}: shape does not match manifest element or byte count")
        if raw_offset > len(parameter_bytes) or byte_size > len(parameter_bytes) - raw_offset:
            raise ValueError(f"{name}: parameter range exceeds the raw blob")
        source_ranges.append((raw_offset, raw_offset + byte_size, name))
        if tensor.get("sourceDType") not in ("int8", "float16"):
            raise ValueError(f"{name}: unsupported source dtype")

        name_offset = len(names)
        encoded_name = name.encode("utf-8")
        names.extend(encoded_name)
        names.append(0)
        checked_tensors.append(
            {
                "name": name,
                "nameHash": _name_hash(name),
                "nameOffset": name_offset,
                "shape": shape,
                "rawOffset": raw_offset,
                "byteSize": byte_size,
                "sourceScale": tensor.get("quantizationScaleF32"),
            }
        )

    source_ranges.sort()
    for previous, current in zip(source_ranges, source_ranges[1:]):
        if current[0] < previous[1]:
            raise ValueError(f"parameter ranges overlap: {previous[2]} and {current[2]}")

    source_hash = bytes.fromhex(manifest["sourceSha256"])
    if len(source_hash) != 32:
        raise ValueError("source SHA-256 must contain 32 bytes")
    manifest_hash = hashlib.sha256(manifest_bytes).digest()
    tensor_table_offset = HEADER.size
    string_table_offset = tensor_table_offset + len(checked_tensors) * TENSOR_RECORD.size
    data_offset = _align(string_table_offset + len(names))

    output = bytearray(data_offset)
    output[string_table_offset : string_table_offset + len(names)] = names
    records: list[bytes] = []
    cursor = data_offset
    for tensor in checked_tensors:
        cursor = _align(cursor)
        shape = tensor["shape"]
        padded_shape = shape + [0] * (4 - len(shape))
        scale = tensor["sourceScale"]
        if scale is None:
            scale = 0.0
        if not isinstance(scale, (int, float)) or not math.isfinite(scale):
            raise ValueError(f"{tensor['name']}: source scale must be finite")
        try:
            record = TENSOR_RECORD.pack(
                tensor["nameHash"],
                tensor["nameOffset"],
                1,  # F16
                0,  # canonical logical-order layout
                len(shape),
                *padded_shape,
                ALIGNMENT,
                0,  # no additional compatibility flags are currently encoded
                cursor,
                tensor["byteSize"],
                float(scale),
                0.0,
                0.0,
                0.0,
            )
        except (OverflowError, struct.error) as error:
            raise ValueError(f"{tensor['name']}: metadata is outside the pack format range") from error
        records.append(record)
        if cursor < len(output):
            raise ValueError("tensor payload overlaps the model-pack metadata")
        output.extend(b"\0" * (cursor - len(output)))
        start = tensor["rawOffset"]
        end = start + tensor["byteSize"]
        output.extend(parameter_bytes[start:end])
        cursor += tensor["byteSize"]

    for index, record in enumerate(records):
        start = tensor_table_offset + index * TENSOR_RECORD.size
        output[start : start + TENSOR_RECORD.size] = record

    header = HEADER.pack(
        MAGIC,
        VERSION,
        HEADER.size,
        source_hash,
        manifest_hash,
        len(checked_tensors),
        0,
        tensor_table_offset,
        string_table_offset,
        data_offset,
        len(output),
    )
    output[: HEADER.size] = header
    return bytes(output)


def build_from_files(manifest_path: Path, output_path: Path) -> dict[str, Any]:
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes.decode("utf-8-sig"))
    parameter_path = manifest_path.parent / manifest["output"]
    parameter_bytes = parameter_path.read_bytes()
    pack = build_model_pack(manifest_bytes, parameter_bytes)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(pack)
    return {
        "path": output_path.name,
        "bytes": len(pack),
        "sha256": sha256(pack),
        "manifestSha256": sha256(manifest_bytes),
        "tensorCount": manifest["tensorCount"],
    }
