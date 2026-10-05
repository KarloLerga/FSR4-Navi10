"""Deterministic, dependency-free packaging and validation for F4N10 teacher captures."""

from __future__ import annotations

import hashlib
import json
import math
import re
import struct
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any


SCHEMA = "f4n10.teacher.capture.v1"
MAX_MANIFEST_BYTES = 1 * 1024 * 1024
MAX_ARRAY_BYTES = 1024 * 1024 * 1024
MAX_TOTAL_ARRAY_BYTES = 8 * 1024 * 1024 * 1024
MAX_DIMENSION = 16384
CHUNK_BYTES = 1024 * 1024

DTYPE_BYTES = {"<f2": 2, "<f4": 4, "|u1": 1, "<u2": 2, "<i2": 2, "<i4": 4}
FLOAT_FORMAT = {"<f2": "e", "<f4": "f"}

REQUIRED_ARRAYS = {
    "input_color",
    "depth",
    "motion_vectors",
    "current_reconstruction_source",
    "reprojected_history",
    "model_input_semantic_channels",
    "raw_model_parameters",
    "physical_controls",
    "recurrent_state",
    "final_rgb",
}
OPTIONAL_ARRAYS = {
    "reactive_mask",
    "transparency_composition_mask",
    "pass0_features",
    "bottleneck_features",
    "pass11_features",
    "pass12_features",
}
VALIDITY_FIELDS = {
    "input_color",
    "depth",
    "motion_vectors",
    "reactive_mask",
    "transparency_composition_mask",
}
METADATA_FIELDS = {
    "sequence_id",
    "frame_index",
    "preset",
    "render_width",
    "render_height",
    "output_width",
    "output_height",
    "jitter_current",
    "jitter_previous",
    "exposure",
    "pre_exposure",
    "reset",
    "motion_convention",
    "sequence_hash",
    "source_commit",
    "source_hash",
    "shader_hashes",
    "build_commit",
    "build_mode",
    "capture_origin",
    "gpu_name",
    "driver_version",
}
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-fA-F]{40}$")


class CaptureFormatError(ValueError):
    """Raised when a capture manifest or package violates the v1 contract."""


def _object_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise CaptureFormatError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _read_json(data: bytes) -> dict[str, Any]:
    if len(data) > MAX_MANIFEST_BYTES:
        raise CaptureFormatError("capture.json exceeds 1 MiB")
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=_object_no_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CaptureFormatError(f"invalid UTF-8 JSON: {error}") from error
    if not isinstance(value, dict):
        raise CaptureFormatError("capture.json root must be an object")
    return value


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CaptureFormatError(message)


def _positive_int(value: Any, label: str, limit: int = MAX_DIMENSION) -> int:
    _require(type(value) is int and 0 < value <= limit, f"{label} must be an integer in [1, {limit}]")
    return value


def _finite_number(value: Any, label: str) -> float:
    _require(type(value) in (int, float) and math.isfinite(float(value)), f"{label} must be finite")
    return float(value)


def _vector(value: Any, label: str, length: int) -> list[float]:
    _require(isinstance(value, list) and len(value) == length, f"{label} must contain {length} numbers")
    return [_finite_number(v, f"{label}[{i}]") for i, v in enumerate(value)]


def _safe_archive_path(value: Any, label: str) -> str:
    _require(isinstance(value, str) and value != "", f"{label} must be a non-empty relative path")
    _require("\\" not in value and not value.startswith("/"), f"{label} must use relative POSIX separators")
    path = PurePosixPath(value)
    _require(not path.is_absolute() and all(part not in ("", ".", "..") for part in path.parts),
             f"unsafe {label}: {value}")
    _require(path.as_posix() == value, f"non-canonical {label}: {value}")
    return path.as_posix()


def validate_manifest(manifest: dict[str, Any], *, for_packaging: bool = False) -> dict[str, dict[str, Any]]:
    _require(manifest.keys() == {"schema", "metadata", "validity", "arrays"},
             "manifest must contain exactly schema, metadata, validity and arrays")
    _require(manifest.get("schema") == SCHEMA, f"schema must be {SCHEMA}")
    metadata = manifest.get("metadata")
    _require(isinstance(metadata, dict), "metadata must be an object")
    missing_metadata = sorted(METADATA_FIELDS - metadata.keys())
    _require(not missing_metadata, f"missing metadata fields: {', '.join(missing_metadata)}")

    for field in ("sequence_id", "preset", "motion_convention", "build_mode", "capture_origin", "gpu_name", "driver_version"):
        _require(isinstance(metadata[field], str) and metadata[field].strip() != "", f"metadata.{field} must be non-empty text")
    _require(type(metadata["frame_index"]) is int and metadata["frame_index"] >= 0,
             "metadata.frame_index must be a non-negative integer")
    for field in ("render_width", "render_height", "output_width", "output_height"):
        _positive_int(metadata[field], f"metadata.{field}")
    for field in ("jitter_current", "jitter_previous"):
        _vector(metadata[field], f"metadata.{field}", 2)
    for field in ("exposure", "pre_exposure"):
        _require(_finite_number(metadata[field], f"metadata.{field}") > 0.0,
                 f"metadata.{field} must be greater than zero")
    _require(type(metadata["reset"]) is bool, "metadata.reset must be boolean")
    _require(isinstance(metadata["source_commit"], str) and COMMIT_RE.fullmatch(metadata["source_commit"]) is not None,
             "metadata.source_commit must be a 40-character commit hash")
    _require(isinstance(metadata["source_hash"], str) and SHA256_RE.fullmatch(metadata["source_hash"]) is not None,
             "metadata.source_hash must be a SHA-256 hex digest")
    _require(isinstance(metadata["sequence_hash"], str) and SHA256_RE.fullmatch(metadata["sequence_hash"]) is not None,
             "metadata.sequence_hash must be a SHA-256 hex digest")
    _require(isinstance(metadata["build_commit"], str) and COMMIT_RE.fullmatch(metadata["build_commit"]) is not None,
             "metadata.build_commit must be a 40-character commit hash")
    shader_hashes = metadata["shader_hashes"]
    _require(isinstance(shader_hashes, dict) and shader_hashes, "metadata.shader_hashes must be a non-empty object")
    for name, digest in shader_hashes.items():
        _require(isinstance(name, str) and name.strip() != "", "shader hash names must be non-empty text")
        _require(isinstance(digest, str) and SHA256_RE.fullmatch(digest) is not None,
                 f"metadata.shader_hashes[{name!r}] must be a SHA-256 hex digest")

    validity = manifest.get("validity")
    _require(isinstance(validity, dict) and validity.keys() == VALIDITY_FIELDS,
             "validity must contain exactly input_color, depth, motion_vectors, reactive_mask and transparency_composition_mask")
    for name, valid in validity.items():
        _require(type(valid) is bool, f"validity.{name} must be boolean")
    for name in ("input_color", "depth", "motion_vectors"):
        _require(validity[name], f"validity.{name} must be true for a teacher capture")

    arrays = manifest.get("arrays")
    _require(isinstance(arrays, dict), "arrays must be an object")
    _require(all(isinstance(name, str) for name in arrays), "array names must be text")
    missing_arrays = sorted(REQUIRED_ARRAYS - arrays.keys())
    _require(not missing_arrays, f"missing required arrays: {', '.join(missing_arrays)}")
    unknown_arrays = sorted(arrays.keys() - REQUIRED_ARRAYS - OPTIONAL_ARRAYS)
    _require(not unknown_arrays, f"unknown arrays: {', '.join(unknown_arrays)}")

    for name in ("reactive_mask", "transparency_composition_mask"):
        _require((name in arrays) == validity[name],
                 f"arrays.{name} presence must match validity.{name}; missing data must not be filled with zero")

    render_w = metadata["render_width"]
    render_h = metadata["render_height"]
    output_w = metadata["output_width"]
    output_h = metadata["output_height"]
    expected_shapes = {
        "input_color": ((render_h, render_w, 3), (render_h, render_w, 4)),
        "depth": ((render_h, render_w, 1),),
        "motion_vectors": ((render_h, render_w, 2),),
        "reactive_mask": ((render_h, render_w, 1),),
        "transparency_composition_mask": ((render_h, render_w, 1),),
        "current_reconstruction_source": ((render_h, render_w, 3),),
        "reprojected_history": ((output_h, output_w, 3),),
        "raw_model_parameters": ((output_h, output_w, 4),),
        "physical_controls": ((output_h, output_w, 4),),
        "recurrent_state": ((output_h, output_w, 4),),
        "final_rgb": ((output_h, output_w, 3),),
    }
    normalized: dict[str, dict[str, Any]] = {}
    used_paths: set[str] = set()
    total_bytes = 0
    for name, descriptor in arrays.items():
        _require(isinstance(name, str) and isinstance(descriptor, dict), f"arrays.{name} must be an object")
        allowed_descriptor_fields = {"dtype", "shape", "sha256", "file" if for_packaging else "path"}
        required_descriptor_fields = {"dtype", "shape", "file" if for_packaging else "path"}
        _require(descriptor.keys() <= allowed_descriptor_fields and required_descriptor_fields <= descriptor.keys(),
                 f"arrays.{name} has unexpected or missing descriptor fields")
        _require(descriptor.get("dtype") in DTYPE_BYTES, f"arrays.{name}.dtype is unsupported")
        dtype = descriptor["dtype"]
        shape = descriptor.get("shape")
        _require(isinstance(shape, list) and 1 <= len(shape) <= 5,
                 f"arrays.{name}.shape must have one to five dimensions")
        count = 1
        for axis, value in enumerate(shape):
            count *= _positive_int(value, f"arrays.{name}.shape[{axis}]")
        byte_count = count * DTYPE_BYTES[dtype]
        _require(byte_count <= MAX_ARRAY_BYTES, f"arrays.{name} exceeds the 1 GiB per-array limit")
        total_bytes += byte_count
        _require(total_bytes <= MAX_TOTAL_ARRAY_BYTES, "capture exceeds the 8 GiB total-array limit")
        if name in expected_shapes:
            _require(tuple(shape) in expected_shapes[name],
                     f"arrays.{name}.shape {shape} does not match capture dimensions/channels")
        if name == "model_input_semantic_channels":
            _require(len(shape) == 3 and shape[2] >= 7,
                     "arrays.model_input_semantic_channels must be HWC with at least seven semantic channels")
        path = descriptor.get("path")
        if path is not None:
            path = _safe_archive_path(path, f"arrays.{name}.path")
            _require(path.startswith("arrays/"), f"arrays.{name}.path must be under arrays/")
            _require(path not in used_paths, f"duplicate array path: {path}")
            used_paths.add(path)
        digest = descriptor.get("sha256")
        if digest is not None:
            _require(isinstance(digest, str) and SHA256_RE.fullmatch(digest) is not None,
                     f"arrays.{name}.sha256 must be a SHA-256 hex digest")
        normalized[name] = {
            "dtype": dtype,
            "shape": shape,
            "path": path,
            "sha256": digest,
            "byte_count": byte_count,
        }
    return normalized


def _finite_stream(stream: Any, dtype: str, expected_bytes: int, label: str) -> tuple[str, int]:
    digest = hashlib.sha256()
    seen = 0
    fmt = FLOAT_FORMAT.get(dtype)
    carry = b""
    item_size = DTYPE_BYTES[dtype]
    while True:
        block = stream.read(CHUNK_BYTES)
        if not block:
            break
        seen += len(block)
        _require(seen <= expected_bytes, f"{label} is longer than its declared shape")
        digest.update(block)
        if fmt:
            data = carry + block
            aligned = len(data) - len(data) % item_size
            for (value,) in struct.iter_unpack("<" + fmt, data[:aligned]):
                if not math.isfinite(value):
                    raise CaptureFormatError(f"{label} contains NaN or Inf")
            carry = data[aligned:]
    _require(seen == expected_bytes, f"{label} has {seen} bytes; expected {expected_bytes}")
    _require(not carry, f"{label} ends in a partial scalar value")
    return digest.hexdigest(), seen


def validate_capture(path: Path) -> dict[str, Any]:
    path = Path(path)
    try:
        archive = zipfile.ZipFile(path, "r")
    except (OSError, zipfile.BadZipFile) as error:
        raise CaptureFormatError(f"cannot open capture ZIP: {error}") from error

    with archive:
        infos = archive.infolist()
        names: set[str] = set()
        total_uncompressed = 0
        for info in infos:
            name = _safe_archive_path(info.filename, "ZIP entry")
            _require(not info.is_dir(), "directory entries are not permitted")
            _require(name not in names, f"duplicate ZIP entry: {name}")
            names.add(name)
            _require(info.flag_bits & 0x1 == 0, f"encrypted ZIP entry is not permitted: {name}")
            _require(info.compress_type == zipfile.ZIP_STORED, f"ZIP entry must be stored without compression: {name}")
            total_uncompressed += info.file_size
        _require(total_uncompressed <= MAX_TOTAL_ARRAY_BYTES + MAX_MANIFEST_BYTES,
                 "capture ZIP exceeds the 8 GiB size limit")
        _require("capture.json" in names, "capture ZIP is missing root capture.json")
        _require(archive.getinfo("capture.json").file_size <= MAX_MANIFEST_BYTES,
                 "capture.json exceeds 1 MiB")
        try:
            manifest_data = archive.read("capture.json")
        except (KeyError, zipfile.BadZipFile, RuntimeError) as error:
            raise CaptureFormatError(f"cannot read capture.json: {error}") from error
        manifest = _read_json(manifest_data)
        arrays = validate_manifest(manifest)
        for name, descriptor in manifest["arrays"].items():
            _require(descriptor["sha256"] is not None, f"arrays.{name}.sha256 is required in a package")

        expected_names = {"capture.json"}
        for name, descriptor in arrays.items():
            _require(descriptor["path"] is not None, f"arrays.{name}.path is required in a package")
            expected_names.add(descriptor["path"])
            _require(descriptor["path"] in names, f"missing ZIP entry: {descriptor['path']}")
            info = archive.getinfo(descriptor["path"])
            expected_bytes = descriptor["byte_count"]
            _require(info.file_size == expected_bytes,
                     f"arrays.{name} ZIP size is {info.file_size}; expected {expected_bytes}")
            try:
                with archive.open(info, "r") as stream:
                    actual_sha, actual_size = _finite_stream(stream, descriptor["dtype"], expected_bytes,
                                                             f"arrays.{name}")
            except (KeyError, zipfile.BadZipFile, RuntimeError, OSError) as error:
                raise CaptureFormatError(f"cannot read arrays.{name}: {error}") from error
            _require(actual_size == expected_bytes, f"arrays.{name} byte-count mismatch")
            _require(actual_sha.lower() == descriptor["sha256"].lower(),
                     f"arrays.{name} SHA-256 mismatch")
        extras = sorted(names - expected_names)
        missing = sorted(expected_names - names)
        _require(not missing, f"missing ZIP entries: {', '.join(missing)}")
        _require(not extras, f"unexpected ZIP entries: {', '.join(extras)}")

    return {
        "schema": SCHEMA,
        "sequence_id": manifest["metadata"]["sequence_id"],
        "sequence_hash": manifest["metadata"]["sequence_hash"],
        "frame_index": manifest["metadata"]["frame_index"],
        "preset": manifest["metadata"]["preset"],
        "render_size": [manifest["metadata"]["render_width"], manifest["metadata"]["render_height"]],
        "output_size": [manifest["metadata"]["output_width"], manifest["metadata"]["output_height"]],
        "array_count": len(arrays),
        "array_bytes": sum(item["byte_count"] for item in arrays.values()),
        "validity": manifest["validity"],
        "capture_origin_claim": manifest["metadata"]["capture_origin"],
        "validation_note": "Integrity checks passed; capture provenance and GPU origin remain self-reported metadata.",
    }


def package_capture(input_manifest: dict[str, Any], array_root: Path, output_path: Path) -> dict[str, Any]:
    """Build a deterministic .f4cap from a JSON-like manifest and raw array files."""
    arrays = validate_manifest(input_manifest, for_packaging=True)
    array_root = Path(array_root).resolve()
    output_path = Path(output_path)
    _require(output_path.suffix.lower() == ".f4cap", "output filename must end in .f4cap")
    output_manifest = json.loads(json.dumps(input_manifest))
    output_manifest["arrays"] = {}
    payloads: list[tuple[str, bytes]] = []
    total_bytes = 0

    for name in sorted(arrays):
        original = input_manifest["arrays"][name]
        source_name = _safe_archive_path(original.get("file"), f"arrays.{name}.file")
        _require(source_name.startswith("arrays/"), f"arrays.{name}.file must be under arrays/")
        source_path = (array_root / Path(*PurePosixPath(source_name).parts)).resolve()
        _require(source_path.is_relative_to(array_root), f"arrays.{name}.file escapes the array directory")
        _require(source_path.is_file(), f"array source file does not exist: {source_name}")
        data = source_path.read_bytes()
        expected_bytes = arrays[name]["byte_count"]
        _require(len(data) == expected_bytes,
                 f"arrays.{name}.file has {len(data)} bytes; expected {expected_bytes}")
        sha = hashlib.sha256(data).hexdigest()
        if arrays[name]["sha256"] is not None:
            _require(sha.lower() == arrays[name]["sha256"].lower(),
                     f"arrays.{name}.file SHA-256 mismatch")
        # Reuse the same scalar/finite checks used by the package reader.
        import io

        _finite_stream(io.BytesIO(data), arrays[name]["dtype"], expected_bytes, f"arrays.{name}")
        archive_name = source_name
        output_manifest["arrays"][name] = {
            "path": archive_name,
            "dtype": arrays[name]["dtype"],
            "shape": arrays[name]["shape"],
            "sha256": sha,
        }
        payloads.append((archive_name, data))
        total_bytes += len(data)
        _require(total_bytes <= MAX_TOTAL_ARRAY_BYTES, "capture exceeds the 8 GiB total-array limit")

    try:
        manifest_data = (json.dumps(output_manifest, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    except (TypeError, ValueError) as error:
        raise CaptureFormatError(f"manifest cannot be serialized as strict JSON: {error}") from error
    _require(len(manifest_data) <= MAX_MANIFEST_BYTES, "capture.json exceeds 1 MiB")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", allowZip64=True) as archive:
        entries = [("capture.json", manifest_data), *payloads]
        for name, data in entries:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 0
            info.external_attr = 0
            archive.writestr(info, data)
    return validate_capture(output_path)
