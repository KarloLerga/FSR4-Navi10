#!/usr/bin/env python3
"""Validate FSR3 accumulation C/H taps against the FSR4 root-cause inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


FSR4_CASES = (
    "intrinsic_literal",
    "intrinsic_stable",
    "scalar_literal",
    "scalar_stable",
)
TAP_ARRAYS = (
    "current_candidate_accum_ycocg_plus_alpha",
    "reprojected_history_accum_ycocg_plus_alpha",
    "current_candidate_linear_rgb_plus_alpha",
    "reprojected_history_linear_rgb_plus_alpha",
)
EXPECTED_AUDIT_FRAMES = (0, 4, 7)


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def frame_hashes(report: dict[str, Any], label: str) -> dict[int, str]:
    frames = report.get("frames")
    if not isinstance(frames, list):
        raise ValueError(f"{label}: missing frame list")
    result: dict[int, str] = {}
    for frame in frames:
        index = int(frame["frame_index"])
        value = frame.get("input_frame_sha256")
        if not isinstance(value, str) or len(value) != 64:
            raise ValueError(f"{label}: invalid input hash for frame {index}")
        if index in result:
            raise ValueError(f"{label}: duplicate frame {index}")
        result[index] = value
    return result


def audit(args: argparse.Namespace) -> dict[str, Any]:
    fsr3_path = args.fsr3_report.resolve()
    matrix_dir = args.fsr4_matrix_dir.resolve()
    capture_root = args.capture_root.resolve()
    fsr3 = load_json(fsr3_path)
    matrix = load_json(matrix_dir / "summary.json")

    fsr3_sequence = fsr3.get("sequence", {})
    sequence_hash = fsr3_sequence.get("sequence_hash")
    if sequence_hash != matrix.get("sequence_hash"):
        raise ValueError("FSR3 and FSR4 matrix sequence hashes differ")

    fsr3_inputs = frame_hashes(fsr3, "FSR3")
    expected_frame_indices = set(range(int(fsr3_sequence.get("frame_count", -1))))
    case_inputs: dict[str, dict[int, str]] = {}
    for case in FSR4_CASES:
        report = load_json(matrix_dir / f"{case}.json")
        if report.get("sequence_hash") != sequence_hash:
            raise ValueError(f"{case}: sequence hash differs from FSR3")
        case_inputs[case] = frame_hashes(report, case)

    input_alignment = {
        "frame_count": len(fsr3_inputs),
        "expected_frame_count": len(expected_frame_indices),
        "all_expected_frames_present": set(fsr3_inputs) == expected_frame_indices
        and all(set(values) == expected_frame_indices for values in case_inputs.values()),
        "fsr3_matches_every_fsr4_case": all(
            fsr3_inputs == values for values in case_inputs.values()
        ),
        "all_fsr4_cases_match_each_other": len(
            {tuple(sorted(values.items())) for values in case_inputs.values()}
        ) == 1,
        "cases": {
            case: {
                "frame_count": len(values),
                "matches_fsr3": values == fsr3_inputs,
            }
            for case, values in case_inputs.items()
        },
    }

    frame_reports = {
        int(frame["frame_index"]): frame for frame in fsr3.get("frames", [])
    }
    captured_frame_indices = tuple(
        sorted(
            index
            for index, frame in frame_reports.items()
            if frame.get("capture_manifest")
        )
    )
    if captured_frame_indices != EXPECTED_AUDIT_FRAMES:
        raise ValueError(
            "FSR3 capture frames differ from expected audit frames "
            f"{list(EXPECTED_AUDIT_FRAMES)}: {list(captured_frame_indices)}"
        )

    captured_frames: list[dict[str, Any]] = []
    exact_final_output_capture = True
    taps_well_formed = True
    for frame_index in EXPECTED_AUDIT_FRAMES:
        frame_report = frame_reports[frame_index]
        frame_root = capture_root / f"frame_{frame_index}"
        capture_manifest = load_json(frame_root / "manifest.json")
        metadata = capture_manifest.get("metadata", {})
        if metadata.get("frame_index") != frame_index:
            raise ValueError(f"capture manifest frame mismatch at {frame_index}")
        if metadata.get("sequence_hash") != sequence_hash:
            raise ValueError(f"capture manifest sequence mismatch at {frame_index}")
        if metadata.get("input_frame_sha256") != fsr3_inputs[frame_index]:
            raise ValueError(f"capture input hash mismatch at frame {frame_index}")

        arrays = capture_manifest.get("arrays", {})
        output_descriptor = arrays.get("final_output")
        if not isinstance(output_descriptor, dict):
            raise ValueError(f"missing final_output capture at frame {frame_index}")
        output_path = frame_root / output_descriptor["file"]
        output_hash = sha256_file(output_path)
        expected_output_bytes = 1920 * 1080 * 4 * 2
        output_well_formed = (
            output_descriptor.get("dtype") == "<f2"
            and output_descriptor.get("shape") == [1080, 1920, 4]
            and output_path.stat().st_size == expected_output_bytes
        )
        output_matches = (
            output_well_formed
            and output_hash == frame_report.get("reference_output_sha256")
        )
        exact_final_output_capture &= output_matches

        taps: dict[str, Any] = {}
        for name in TAP_ARRAYS:
            descriptor = arrays.get(name)
            if not isinstance(descriptor, dict):
                taps_well_formed = False
                taps[name] = {"present": False}
                continue
            path = frame_root / descriptor["file"]
            shape = descriptor.get("shape")
            dtype = descriptor.get("dtype")
            expected_bytes = 1920 * 1080 * 4 * 2
            actual_bytes = path.stat().st_size if path.is_file() else None
            well_formed = (
                path.is_file()
                and shape == [1080, 1920, 4]
                and dtype == "<f2"
                and actual_bytes == expected_bytes
            )
            taps_well_formed &= well_formed
            taps[name] = {
                "present": path.is_file(),
                "dtype": dtype,
                "shape": shape,
                "bytes": actual_bytes,
                "expected_bytes": expected_bytes,
                "sha256": sha256_file(path) if path.is_file() else None,
                "well_formed": well_formed,
            }

        captured_frames.append(
            {
                "frame_index": frame_index,
                "input_frame_sha256": fsr3_inputs[frame_index],
                "final_output_sha256": output_hash,
                "final_output_matches_reference": output_matches,
                "final_output_well_formed": output_well_formed,
                "taps": taps,
            }
        )

    validation = fsr3.get("validation", {})
    checks = {
        "input_frame_hashes_aligned": input_alignment[
            "fsr3_matches_every_fsr4_case"
        ]
        and input_alignment["all_fsr4_cases_match_each_other"]
        and input_alignment["all_expected_frames_present"],
        "fsr3_exact_accumulation_site_basis_taps": bool(
            validation.get("exact_accumulation_site_basis_taps")
        ),
        "fsr3_instrumented_reference_outputs_match": bool(
            validation.get("instrumented_reference_outputs_match")
        ),
        "four_taps_present_with_expected_shape_and_dtype": taps_well_formed,
        "final_output_capture_matches_reference": exact_final_output_capture,
        "quality_not_claimed": not bool(validation.get("quality_claimed")),
    }
    result = {
        "schema": "f4n10.fsr3-delta-basis-capture-audit.v1",
        "sequence_hash": sequence_hash,
        "sequence_id": fsr3_sequence.get("id"),
        "gpu_name": fsr3.get("gpu_name"),
        "provider": fsr3.get("provider"),
        "shader_manifest_sha256": fsr3.get("shader_manifest_sha256"),
        "audit_frames": captured_frames,
        "input_frame_alignment": input_alignment,
        "checks": checks,
        "passed": all(checks.values()),
        "quality_claimed": bool(validation.get("quality_claimed")),
        "note": (
            "C/H taps are recorded at the FSR3.1.5 accumulation site for "
            "diagnostic comparison; this audit makes no quality claim."
        ),
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fsr3-report", type=Path, required=True)
    parser.add_argument("--fsr4-matrix-dir", type=Path, required=True)
    parser.add_argument("--capture-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        result = audit(args)
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"passed": result["passed"], "output": str(args.output)}))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
