#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
from tools.teacher.capture_format import validate_capture

SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _frames(report: dict[str, Any]) -> dict[int, dict[str, Any]]:
    frames = report.get("frames")
    count = report.get("frame_count")
    if not isinstance(frames, list) or type(count) is not int or count <= 0 or len(frames) != count:
        raise ValueError("sequence report has an invalid frame count")
    result = {}
    for frame in frames:
        if not isinstance(frame, dict):
            raise ValueError("sequence report contains a non-object frame")
        index = frame.get("frame_index")
        if type(index) is not int or index in result:
            raise ValueError("sequence report has an invalid or duplicate frame index")
        for key in ("input_frame_sha256", "instrumented_output_sha256", "reference_output_sha256"):
            digest = frame.get(key)
            if not isinstance(digest, str) or SHA256.fullmatch(digest) is None:
                raise ValueError(f"frame {index} has invalid {key}")
        result[index] = frame
    if set(result) != set(range(count)):
        raise ValueError("sequence report frame indices are incomplete")
    return result


def _capture_array_hashes(root: Path, sequence_hash: str) -> dict[int, dict[str, str]]:
    result = {}
    for path in sorted(root.glob("frame_*.f4cap")):
        validate_capture(path)
        with zipfile.ZipFile(path, "r") as archive:
            manifest = json.loads(archive.read("capture.json"))
        metadata = manifest.get("metadata", {})
        index = metadata.get("frame_index")
        if type(index) is not int or metadata.get("sequence_hash") != sequence_hash or index in result:
            raise ValueError(f"capture provenance mismatch or duplicate frame: {path}")
        arrays = manifest.get("arrays", {})
        hashes = {name: value.get("sha256") for name, value in arrays.items()}
        if any(not isinstance(digest, str) or SHA256.fullmatch(digest) is None for digest in hashes.values()):
            raise ValueError(f"capture has invalid array hashes: {path}")
        result[index] = hashes
    if not result:
        raise ValueError(f"no frame_*.f4cap packages found in {root}")
    return result


def compare_reports(
    first: dict[str, Any],
    second: dict[str, Any],
    first_capture_root: Path | None = None,
    second_capture_root: Path | None = None,
) -> dict[str, Any]:
    if first.get("schema") != "f4n10.fsr4-provider-sequence.v1" or second.get("schema") != first.get("schema"):
        raise ValueError("both inputs must be FSR4 provider sequence reports")
    provenance_fields = ("build_commit", "adapter", "driver_version", "sequence_hash", "frame_count")
    same_provenance = all(first.get(key) == second.get(key) for key in provenance_fields)
    frames_a = _frames(first)
    frames_b = _frames(second)
    same_inputs = (
        same_provenance
        and first.get("sequence_id") == second.get("sequence_id")
        and first.get("source_kind") == second.get("source_kind")
        and first.get("render_size") == second.get("render_size")
        and first.get("output_size") == second.get("output_size")
        and all(
            frames_a[index].get("input_frame_sha256") == frames_b[index].get("input_frame_sha256")
            and frames_a[index].get("reset") == frames_b[index].get("reset")
            and frames_a[index].get("camera_cut") == frames_b[index].get("camera_cut")
            for index in frames_a
        )
    )
    instrumented_changes = [
        index for index in frames_a
        if frames_a[index]["instrumented_output_sha256"] != frames_b[index]["instrumented_output_sha256"]
    ]
    reference_changes = [
        index for index in frames_a
        if frames_a[index]["reference_output_sha256"] != frames_b[index]["reference_output_sha256"]
    ]
    instrumented_repeatable = same_inputs and not instrumented_changes
    reference_repeatable = same_inputs and not reference_changes
    if (first_capture_root is None) != (second_capture_root is None):
        raise ValueError("both capture roots must be supplied together")
    capture_array_audit = None
    captured_arrays_repeatable = None
    if first_capture_root is not None and second_capture_root is not None:
        capture_a = _capture_array_hashes(first_capture_root, first["sequence_hash"])
        capture_b = _capture_array_hashes(second_capture_root, second["sequence_hash"])
        if set(capture_a) != set(capture_b):
            raise ValueError("audit capture frame sets differ between sequence runs")
        per_frame = []
        for index in sorted(capture_a):
            if set(capture_a[index]) != set(capture_b[index]):
                raise ValueError(f"capture array names differ at frame {index}")
            changed = [
                {
                    "name": name,
                    "first_sha256": capture_a[index][name],
                    "repeat_sha256": capture_b[index][name],
                }
                for name in sorted(capture_a[index])
                if capture_a[index][name] != capture_b[index][name]
            ]
            per_frame.append({"frame_index": index, "changed_arrays": changed})
        captured_arrays_repeatable = all(not item["changed_arrays"] for item in per_frame)
        capture_array_audit = {
            "audit_frames": sorted(capture_a),
            "all_array_hashes_repeatable": captured_arrays_repeatable,
            "frames": per_frame,
        }
    return {
        "schema": "f4n10.fsr4-sequence-repeatability.v1",
        "first_report_build_commit": first.get("build_commit"),
        "repeat_report_build_commit": second.get("build_commit"),
        "sequence_hash": first.get("sequence_hash"),
        "adapter": first.get("adapter"),
        "driver_version": first.get("driver_version"),
        "same_provenance": same_provenance,
        "same_inputs": same_inputs,
        "frames_compared": len(frames_a),
        "instrumented_outputs_repeatable": instrumented_repeatable,
        "ordinary_outputs_repeatable": reference_repeatable,
        "instrumented_changed_frames": instrumented_changes,
        "ordinary_changed_frames": reference_changes,
        "captured_audit_arrays_repeatable": captured_arrays_repeatable,
        "capture_array_audit": capture_array_audit,
        "repeatable": instrumented_repeatable and reference_repeatable and captured_arrays_repeatable is not False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare two identical-input FSR4 provider sequence runs.")
    parser.add_argument("first_report", type=Path)
    parser.add_argument("repeat_report", type=Path)
    parser.add_argument("--first-capture-root", type=Path)
    parser.add_argument("--repeat-capture-root", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        first = json.loads(args.first_report.read_text(encoding="utf-8"))
        second = json.loads(args.repeat_report.read_text(encoding="utf-8"))
        if not isinstance(first, dict) or not isinstance(second, dict):
            raise ValueError("sequence reports must be JSON objects")
        result = compare_reports(first, second, args.first_capture_root, args.repeat_capture_root)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["repeatable"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
