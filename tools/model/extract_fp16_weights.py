#!/usr/bin/env python3
"""Extract and dequantize pinned FSR4 I8 convolution weights to FP16."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import re
import struct
from dataclasses import dataclass
from pathlib import Path


PRESETS = ("native", "quality", "balanced", "performance", "drs", "ultraperf")
TIERS = ("1080", "2160", "4320")

WORD_ARRAY = re.compile(
    r"static\s+const\s+uint\s+(?P<name>\w+)\[(?P<count>\d+)\]\s*=\s*\{(?P<body>.*?)\};",
    re.DOTALL,
)
CONSTANT_STORAGE = re.compile(
    r"const\s+ConstantBufferStorage\s*<\s*(?P<count>\d+)\s*>\s*"
    r"(?P<storage>\w+)\s*=\s*\{\s*(?P<array>\w+)\s*\}\s*;"
)
INITIALIZER_STORAGE = re.compile(
    r"const\s+BufferStorage\s+(?P<storage>\w+)\s*=\s*\{\s*InitializerBuffer\s*\}\s*;"
)
QUANTIZED_WEIGHT = re.compile(
    r"const\s+QuantizedTensor4i8_(?P<layout>\w+)\s*<\s*"
    r"(?:ConstantBufferStorage\s*<\s*\d+\s*>|BufferStorage)\s*>\s*"
    r"(?P<name>\w+)\s*=\s*\{(?P<body>.*?)\};",
    re.DOTALL,
)
INTEGER = re.compile(r"(?:0[xX][0-9a-fA-F]+|(?<![\w.])-?\d+)")
FLOAT = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")


@dataclass(frozen=True)
class QuantizedWeight:
    name: str
    layout: str
    shape: tuple[int, int, int, int]
    strides: tuple[int, int, int, int]
    byte_offset: int
    scale: float
    storage_name: str


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def to_half(value: float) -> float:
    return struct.unpack("<e", struct.pack("<e", value))[0]


def dequantize_i8(value: int, scale: float) -> bytes:
    """Match the source I8 loader: half(int8) * half(scale), rounded to half."""
    return struct.pack("<e", to_half(float(value) * to_half(scale)))


def _uint4(body: str, label: str) -> tuple[int, int, int, int]:
    match = re.search(rf"uint4\(([^)]*)\)\s*,\s*//\s*{re.escape(label)}", body)
    if not match:
        raise ValueError(f"missing uint4 field {label}")
    values = tuple(int(value.strip(), 0) for value in match.group(1).split(","))
    if len(values) != 4:
        raise ValueError(f"{label} must contain four values")
    return values  # type: ignore[return-value]


def parse_source(source_text: str) -> tuple[list[QuantizedWeight], dict[str, bytes], dict[str, tuple[str, str]]]:
    word_arrays: dict[str, bytes] = {}
    for match in WORD_ARRAY.finditer(source_text):
        body = re.sub(r"//[^\r\n]*", "", match.group("body"))
        values = [int(value, 0) & 0xFFFFFFFF for value in INTEGER.findall(body)]
        expected_count = int(match.group("count"))
        if len(values) != expected_count:
            raise ValueError(f"{match.group('name')}: expected {expected_count} uint dwords, parsed {len(values)}")
        packed = struct.pack(f"<{expected_count}I", *values)
        name = match.group("name")
        if name in word_arrays and word_arrays[name] != packed:
            raise ValueError(f"duplicate uint array has different values: {name}")
        word_arrays[name] = packed

    storage_bindings: dict[str, tuple[str, str]] = {}
    for match in CONSTANT_STORAGE.finditer(source_text):
        storage = match.group("storage")
        array = match.group("array")
        count = int(match.group("count"))
        if array not in word_arrays:
            continue
        if len(word_arrays[array]) != count * 4:
            raise ValueError(f"{storage}: dword array size disagrees with ConstantBufferStorage")
        storage_bindings[storage] = ("embedded", array)
    for match in INITIALIZER_STORAGE.finditer(source_text):
        storage_bindings[match.group("storage")] = ("initializer", "")

    weights: list[QuantizedWeight] = []
    for match in QUANTIZED_WEIGHT.finditer(source_text):
        name = match.group("name")
        if "weight" not in name.lower():
            continue
        body = match.group("body")
        storage_match = re.search(r",\s*(?P<storage>\w+)\s*$", body)
        if not storage_match:
            raise ValueError(f"{name}: cannot read backing storage and quantization scale")
        storage_name = storage_match.group("storage")
        scale_prefix = body[: storage_match.start()]
        scale_values = list(FLOAT.finditer(scale_prefix))
        if not scale_values:
            raise ValueError(f"{name}: quantization scale is missing")
        scale = float(scale_values[-1].group(0))
        byte_offset_match = re.search(r"(-?\d+)\s*,\s*//\s*threadGroupStorageByteOffset", body)
        if not byte_offset_match:
            raise ValueError(f"{name}: byte offset is missing")
        shape = _uint4(body, "logicalSize")
        strides = _uint4(body, "storageByteStrides")
        if any(size <= 0 for size in shape) or any(stride < 0 for stride in strides):
            raise ValueError(f"{name}: dimensions or byte strides are invalid")
        if storage_name not in storage_bindings:
            raise ValueError(f"{name}: backing storage {storage_name} is not recognized")
        weights.append(
            QuantizedWeight(
                name=name,
                layout=match.group("layout"),
                shape=shape,
                strides=strides,
                byte_offset=int(byte_offset_match.group(1)),
                scale=scale,
                storage_name=storage_name,
            )
        )
    return weights, word_arrays, storage_bindings


def convert_weights(
    source_text: str, initializer_data: bytes
) -> tuple[bytes, list[dict[str, object]]]:
    weights, arrays, bindings = parse_source(source_text)
    if not weights:
        raise ValueError("no quantized rank-4 weight tensors were found")

    output = bytearray()
    manifest_tensors: list[dict[str, object]] = []
    for tensor in weights:
        storage_kind, array_name = bindings[tensor.storage_name]
        source_data = arrays[array_name] if storage_kind == "embedded" else initializer_data
        maximum_source_byte = tensor.byte_offset + sum(
            (size - 1) * stride for size, stride in zip(tensor.shape, tensor.strides)
        )
        if tensor.byte_offset < 0 or maximum_source_byte >= len(source_data):
            raise ValueError(
                f"{tensor.name}: source byte range [{tensor.byte_offset}, {maximum_source_byte}] "
                f"exceeds {storage_kind} storage size {len(source_data)}"
            )

        pack_offset = len(output)
        for coordinate in itertools.product(*(range(size) for size in tensor.shape)):
            byte_index = tensor.byte_offset + sum(c * stride for c, stride in zip(coordinate, tensor.strides))
            quantized_value = int.from_bytes(source_data[byte_index : byte_index + 1], "little", signed=True)
            output.extend(dequantize_i8(quantized_value, tensor.scale))

        element_count = 1
        for dimension in tensor.shape:
            element_count *= dimension
        manifest_tensors.append(
            {
                "name": tensor.name,
                "layout": tensor.layout,
                "shape": list(tensor.shape),
                "sourceByteStrides": list(tensor.strides),
                "sourceByteOffset": tensor.byte_offset,
                "sourceStorage": storage_kind,
                "quantizationScaleF32": tensor.scale,
                "conversion": "f16(int8_value * f16(quantizationScaleF32))",
                "elementCount": element_count,
                "packOffsetBytes": pack_offset,
                "packSizeBytes": element_count * 2,
            }
        )

    return bytes(output), manifest_tensors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fsr4-root", type=Path, required=True)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--preset", choices=PRESETS, default="native")
    parser.add_argument("--tier", choices=TIERS, default="1080")
    args = parser.parse_args()

    fsr4_root = args.fsr4_root.resolve()
    model_dir = fsr4_root / "internal" / "shaders" / f"fsr4_model_v07_i8_{args.preset}"
    source_path = model_dir / f"passes_{args.tier}.hlsl"
    initializer_path = model_dir / "initializers.bin"
    if not source_path.is_file() or not initializer_path.is_file():
        parser.error(f"pinned model source or initializers are missing under {model_dir}")

    source_data = source_path.read_bytes()
    initializer_data = initializer_path.read_bytes()
    try:
        pack_data, tensors = convert_weights(source_data.decode("utf-8"), initializer_data)
    except (UnicodeDecodeError, ValueError) as error:
        parser.error(str(error))

    lock = json.loads(args.lock.read_text(encoding="utf-8-sig"))
    upstream_commit = lock["fsr4Source"]["actualCommit"]
    args.output.mkdir(parents=True, exist_ok=True)
    pack_path = args.output / "weights.fp16.bin"
    pack_path.write_bytes(pack_data)
    manifest = {
        "format": "fsr4n10-i8-dequantized-fp16-weight-pack-v1",
        "sourceBackend": "upstream_i8",
        "scope": "QuantizedTensor4i8 weight tensors only; native FP16 weights, biases, and runtime tensors are not included.",
        "completeModelWeightsIncluded": False,
        "preset": args.preset,
        "resolutionTier": args.tier,
        "upstreamCommit": upstream_commit,
        "source": source_path.relative_to(fsr4_root).as_posix(),
        "sourceSha256": sha256(source_data),
        "initializerSource": initializer_path.relative_to(fsr4_root).as_posix(),
        "initializerSha256": sha256(initializer_data),
        "output": pack_path.name,
        "outputBytes": len(pack_data),
        "outputSha256": sha256(pack_data),
        "tensorCount": len(tensors),
        "tensorElementCount": sum(int(tensor["elementCount"]) for tensor in tensors),
        "tensors": tensors,
    }
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"Converted {manifest['tensorCount']} I8 weight tensors "
        f"({manifest['tensorElementCount']} values) to {pack_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
