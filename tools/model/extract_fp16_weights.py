#!/usr/bin/env python3
"""Extract pinned FSR4 model weights and biases into deterministic FP16 blobs."""

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
NATIVE_FP16_WEIGHT = re.compile(
    r"const\s+Tensor4h_(?P<layout>\w+)\s*<\s*"
    r"(?:ConstantBufferStorage\s*<\s*\d+\s*>|BufferStorage)\s*>\s*"
    r"(?P<name>\w+)\s*=\s*\{(?P<body>.*?)\};",
    re.DOTALL,
)
FP16_BIAS = re.compile(
    r"const\s+Tensor1h\s*<\s*(?:ConstantBufferStorage\s*<\s*\d+\s*>|BufferStorage)\s*>\s*"
    r"(?P<name>\w+)\s*=\s*\{(?P<body>.*?)\};",
    re.DOTALL,
)
INTEGER = re.compile(r"(?:0[xX][0-9a-fA-F]+|(?<![\w.])-?\d+)")
FLOAT = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")


@dataclass(frozen=True)
class ModelTensor:
    name: str
    tensor_type: str
    layout: str
    shape: tuple[int, ...]
    strides: tuple[int, ...]
    byte_offset: int
    source_dtype: str
    scale: float | None
    storage_name: str
    source_order: int


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def to_half(value: float) -> float:
    return struct.unpack("<e", struct.pack("<e", value))[0]


def dequantize_i8(value: int, scale: float) -> bytes:
    """Expand I8 with a half-rounded scale and half-rounded product."""
    return struct.pack("<e", to_half(float(value) * to_half(scale)))


def _uint4(body: str, label: str) -> tuple[int, int, int, int]:
    match = re.search(rf"uint4\(([^)]*)\)\s*,\s*//\s*{re.escape(label)}", body)
    if not match:
        raise ValueError(f"missing uint4 field {label}")
    values = tuple(int(value.strip(), 0) for value in match.group(1).split(","))
    if len(values) != 4:
        raise ValueError(f"{label} must contain four values")
    return values  # type: ignore[return-value]


def _scalar(body: str, label: str) -> int:
    match = re.search(rf"(-?\d+)\s*,\s*//\s*{re.escape(label)}", body)
    if not match:
        raise ValueError(f"missing scalar field {label}")
    return int(match.group(1))


def _storage_name(body: str, tensor_name: str) -> str:
    match = re.search(r"(?P<storage>\w+)\s*$", body)
    if not match:
        raise ValueError(f"{tensor_name}: backing storage reference is missing")
    return match.group("storage")


def _byte_offset(body: str, tensor_name: str) -> int:
    match = re.search(r"(-?\d+)\s*,\s*//\s*threadGroupStorageByteOffset", body)
    if not match:
        raise ValueError(f"{tensor_name}: byte offset is missing")
    return int(match.group(1))


def parse_source(source_text: str) -> tuple[list[ModelTensor], dict[str, bytes], dict[str, tuple[str, str]]]:
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

    tensors: list[ModelTensor] = []
    for match in QUANTIZED_WEIGHT.finditer(source_text):
        name = match.group("name")
        if "weight" not in name.lower():
            continue
        body = match.group("body")
        storage_name = _storage_name(body, name)
        storage_match = re.search(r",\s*\w+\s*$", body)
        assert storage_match is not None
        scale_prefix = body[: storage_match.start()]
        scale_values = list(FLOAT.finditer(scale_prefix))
        if not scale_values:
            raise ValueError(f"{name}: quantization scale is missing")
        scale = float(scale_values[-1].group(0))
        shape = _uint4(body, "logicalSize")
        strides = _uint4(body, "storageByteStrides")
        if any(size <= 0 for size in shape) or any(stride < 0 for stride in strides):
            raise ValueError(f"{name}: dimensions or byte strides are invalid")
        if storage_name not in storage_bindings:
            raise ValueError(f"{name}: backing storage {storage_name} is not recognized")
        tensors.append(
            ModelTensor(
                name=name,
                tensor_type=f"QuantizedTensor4i8_{match.group('layout')}",
                layout=match.group("layout"),
                shape=shape,
                strides=strides,
                byte_offset=_byte_offset(body, name),
                source_dtype="int8",
                scale=scale,
                storage_name=storage_name,
                source_order=match.start(),
            )
        )

    for match in NATIVE_FP16_WEIGHT.finditer(source_text):
        name = match.group("name")
        if "weight" not in name.lower():
            continue
        body = match.group("body")
        storage_name = _storage_name(body, name)
        shape = _uint4(body, "logicalSize")
        strides = _uint4(body, "storageByteStrides")
        if any(size <= 0 for size in shape) or any(stride < 0 for stride in strides):
            raise ValueError(f"{name}: dimensions or byte strides are invalid")
        if storage_name not in storage_bindings:
            raise ValueError(f"{name}: backing storage {storage_name} is not recognized")
        tensors.append(
            ModelTensor(
                name=name,
                tensor_type=f"Tensor4h_{match.group('layout')}",
                layout=match.group("layout"),
                shape=shape,
                strides=strides,
                byte_offset=_byte_offset(body, name),
                source_dtype="float16",
                scale=None,
                storage_name=storage_name,
                source_order=match.start(),
            )
        )

    for match in FP16_BIAS.finditer(source_text):
        name = match.group("name")
        if "bias" not in name.lower():
            continue
        body = match.group("body")
        storage_name = _storage_name(body, name)
        shape = (_scalar(body, "logicalSize"),)
        strides = (_scalar(body, "storageByteStrides"),)
        if shape[0] <= 0 or strides[0] < 0:
            raise ValueError(f"{name}: dimensions or byte stride are invalid")
        if storage_name not in storage_bindings:
            raise ValueError(f"{name}: backing storage {storage_name} is not recognized")
        tensors.append(
            ModelTensor(
                name=name,
                tensor_type="Tensor1h",
                layout="vector",
                shape=shape,
                strides=strides,
                byte_offset=_byte_offset(body, name),
                source_dtype="float16",
                scale=None,
                storage_name=storage_name,
                source_order=match.start(),
            )
        )

    tensors.sort(key=lambda tensor: tensor.source_order)
    return tensors, word_arrays, storage_bindings


def convert_model_parameters(
    source_text: str, initializer_data: bytes
) -> tuple[bytes, list[dict[str, object]]]:
    tensors, arrays, bindings = parse_source(source_text)
    if not tensors:
        raise ValueError("no supported model weights or biases were found")

    output = bytearray()
    manifest_tensors: list[dict[str, object]] = []
    for tensor in tensors:
        storage_kind, array_name = bindings[tensor.storage_name]
        source_data = arrays[array_name] if storage_kind == "embedded" else initializer_data
        source_element_bytes = 1 if tensor.source_dtype == "int8" else 2
        maximum_source_byte = tensor.byte_offset + sum(
            (size - 1) * stride for size, stride in zip(tensor.shape, tensor.strides)
        ) + source_element_bytes - 1
        if tensor.byte_offset < 0 or maximum_source_byte >= len(source_data):
            raise ValueError(
                f"{tensor.name}: source byte range [{tensor.byte_offset}, {maximum_source_byte}] "
                f"exceeds {storage_kind} storage size {len(source_data)}"
            )

        pack_offset = len(output)
        for coordinate in itertools.product(*(range(size) for size in tensor.shape)):
            byte_index = tensor.byte_offset + sum(c * stride for c, stride in zip(coordinate, tensor.strides))
            source_value = source_data[byte_index : byte_index + source_element_bytes]
            if tensor.source_dtype == "int8":
                quantized_value = int.from_bytes(source_value, "little", signed=True)
                assert tensor.scale is not None
                output.extend(dequantize_i8(quantized_value, tensor.scale))
            else:
                output.extend(source_value)

        element_count = 1
        for dimension in tensor.shape:
            element_count *= dimension
        manifest_tensors.append(
            {
                "name": tensor.name,
                "tensorType": tensor.tensor_type,
                "sourceDType": tensor.source_dtype,
                "layout": tensor.layout,
                "shape": list(tensor.shape),
                "sourceByteStrides": list(tensor.strides),
                "sourceByteOffset": tensor.byte_offset,
                "sourceStorage": storage_kind,
                "quantizationScaleF32": tensor.scale,
                "conversion": (
                    "f16(int8_value * f16(quantizationScaleF32))"
                    if tensor.source_dtype == "int8"
                    else "copy_fp16_bits"
                ),
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
    parser.add_argument("--preset", choices=(*PRESETS, "all"), default="native")
    parser.add_argument("--tier", choices=(*TIERS, "all"), default="1080")
    args = parser.parse_args()

    fsr4_root = args.fsr4_root.resolve()
    lock = json.loads(args.lock.read_text(encoding="utf-8-sig"))
    upstream_commit = lock["fsr4Source"]["actualCommit"]
    args.output.mkdir(parents=True, exist_ok=True)

    presets = PRESETS if args.preset == "all" else (args.preset,)
    tiers = TIERS if args.tier == "all" else (args.tier,)
    generated_manifests: list[Path] = []
    for preset in presets:
        for tier in tiers:
            model_dir = fsr4_root / "internal" / "shaders" / f"fsr4_model_v07_i8_{preset}"
            source_path = model_dir / f"passes_{tier}.hlsl"
            initializer_path = model_dir / "initializers.bin"
            if not source_path.is_file() or not initializer_path.is_file():
                parser.error(f"pinned model source or initializers are missing under {model_dir}")

            source_data = source_path.read_bytes()
            initializer_data = initializer_path.read_bytes()
            try:
                pack_data, tensors = convert_model_parameters(
                    source_data.decode("utf-8-sig"), initializer_data
                )
            except (UnicodeDecodeError, ValueError) as error:
                parser.error(f"{preset}/{tier}: {error}")

            output_dir = args.output / preset / tier
            output_dir.mkdir(parents=True, exist_ok=True)
            pack_path = output_dir / "parameters.fp16.bin"
            pack_path.write_bytes(pack_data)
            manifest = {
                "format": "fsr4n10-fp16-parameter-pack-v1",
                "sourceBackend": "upstream_i8",
                "scope": "Rank-4 source weight tensors and rank-1 source bias tensors; runtime activation tensors and shader bindings are not included. I8 values use f16(int8_value * f16(scale)); source operators may apply scale at different boundaries, so this parameter expansion does not imply end-to-end numerical equivalence.",
                "preset": preset,
                "resolutionTier": tier,
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
                "parameterCounts": {
                    "quantizedI8Weights": sum(tensor["sourceDType"] == "int8" for tensor in tensors),
                    "nativeFp16Weights": sum(tensor["tensorType"].startswith("Tensor4h_") for tensor in tensors),
                    "fp16Biases": sum(tensor["tensorType"] == "Tensor1h" for tensor in tensors),
                },
                "tensors": tensors,
            }
            manifest_path = output_dir / "manifest.json"
            manifest_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            generated_manifests.append(manifest_path)

    combinations = []
    tensor_count = 0
    parameter_bytes = 0
    for manifest_path in generated_manifests:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        tensor_count += int(manifest["tensorCount"])
        parameter_bytes += int(manifest["outputBytes"])
        combinations.append(
            {
                "preset": manifest["preset"],
                "resolutionTier": manifest["resolutionTier"],
                "manifest": manifest_path.relative_to(args.output).as_posix(),
                "manifestSha256": sha256(manifest_path.read_bytes()),
                "outputSha256": manifest["outputSha256"],
            }
        )
    index = {
        "format": "fsr4n10-fp16-parameter-pack-index-v1",
        "upstreamCommit": upstream_commit,
        "combinationCount": len(combinations),
        "tensorCount": tensor_count,
        "outputBytes": parameter_bytes,
        "combinations": combinations,
    }
    index_path = args.output / "index.json"
    index_path.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"Indexed {tensor_count} parameter tensors across {len(combinations)} preset/tier combinations "
        f"({parameter_bytes} bytes total): {index_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
