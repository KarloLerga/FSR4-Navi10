from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Any


class AlignmentError(ValueError):
    pass


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise AlignmentError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _read_report(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_object_without_duplicate_keys)
    except json.JSONDecodeError as error:
        raise AlignmentError(f"invalid JSON in {path}: {error}") from error
    if not isinstance(value, dict):
        raise AlignmentError(f"report root must be a JSON object: {path}")
    return value


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AlignmentError(message)


def _valid_sha256(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _positive_finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AlignmentError(f"{label} must be a number")
    number = float(value)
    if not math.isfinite(number) or number <= 0.0:
        raise AlignmentError(f"{label} must be positive and finite")
    return number


def compare_reports(fsr4: dict[str, Any], fsr3: dict[str, Any]) -> dict[str, Any]:
    _require(fsr4.get("schema") == "f4n10.fsr4-provider-sequence.v1", "unexpected FSR4 report schema")
    _require(fsr3.get("schema") == "f4n10.fsr3-reference-sequence.v1", "unexpected FSR3 report schema")
    _require(fsr4.get("instrumentation_matches_reference") is True,
             "FSR4 instrumented output did not match its ordinary provider output")
    _require(fsr3.get("validation", {}).get("instrumented_reference_outputs_match") is True,
             "FSR3 instrumented output did not match its ordinary provider output")
    _require(fsr4.get("gpu_timing_recorded") is True, "FSR4 report has no provider GPU timing")
    _require(fsr3.get("validation", {}).get("gpu_timing_recorded") is True,
             "FSR3 report has no provider GPU timing")

    sequence4 = {
        "id": fsr4.get("sequence_id"),
        "source_kind": fsr4.get("source_kind"),
        "sequence_hash": fsr4.get("sequence_hash"),
        "render_size": fsr4.get("render_size"),
        "output_size": fsr4.get("output_size"),
        "frame_count": fsr4.get("frame_count"),
    }
    sequence3 = fsr3.get("sequence")
    _require(isinstance(sequence3, dict), "FSR3 report is missing sequence metadata")
    for key, value in (("id", sequence3.get("id")), ("source_kind", sequence3.get("source_kind")),
                       ("sequence_hash", sequence3.get("sequence_hash")),
                       ("render_size", sequence3.get("render_size")),
                       ("output_size", sequence3.get("output_size")),
                       ("frame_count", sequence3.get("frame_count"))):
        _require(sequence4[key] == value, f"FSR4/FSR3 sequence metadata differs: {key}")
    _require(_valid_sha256(sequence4["sequence_hash"]), "sequence_hash must be a lowercase SHA-256")
    _require(fsr4.get("adapter") == fsr3.get("gpu_name"), "providers ran on different GPU adapters")

    frames4 = fsr4.get("frames")
    frames3 = fsr3.get("frames")
    _require(isinstance(frames4, list) and isinstance(frames3, list), "frame reports must be arrays")
    _require(len(frames4) == len(frames3) == sequence4["frame_count"], "frame report counts do not match")

    paired_frames: list[dict[str, Any]] = []
    captures4: list[int] = []
    captures3: list[int] = []
    for expected_index, (frame4, frame3) in enumerate(zip(frames4, frames3, strict=True)):
        _require(isinstance(frame4, dict) and isinstance(frame3, dict), "frame report entries must be objects")
        _require(frame4.get("frame_index") == frame3.get("frame_index") == expected_index,
                 f"frame indices differ or are out of order at {expected_index}")
        _require(frame4.get("input_frame_sha256") == frame3.get("input_frame_sha256") and
                 _valid_sha256(frame4.get("input_frame_sha256")),
                 f"input frame SHA-256 differs at frame {expected_index}")
        for flag in ("reset", "camera_cut"):
            _require(frame4.get(flag) == frame3.get(flag), f"{flag} differs at frame {expected_index}")
        _require(frame4.get("output_identical") is True, f"FSR4 instrumentation mismatch at frame {expected_index}")
        _require(frame3.get("instrumented_reference_match") is True,
                 f"FSR3 instrumentation mismatch at frame {expected_index}")
        _require(_valid_sha256(frame4.get("reference_output_sha256")),
                 f"FSR4 output SHA-256 is invalid at frame {expected_index}")
        _require(_valid_sha256(frame3.get("reference_output_sha256")),
                 f"FSR3 output SHA-256 is invalid at frame {expected_index}")
        time4 = _positive_finite(frame4.get("reference_gpu_dispatch_us"),
                                 f"FSR4 GPU time at frame {expected_index}")
        time3 = _positive_finite(frame3.get("reference_gpu_dispatch_us"),
                                 f"FSR3 GPU time at frame {expected_index}")
        if frame4.get("capture_manifest"):
            captures4.append(expected_index)
        if frame3.get("capture_manifest"):
            captures3.append(expected_index)
        paired_frames.append({
            "frame_index": expected_index,
            "reset": frame4["reset"],
            "camera_cut": frame4["camera_cut"],
            "input_frame_sha256": frame4["input_frame_sha256"],
            "fsr4_output_sha256": frame4["reference_output_sha256"],
            "fsr3_output_sha256": frame3["reference_output_sha256"],
            "fsr4_gpu_dispatch_us": time4,
            "fsr3_gpu_dispatch_us": time3,
        })
    _require(captures4 == captures3, "FSR4 and FSR3 captured different audit frames")

    timing4 = fsr4.get("gpu_timing")
    timing3 = fsr3.get("gpu_timing")
    _require(isinstance(timing4, dict) and isinstance(timing3, dict), "provider timing summaries are missing")
    for key in ("steady_state_mean_us", "steady_state_p50_us", "steady_state_p95_us"):
        _positive_finite(timing4.get(key), f"FSR4 timing summary {key}")
        _positive_finite(timing3.get(key), f"FSR3 timing summary {key}")

    return {
        "schema": "f4n10.provider-pairing-report.v1",
        "sequence": sequence4,
        "gpu": fsr4["adapter"],
        "fsr4_provider": "pinned_amd_fsr4_i8_native_1080",
        "fsr4_upstream_commit": fsr4.get("upstream_commit"),
        "fsr3_provider": fsr3.get("provider"),
        "fsr3_sdk_commit": fsr3.get("sdk_commit"),
        "audit_capture_frames": captures4,
        "input_frames_aligned_by_sha256": True,
        "instrumented_outputs_match_ordinary_provider": True,
        "cross_provider_output_equality_claimed": False,
        "quality_claimed": False,
        "timing_us": {
            "fsr4_steady_state_mean": timing4["steady_state_mean_us"],
            "fsr4_steady_state_p50": timing4["steady_state_p50_us"],
            "fsr4_steady_state_p95": timing4["steady_state_p95_us"],
            "fsr3_steady_state_mean": timing3["steady_state_mean_us"],
            "fsr3_steady_state_p50": timing3["steady_state_p50_us"],
            "fsr3_steady_state_p95": timing3["steady_state_p95_us"],
        },
        "frames": paired_frames,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Pair FSR4 and FSR3 sequence reports by per-frame input SHA-256.")
    parser.add_argument("fsr4_report", type=Path)
    parser.add_argument("fsr3_report", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        result = compare_reports(_read_report(args.fsr4_report), _read_report(args.fsr3_report))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"Aligned {len(result['frames'])} input frames: {args.output}")
        return 0
    except (OSError, AlignmentError) as error:
        print(f"compare_provider_runs: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
