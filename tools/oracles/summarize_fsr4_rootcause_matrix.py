#!/usr/bin/env python3
"""Summarize the four diagnostic FSR4 provider/POST replay cases."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

CASES = ("intrinsic_literal", "intrinsic_stable", "scalar_literal", "scalar_stable")
MAX_ZERO_FRACTION_FOR_O0 = 0.999


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def input_signature(provider: dict[str, Any]) -> list[tuple[int, str]]:
    return [
        (int(frame["frame_index"]), str(frame["input_frame_sha256"]))
        for frame in provider.get("frames", [])
    ]


def main() -> int:
    root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
    rows: dict[str, dict[str, Any]] = {}
    signatures: list[list[tuple[int, str]]] = []
    sequence_hashes: list[str] = []

    for name in CASES:
        replay = read_json(root / f"{name}-post-replay.json")
        provider = read_json(root / f"{name}.json")
        captures = replay.get("captures", [])
        if not captures:
            raise SystemExit(f"POST replay for {name} contains no captures")

        provider_signature = input_signature(provider)
        signatures.append(provider_signature)
        sequence_hash = str(provider.get("sequence_hash", ""))
        sequence_hashes.append(sequence_hash)
        provider_capture_frames = sorted(
            int(frame["frame_index"])
            for frame in provider.get("frames", [])
            if frame.get("capture_package") or frame.get("capture_manifest")
        )
        replay_frames = sorted(int(capture["frame_index"]) for capture in captures)
        capture_sequence_hashes = {str(capture.get("sequence_hash", "")) for capture in captures}
        capture_alignment = (
            provider_capture_frames == replay_frames
            and capture_sequence_hashes == {sequence_hash}
            and bool(sequence_hash)
        )

        frame_details = [
            {
                "frame_index": int(capture["frame_index"]),
                "raw_parameter_min_by_channel": capture["raw_parameter_min_by_channel"],
                "raw_parameter_max_by_channel": capture["raw_parameter_max_by_channel"],
                "nonfinite_replayed_model_pixels": int(capture["nonfinite_replayed_model_pixels"]),
                "reference_zero_fraction": float(capture["reference_zero_fraction"]),
                "rgb_within_tolerance": bool(capture["rgb_within_tolerance"]),
                "numerically_valid": bool(capture["numerically_valid"]),
                "reference_finite": bool(capture["reference_finite"]),
                "replay_finite": bool(capture["replay_finite"]),
            }
            for capture in captures
        ]
        max_zero = max(frame["reference_zero_fraction"] for frame in frame_details)
        rows[name] = {
            "sequence_hash": sequence_hash,
            "provider_frame_count": len(provider_signature),
            "provider_audit_frames": provider_capture_frames,
            "replay_frames": replay_frames,
            "capture_frames_aligned": capture_alignment,
            "instrumented_matches_reference": bool(provider.get("instrumentation_matches_reference", False)),
            "provider_outputs_finite": bool(provider.get("provider_outputs_finite", False)),
            "post_rgb_replay_matches": bool(replay.get("validation", {}).get("post_rgb_replay_matches", False)),
            "all_intermediates_numerically_valid": bool(
                replay.get("validation", {}).get("all_intermediates_numerically_valid", False)
            ),
            "all_captures_passed": bool(replay.get("validation", {}).get("all_captures_passed", False)),
            "max_nonfinite_model_pixels": max(
                int(frame["nonfinite_replayed_model_pixels"]) for frame in frame_details
            ),
            "max_reference_zero_fraction": max_zero,
            "nondegenerate_mixed_sequence_output": max_zero < MAX_ZERO_FRACTION_FOR_O0,
            "raw_parameter_abs_max": max(
                abs(float(value))
                for frame in frame_details
                for value in (*frame["raw_parameter_min_by_channel"], *frame["raw_parameter_max_by_channel"])
            ),
            "audited_frames": frame_details,
        }

    inputs_aligned = bool(signatures[0]) and all(signature == signatures[0] for signature in signatures[1:])
    sequences_aligned = bool(sequence_hashes[0]) and all(value == sequence_hashes[0] for value in sequence_hashes)
    matrix_aligned = inputs_aligned and sequences_aligned
    for name, row in rows.items():
        row["matrix_inputs_aligned"] = matrix_aligned
        row["literal_o0_eligible"] = (
            name.endswith("_literal")
            and matrix_aligned
            and row["capture_frames_aligned"]
            and row["instrumented_matches_reference"]
            and row["provider_outputs_finite"]
            and row["post_rgb_replay_matches"]
            and row["all_intermediates_numerically_valid"]
            and row["all_captures_passed"]
            and row["nondegenerate_mixed_sequence_output"]
        )

    intrinsic = rows["intrinsic_literal"]
    intrinsic_stable = rows["intrinsic_stable"]
    scalar = rows["scalar_literal"]
    scalar_stable = rows["scalar_stable"]
    if scalar["literal_o0_eligible"] and not intrinsic["literal_o0_eligible"]:
        diagnosis = (
            "scalar signed-I8 dot4 restores the exact literal O0 path; the native "
            "dot4add_i8packed/driver lowering is the primary Navi10 correctness blocker"
        )
    elif (
        scalar["all_intermediates_numerically_valid"]
        and scalar["nondegenerate_mixed_sequence_output"]
        and not scalar["all_captures_passed"]
        and scalar_stable["all_captures_passed"]
    ):
        diagnosis = (
            "scalar dot4 removes the neural-path failure, but literal POST still fails; "
            "stable POST remains diagnostic pending validation against a supported FSR4 reference"
        )
    elif intrinsic_stable["all_captures_passed"] and not intrinsic["all_captures_passed"]:
        diagnosis = (
            "stable-equivalent POST removes non-finite reconstruction while intrinsic logits remain problematic; "
            "this does not unlock O1-O13 because it is not literal pinned-source O0"
        )
    elif intrinsic["literal_o0_eligible"]:
        diagnosis = "baseline intrinsic/literal path is numerically valid and nondegenerate; previous failure was not reproduced"
    else:
        diagnosis = (
            "root cause remains upstream of a source-valid POST; inspect PRE/model tensor scaling, initializer selection, "
            "signed-I8 arithmetic and pass-boundary tensors before enabling O1-O13"
        )

    gate = bool(intrinsic["literal_o0_eligible"] or scalar["literal_o0_eligible"])
    summary = {
        "schema": "f4n10.fsr4-rootcause-matrix.v3",
        "sequence_hash": sequence_hashes[0],
        "input_frame_hashes_aligned_across_cases": inputs_aligned,
        "sequence_hashes_aligned_across_cases": sequences_aligned,
        "cases": rows,
        "diagnosis": diagnosis,
        "o1_o13_may_proceed_on_at_least_one_literal_variant": gate,
        "stable_post_is_diagnostic_only": True,
        "mixed_sequence_zero_fraction_gate": MAX_ZERO_FRACTION_FOR_O0,
        "rule": (
            "Unlock O1-O13 only on a literal pinned-source variant with aligned inputs, finite intermediates, "
            "replay agreement, nondegenerate mixed-sequence output, and instrumented/reference equality. "
            "Stable POST alone never unlocks O1-O13."
        ),
    }
    output = root / "summary.json"
    output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
