"""Deterministic f4n10.sequence.v2 reader, validator and packer."""

from __future__ import annotations

import hashlib
import json
import math
import re
import struct
import zipfile
import zlib
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO


SCHEMA = "f4n10.sequence.v2"
MAGIC = b"F4N10SQ2"
VERSION = 2
HEADER = struct.Struct("<8s10IQ4I64s32s32s")
FRAME = struct.Struct("<IIf6f4I160s")
SEQUENCE_HASH_OFFSET = 168
MAX_MANIFEST_BYTES = 16 * 1024 * 1024
MAX_FRAME_COUNT = 100_000
MAX_DIMENSION = 16_384
MAX_ARRAY_BYTES = 1024 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024 * 1024
CHUNK_BYTES = 1024 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SEQUENCE_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,63}$")

PRESETS = {
    "native": (0, 1, 1),
    "quality": (1, 3, 2),
    "balanced": (2, 17, 10),
    "performance": (3, 2, 1),
    "ultra_performance": (4, 3, 1),
}
MOTION_CONVENTIONS = {"current_to_previous_render_pixels_unjittered": 1}
DEPTH_CONVENTIONS = {"forward_zero_to_one": 1}
SOURCE_KINDS = {"renderer_capture": 1, "procedural_synthetic": 2, "imported_buffers": 3, "test_fixture": 4}
ARRAYS = {
    "color": ("<f2", 8),
    "depth": ("<f4", 4),
    "motion_vectors": ("<f2", 4),
    "reactive_mask": ("|u1", 1),
    "transparency_composition_mask": ("|u1", 1),
}
ARRAY_ORDER = tuple(ARRAYS)
FLOAT_DTYPES = {"<f2": (2, "e"), "<f4": (4, "f")}
ARRAY_CHANNELS = {"color": 4, "depth": 1, "motion_vectors": 2,
                  "reactive_mask": 1, "transparency_composition_mask": 1}
FRAME_RESET = 1 << 0
FRAME_CAMERA_CUT = 1 << 1
FRAME_REACTIVE_VALID = 1 << 2
FRAME_TCR_VALID = 1 << 3
ALLOWED_FRAME_FLAGS = FRAME_RESET | FRAME_CAMERA_CUT | FRAME_REACTIVE_VALID | FRAME_TCR_VALID


class F4SeqError(ValueError):
    """Raised when an f4seq manifest, index or payload is invalid."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise F4SeqError(message)


def _json_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        _require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _safe_path(value: Any, label: str) -> str:
    _require(isinstance(value, str) and value != "", f"{label} must be non-empty text")
    _require("\\" not in value and not value.startswith("/"), f"{label} must use relative POSIX separators")
    path = PurePosixPath(value)
    _require(not path.is_absolute() and all(part not in ("", ".", "..") for part in path.parts),
             f"unsafe {label}: {value}")
    _require(path.as_posix() == value, f"non-canonical {label}: {value}")
    return value


def _sha(value: Any, label: str) -> bytes:
    _require(isinstance(value, str) and SHA256_RE.fullmatch(value) is not None,
             f"{label} must be a lowercase SHA-256 hex digest")
    return bytes.fromhex(value)


def _finite_float(value: Any, label: str, *, positive: bool = False) -> float:
    _require(type(value) in (int, float) and math.isfinite(float(value)), f"{label} must be finite")
    result = float(value)
    if positive:
        _require(result > 0.0, f"{label} must be greater than zero")
    return result


def _vector(value: Any, label: str) -> tuple[float, float]:
    _require(isinstance(value, list) and len(value) == 2, f"{label} must contain two numbers")
    return (_finite_float(value[0], f"{label}[0]"), _finite_float(value[1], f"{label}[1]"))


def _f32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", value))[0]


def _check_float_bytes(data: bytes, dtype: str, label: str) -> None:
    if dtype not in FLOAT_DTYPES:
        return
    try:
        import numpy as np
    except ImportError:
        np = None
    item_size, item_fmt = FLOAT_DTYPES[dtype]
    aligned = len(data) - (len(data) % item_size)
    if np is not None:
        _require(bool(np.isfinite(np.frombuffer(data[:aligned], dtype=dtype)).all()), f"{label} contains NaN or Inf")
    else:
        for (value,) in struct.iter_unpack("<" + item_fmt, data[:aligned]):
            _require(math.isfinite(value), f"{label} contains NaN or Inf")
    _require(aligned == len(data), f"{label} ends in a partial scalar")


def _stream_member(
    stream: BinaryIO,
    *,
    expected_bytes: int,
    dtype: str | None,
    label: str,
    sequence_digest: Any | None = None,
) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    item_size, item_fmt = FLOAT_DTYPES.get(dtype or "", (0, ""))
    carry = b""
    while block := stream.read(CHUNK_BYTES):
        total += len(block)
        _require(total <= expected_bytes, f"{label} is longer than declared")
        digest.update(block)
        if sequence_digest is not None:
            sequence_digest.update(block)
        if dtype in FLOAT_DTYPES:
            data = carry + block
            aligned = len(data) - len(data) % item_size
            aligned_data = data[:aligned]
            try:
                import numpy as np
            except ImportError:
                np = None
            if np is not None:
                _require(bool(np.isfinite(np.frombuffer(aligned_data, dtype=dtype)).all()),
                         f"{label} contains NaN or Inf")
            else:
                for (value,) in struct.iter_unpack("<" + item_fmt, aligned_data):
                    _require(math.isfinite(value), f"{label} contains NaN or Inf")
            carry = data[aligned:]
    _require(total == expected_bytes, f"{label} has {total} bytes; expected {expected_bytes}")
    _require(not carry, f"{label} ends in a partial scalar")
    return digest.hexdigest(), total


def _normalize_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    required = {
        "sequence_id", "seed", "render_size", "output_size", "preset", "source_kind", "source_hash",
        "motion_vector_convention", "depth_convention",
    }
    _require(isinstance(metadata, dict) and set(metadata) == required,
             "sequence metadata must contain exactly " + ", ".join(sorted(required)))
    sequence_id = metadata["sequence_id"]
    _require(isinstance(sequence_id, str) and SEQUENCE_ID_RE.fullmatch(sequence_id) is not None,
             "sequence_id must be 1-63 ASCII letters, digits, dots, underscores or hyphens")
    _require(type(metadata["seed"]) is int and 0 <= metadata["seed"] <= 0xFFFFFFFFFFFFFFFF,
             "seed must be an unsigned 64-bit integer")
    sizes: dict[str, list[int]] = {}
    for key in ("render_size", "output_size"):
        value = metadata[key]
        _require(isinstance(value, list) and len(value) == 2, f"{key} must be [width, height]")
        sizes[key] = []
        for index, axis in enumerate(value):
            _require(type(axis) is int and 0 < axis <= MAX_DIMENSION, f"{key}[{index}] must be in [1, {MAX_DIMENSION}]")
            sizes[key].append(axis)
    preset = metadata["preset"]
    _require(preset in PRESETS, f"preset must be one of: {', '.join(PRESETS)}")
    source_kind = metadata["source_kind"]
    _require(source_kind in SOURCE_KINDS, f"source_kind must be one of: {', '.join(SOURCE_KINDS)}")
    _sha(metadata["source_hash"], "source_hash")
    _require(metadata["motion_vector_convention"] in MOTION_CONVENTIONS,
             "unsupported motion_vector_convention")
    _require(metadata["depth_convention"] in DEPTH_CONVENTIONS, "unsupported depth_convention")
    return {
        "sequence_id": sequence_id,
        "seed": metadata["seed"],
        "render_size": sizes["render_size"],
        "output_size": sizes["output_size"],
        "preset": preset,
        "source_kind": source_kind,
        "scale_factor": list(PRESETS[preset][1:]),
        "source_hash": metadata["source_hash"],
        "motion_vector_convention": metadata["motion_vector_convention"],
        "depth_convention": metadata["depth_convention"],
    }


def _normalize_frame(frame: dict[str, Any], index: int, width: int, height: int) -> dict[str, Any]:
    required = {
        "frame_time_delta_ms", "jitter_current", "jitter_previous", "exposure", "pre_exposure",
        "reset", "camera_cut", "validity", "arrays",
    }
    _require(isinstance(frame, dict) and set(frame) == required,
             f"frame {index} must contain exactly " + ", ".join(sorted(required)))
    dt = _finite_float(frame["frame_time_delta_ms"], f"frame {index}.frame_time_delta_ms", positive=True)
    current = _vector(frame["jitter_current"], f"frame {index}.jitter_current")
    previous = _vector(frame["jitter_previous"], f"frame {index}.jitter_previous")
    exposure = _finite_float(frame["exposure"], f"frame {index}.exposure", positive=True)
    pre_exposure = _finite_float(frame["pre_exposure"], f"frame {index}.pre_exposure", positive=True)
    _require(type(frame["reset"]) is bool and type(frame["camera_cut"]) is bool,
             f"frame {index}.reset and camera_cut must be booleans")
    _require(not frame["camera_cut"] or frame["reset"], f"frame {index}: camera_cut requires reset=true")
    validity = frame["validity"]
    expected_validity = {"reactive_mask", "transparency_composition_mask"}
    _require(isinstance(validity, dict) and set(validity) == expected_validity,
             f"frame {index}.validity must contain reactive_mask and transparency_composition_mask")
    for name, valid in validity.items():
        _require(type(valid) is bool, f"frame {index}.validity.{name} must be boolean")
    arrays = frame["arrays"]
    _require(isinstance(arrays, dict) and {name for name in arrays if name in ARRAYS} ==
             {"color", "depth", "motion_vectors"} |
             {name for name, valid in validity.items() if valid},
             f"frame {index}.arrays must provide required arrays and exactly the valid optional masks")
    array_paths: dict[str, str] = {}
    for name, path in arrays.items():
        _require(name in ARRAYS, f"frame {index} has unknown array {name!r}")
        array_paths[name] = _safe_path(path, f"frame {index}.arrays.{name}")
        _require(array_paths[name].startswith("input/"), f"frame {index}.arrays.{name} must be under input/")
    values = (dt, *current, *previous, exposure, pre_exposure)
    values = tuple(_f32(value) for value in values)
    _require(all(math.isfinite(value) for value in values), f"frame {index} metadata is outside FP32 range")
    return {
        "frame_index": index,
        "frame_time_delta_ms": values[0],
        "jitter_current": list(values[1:3]),
        "jitter_previous": list(values[3:5]),
        "exposure": values[5],
        "pre_exposure": values[6],
        "reset": frame["reset"],
        "camera_cut": frame["camera_cut"],
        "validity": dict(validity),
        "arrays": array_paths,
        "array_hashes": {},
    }


def _array_bytes(name: str, width: int, height: int) -> int:
    return width * height * ARRAYS[name][1]


def _array_shape(name: str, width: int, height: int) -> list[int]:
    return [height, width, ARRAY_CHANNELS[name]]


def _frame_flags(frame: dict[str, Any]) -> int:
    result = (FRAME_RESET if frame["reset"] else 0) | (FRAME_CAMERA_CUT if frame["camera_cut"] else 0)
    result |= FRAME_REACTIVE_VALID if frame["validity"]["reactive_mask"] else 0
    result |= FRAME_TCR_VALID if frame["validity"]["transparency_composition_mask"] else 0
    return result


def _pack_header(metadata: dict[str, Any], frame_count: int, *, sequence_hash: bytes) -> bytes:
    preset_id, scale_num, scale_den = PRESETS[metadata["preset"]]
    width, height = metadata["render_size"]
    output_width, output_height = metadata["output_size"]
    seq_id = metadata["sequence_id"].encode("ascii").ljust(64, b"\0")
    return HEADER.pack(
        MAGIC, VERSION, HEADER.size + FRAME.size * frame_count, frame_count,
        width, height, output_width, output_height, preset_id, scale_num, scale_den,
        metadata["seed"], SOURCE_KINDS[metadata["source_kind"]],
        MOTION_CONVENTIONS[metadata["motion_vector_convention"]],
        DEPTH_CONVENTIONS[metadata["depth_convention"]], 0,
        seq_id, _sha(metadata["source_hash"], "source_hash"), sequence_hash,
    )


def _pack_frame(frame: dict[str, Any]) -> bytes:
    hashes = []
    for name in ARRAY_ORDER:
        value = frame["array_hashes"].get(name)
        hashes.append(_sha(value, f"frame {frame['frame_index']} {name} hash") if value else bytes(32))
    return FRAME.pack(
        frame["frame_index"], _frame_flags(frame), frame["frame_time_delta_ms"],
        *frame["jitter_current"], *frame["jitter_previous"], frame["exposure"], frame["pre_exposure"],
        0, 0, 0, 0, b"".join(hashes),
    )


def build_f4seq(output_path: Path, metadata: dict[str, Any], frames: list[dict[str, Any]], source_root: Path) -> dict[str, Any]:
    """Pack raw frame planes into a deterministic ZIP_STORED f4seq."""
    output_path = Path(output_path)
    _require(output_path.suffix.lower() == ".f4seq", "output filename must end in .f4seq")
    sequence = _normalize_metadata(metadata)
    _require(isinstance(frames, list) and 0 < len(frames) <= MAX_FRAME_COUNT,
             f"frame count must be in [1, {MAX_FRAME_COUNT}]")
    source_root = Path(source_root).resolve()
    width, height = sequence["render_size"]
    frame_records = [_normalize_frame(frame, index, width, height) for index, frame in enumerate(frames)]
    total_bytes = 0

    for record in frame_records:
        record["manifest_arrays"] = {}
        for name in ARRAY_ORDER:
            if name not in record["arrays"]:
                continue
            source_relative = record["arrays"][name]
            source = (source_root / Path(*PurePosixPath(source_relative).parts)).resolve()
            _require(source.is_relative_to(source_root), f"frame {record['frame_index']} {name} path escapes source root")
            _require(source.is_file(), f"missing source array: {source_relative}")
            expected = _array_bytes(name, width, height)
            _require(expected <= MAX_ARRAY_BYTES, f"frame {record['frame_index']} {name} exceeds the 1 GiB limit")
            with source.open("rb") as stream:
                array_hash, actual_bytes = _stream_member(stream, expected_bytes=expected, dtype=ARRAYS[name][0],
                                                         label=f"frame {record['frame_index']} {name}")
            _require(actual_bytes == expected, f"frame {record['frame_index']} {name} byte count mismatch")
            record["array_hashes"][name] = array_hash
            member_path = f"frames/{record['frame_index']:06d}/{name}.raw"
            record["manifest_arrays"][name] = {
                "path": member_path, "dtype": ARRAYS[name][0], "shape": _array_shape(name, width, height),
                "bytes": expected, "sha256": array_hash,
            }
            total_bytes += expected
            _require(total_bytes <= MAX_TOTAL_BYTES, "sequence payload exceeds 64 GiB")

    header_zero = _pack_header(sequence, len(frame_records), sequence_hash=bytes(32))
    table = b"".join(_pack_frame(frame) for frame in frame_records)
    content_digest = hashlib.sha256()
    content_digest.update(header_zero)
    content_digest.update(table)
    for frame in frame_records:
        for name in ARRAY_ORDER:
            if name not in frame["arrays"]:
                continue
            source = source_root / Path(*PurePosixPath(frame["arrays"][name]).parts)
            with source.open("rb") as stream:
                while block := stream.read(CHUNK_BYTES):
                    content_digest.update(block)
    sequence_hash = content_digest.digest()
    index_data = _pack_header(sequence, len(frame_records), sequence_hash=sequence_hash) + table

    manifest = {
        "schema": SCHEMA,
        "sequence": {
            **sequence,
            "frame_count": len(frame_records),
            "motion_convention_id": MOTION_CONVENTIONS[sequence["motion_vector_convention"]],
            "depth_convention_id": DEPTH_CONVENTIONS[sequence["depth_convention"]],
            "source_hash": sequence["source_hash"],
            "sequence_hash": sequence_hash.hex(),
            "index_sha256": hashlib.sha256(index_data).hexdigest(),
        },
        "frames": [
            {key: value for key, value in record.items() if key in {
                "frame_index", "frame_time_delta_ms", "jitter_current", "jitter_previous", "exposure",
                "pre_exposure", "reset", "camera_cut", "validity",
            }} | {"arrays": record["manifest_arrays"]}
            for record in frame_records
        ],
    }
    manifest_data = (json.dumps(manifest, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    _require(len(manifest_data) <= MAX_MANIFEST_BYTES, "sequence.json exceeds 16 MiB")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", allowZip64=True) as archive:
        for name, data in (("sequence.json", manifest_data), ("sequence.bin", index_data)):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 0
            info.external_attr = 0
            archive.writestr(info, data)
        for record in frame_records:
            for name in ARRAY_ORDER:
                if name not in record["arrays"]:
                    continue
                source = source_root / Path(*PurePosixPath(record["arrays"][name]).parts)
                member = record["manifest_arrays"][name]["path"]
                info = zipfile.ZipInfo(member, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_STORED
                info.create_system = 0
                info.external_attr = 0
                with source.open("rb") as reader, archive.open(info, "w") as writer:
                    while block := reader.read(CHUNK_BYTES):
                        writer.write(block)
    return validate_f4seq(output_path)


def _parse_index(data: bytes) -> tuple[dict[str, Any], list[dict[str, Any]], bytes]:
    _require(len(data) >= HEADER.size, "sequence.bin is shorter than its fixed header")
    values = HEADER.unpack_from(data)
    (magic, version, header_bytes, frame_count, width, height, output_width, output_height,
     preset_id, scale_num, scale_den, seed, flags, motion_id, depth_id, reserved,
     sequence_id_raw, source_hash, sequence_hash) = values
    _require(magic == MAGIC and version == VERSION, "sequence.bin magic/version mismatch")
    _require(frame_count > 0 and frame_count <= MAX_FRAME_COUNT, "sequence.bin frame_count is out of range")
    _require(header_bytes == HEADER.size + FRAME.size * frame_count == len(data),
             "sequence.bin header/table size mismatch")
    _require(all(0 < value <= MAX_DIMENSION for value in (width, height, output_width, output_height)),
             "sequence.bin dimensions are out of range")
    _require(flags in SOURCE_KINDS.values() and reserved == 0, "sequence.bin has unsupported source kind or flags")
    sequence_id = sequence_id_raw.split(b"\0", 1)[0].decode("ascii", errors="strict")
    _require(SEQUENCE_ID_RE.fullmatch(sequence_id) is not None, "sequence.bin sequence_id is invalid")
    _require(preset_id < len(PRESETS), "sequence.bin preset id is invalid")
    preset, (expected_id, expected_num, expected_den) = list(PRESETS.items())[preset_id]
    _require(preset_id == expected_id and scale_num == expected_num and scale_den == expected_den,
             "sequence.bin preset scale mismatch")
    _require(motion_id in MOTION_CONVENTIONS.values() and depth_id in DEPTH_CONVENTIONS.values(),
             "sequence.bin uses an unsupported motion/depth convention")
    source_kind = next(name for name, value in SOURCE_KINDS.items() if value == flags)
    metadata = {
        "sequence_id": sequence_id, "seed": seed, "render_size": [width, height],
        "output_size": [output_width, output_height], "preset": preset,
        "scale_factor": [scale_num, scale_den], "source_kind": source_kind, "source_hash": source_hash.hex(),
        "motion_convention_id": motion_id, "depth_convention_id": depth_id,
        "sequence_hash": sequence_hash.hex(), "frame_count": frame_count,
    }
    frames = []
    for index in range(frame_count):
        frame_values = FRAME.unpack_from(data, HEADER.size + index * FRAME.size)
        (frame_index, frame_flags, dt, jitter_x, jitter_y, previous_x, previous_y, exposure,
         pre_exposure, r0, r1, r2, r3, hashes) = frame_values
        _require(frame_index == index, f"sequence.bin frame index mismatch at {index}")
        _require(frame_flags & ~ALLOWED_FRAME_FLAGS == 0 and all(v == 0 for v in (r0, r1, r2, r3)),
                 f"sequence.bin frame {index} has unsupported flags or reserved data")
        _require(all(math.isfinite(v) for v in (dt, jitter_x, jitter_y, previous_x, previous_y, exposure, pre_exposure))
                 and dt > 0.0 and exposure > 0.0 and pre_exposure > 0.0,
                 f"sequence.bin frame {index} metadata is invalid")
        digest_values = [hashes[offset:offset + 32] for offset in range(0, 160, 32)]
        valid = {
            "reactive_mask": bool(frame_flags & FRAME_REACTIVE_VALID),
            "transparency_composition_mask": bool(frame_flags & FRAME_TCR_VALID),
        }
        for name, digest in zip(ARRAY_ORDER, digest_values):
            should_exist = name in {"color", "depth", "motion_vectors"} or valid.get(name, False)
            _require((digest != bytes(32)) == should_exist, f"sequence.bin frame {index} {name} hash/validity mismatch")
        frames.append({
            "frame_index": index, "flags": frame_flags, "frame_time_delta_ms": dt,
            "jitter_current": [jitter_x, jitter_y], "jitter_previous": [previous_x, previous_y],
            "exposure": exposure, "pre_exposure": pre_exposure, "validity": valid,
            "array_hashes": {name: digest.hex() for name, digest in zip(ARRAY_ORDER, digest_values)
                             if digest != bytes(32)},
        })
    return metadata, frames, sequence_hash


def validate_f4seq(path: Path) -> dict[str, Any]:
    path = Path(path)
    _require(path.suffix.lower() == ".f4seq", "input filename must end in .f4seq")
    try:
        archive = zipfile.ZipFile(path, "r")
    except (OSError, zipfile.BadZipFile) as error:
        raise F4SeqError(f"cannot open f4seq ZIP: {error}") from error
    with archive:
        infos = archive.infolist()
        by_name: dict[str, zipfile.ZipInfo] = {}
        total_size = 0
        for info in infos:
            name = _safe_path(info.filename, "ZIP entry")
            _require(not info.is_dir(), "directory entries are not permitted")
            _require(name not in by_name, f"duplicate ZIP entry: {name}")
            _require(info.flag_bits & 0x1 == 0, f"encrypted ZIP entry is not permitted: {name}")
            _require(info.compress_type == zipfile.ZIP_STORED, f"ZIP entry must be stored without compression: {name}")
            total_size += info.file_size
            _require(total_size <= MAX_TOTAL_BYTES + MAX_MANIFEST_BYTES + HEADER.size + FRAME.size * MAX_FRAME_COUNT,
                     "sequence ZIP exceeds configured size limit")
            by_name[name] = info
        _require("sequence.json" in by_name and "sequence.bin" in by_name,
                 "sequence ZIP requires sequence.json and sequence.bin")
        _require(by_name["sequence.json"].file_size <= MAX_MANIFEST_BYTES, "sequence.json exceeds 16 MiB")
        manifest_data = archive.read("sequence.json")
        try:
            manifest = json.loads(manifest_data.decode("utf-8"), object_pairs_hook=_json_no_duplicates)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise F4SeqError(f"invalid sequence.json: {error}") from error
        _require(isinstance(manifest, dict) and set(manifest) == {"schema", "sequence", "frames"},
                 "sequence.json root must contain exactly schema, sequence and frames")
        _require(manifest["schema"] == SCHEMA, f"schema must be {SCHEMA}")
        sequence = manifest["sequence"]
        _require(isinstance(sequence, dict), "sequence.json sequence must be an object")
        index_data = archive.read("sequence.bin")
        _require(hashlib.sha256(index_data).hexdigest() == sequence.get("index_sha256"),
                 "sequence.bin SHA-256 mismatch")
        binary_metadata, binary_frames, sequence_hash = _parse_index(index_data)
        _require(sequence_hash.hex() == sequence.get("sequence_hash"), "sequence hash differs between manifest and index")
        for key in ("sequence_id", "seed", "render_size", "output_size", "preset", "scale_factor", "source_kind", "source_hash",
                    "motion_vector_convention", "depth_convention", "frame_count"):
            if key == "motion_vector_convention":
                value = next((name for name, enum in MOTION_CONVENTIONS.items()
                              if enum == binary_metadata["motion_convention_id"]), None)
            elif key == "depth_convention":
                value = next((name for name, enum in DEPTH_CONVENTIONS.items()
                              if enum == binary_metadata["depth_convention_id"]), None)
            else:
                value = binary_metadata.get(key)
            _require(sequence.get(key) == value, f"sequence.json {key} differs from sequence.bin")
        _require(isinstance(manifest["frames"], list) and len(manifest["frames"]) == binary_metadata["frame_count"],
                 "sequence.json frame count mismatch")

        canonical_index = bytearray(index_data)
        canonical_index[SEQUENCE_HASH_OFFSET:SEQUENCE_HASH_OFFSET + 32] = bytes(32)
        content_digest = hashlib.sha256(canonical_index)
        expected_names = {"sequence.json", "sequence.bin"}
        total_payload = 0
        for index, (frame_json, frame_bin) in enumerate(zip(manifest["frames"], binary_frames)):
            _require(isinstance(frame_json, dict), f"sequence.json frame {index} must be an object")
            expected_fields = {"frame_index", "frame_time_delta_ms", "jitter_current", "jitter_previous",
                               "exposure", "pre_exposure", "reset", "camera_cut", "validity", "arrays"}
            _require(set(frame_json) == expected_fields, f"sequence.json frame {index} fields mismatch")
            _require(frame_json["frame_index"] == index, f"sequence.json frame index mismatch at {index}")
            flags = frame_bin["flags"]
            expected_frame = {
                "frame_time_delta_ms": frame_bin["frame_time_delta_ms"],
                "jitter_current": frame_bin["jitter_current"],
                "jitter_previous": frame_bin["jitter_previous"],
                "exposure": frame_bin["exposure"], "pre_exposure": frame_bin["pre_exposure"],
                "reset": bool(flags & FRAME_RESET), "camera_cut": bool(flags & FRAME_CAMERA_CUT),
                "validity": frame_bin["validity"],
            }
            for key, value in expected_frame.items():
                _require(frame_json.get(key) == value, f"sequence.json frame {index} {key} differs from sequence.bin")
            arrays = frame_json["arrays"]
            _require(isinstance(arrays, dict), f"sequence.json frame {index}.arrays must be an object")
            expected_array_names = {name for name in ARRAY_ORDER if name in frame_bin["array_hashes"]}
            _require(set(arrays) == expected_array_names, f"sequence.json frame {index} array list differs from index")
            width, height = binary_metadata["render_size"]
            for name in ARRAY_ORDER:
                if name not in expected_array_names:
                    continue
                descriptor = arrays[name]
                _require(isinstance(descriptor, dict) and set(descriptor) == {"path", "dtype", "shape", "bytes", "sha256"},
                         f"sequence.json frame {index} {name} descriptor fields mismatch")
                member = _safe_path(descriptor["path"], f"frame {index} {name} path")
                _require(member == f"frames/{index:06d}/{name}.raw", f"frame {index} {name} path is not canonical")
                expected_bytes = _array_bytes(name, width, height)
                _require(descriptor["dtype"] == ARRAYS[name][0] and descriptor["shape"] == _array_shape(name, width, height)
                         and descriptor["bytes"] == expected_bytes, f"frame {index} {name} dtype/shape/bytes mismatch")
                _require(descriptor["sha256"] == frame_bin["array_hashes"][name], f"frame {index} {name} hash differs from index")
                _sha(descriptor["sha256"], f"frame {index} {name} hash")
                info = by_name.get(member)
                _require(info is not None, f"missing ZIP entry: {member}")
                _require(info.file_size == expected_bytes, f"{member} ZIP size mismatch")
                with archive.open(info) as stream:
                    actual_sha, _ = _stream_member(stream, expected_bytes=expected_bytes, dtype=ARRAYS[name][0],
                                                   label=member, sequence_digest=content_digest)
                _require(actual_sha == descriptor["sha256"], f"{member} SHA-256 mismatch")
                expected_names.add(member)
                total_payload += expected_bytes
                _require(total_payload <= MAX_TOTAL_BYTES, "sequence payload exceeds 64 GiB")
        extras = sorted(set(by_name) - expected_names)
        missing = sorted(expected_names - set(by_name))
        _require(not missing, "missing ZIP entries: " + ", ".join(missing))
        _require(not extras, "unexpected ZIP entries: " + ", ".join(extras))
        _require(content_digest.digest() == sequence_hash, "sequence content hash mismatch")

    return {
        "schema": SCHEMA,
        "sequence_id": binary_metadata["sequence_id"],
        "sequence_hash": sequence_hash.hex(),
        "frame_count": binary_metadata["frame_count"],
        "render_size": binary_metadata["render_size"],
        "output_size": binary_metadata["output_size"],
        "preset": binary_metadata["preset"],
        "array_bytes": total_payload,
        "reset_frames": [index for index, frame in enumerate(binary_frames) if frame["flags"] & FRAME_RESET],
        "camera_cuts": [index for index, frame in enumerate(binary_frames) if frame["flags"] & FRAME_CAMERA_CUT],
        "integrity": "container, index, per-frame content hashes and finite floating-point inputs validated",
    }
