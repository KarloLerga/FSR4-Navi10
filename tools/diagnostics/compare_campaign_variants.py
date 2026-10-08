#!/usr/bin/env python3
"""Compare same-seed race-bisector captures with and without global barriers."""
from __future__ import annotations
import argparse
import json
from pathlib import Path


def _case_map(document: dict) -> dict:
    result = {}
    for case in document.get("cases", []):
        key = (case["seed"], case["pass_name"], int(case["repeat"]))
        if key in result:
            raise ValueError(f"duplicate campaign case: {key}")
        result[key] = case
    return result


def _sequence_report(case: dict) -> dict:
    path = Path(case["report_path"])
    report = json.loads(path.read_text(encoding="utf-8"))
    hashes = [frame.get("input_frame_sha256", "") for frame in report.get("frames", [])]
    if report.get("sequence_hash") != case.get("sequence_hash") or hashes != case.get("input_hashes"):
        raise ValueError(f"campaign provenance does not match sequence report: {path}")
    return report


def _output_comparison(left: dict, right: dict) -> dict:
    lf, rf = left.get("frames", []), right.get("frames", [])
    paired = len(lf) == len(rf) and bool(lf)
    input_equal = paired and all(
        a.get("input_frame_sha256") == b.get("input_frame_sha256")
        for a, b in zip(lf, rf)
    )
    outputs = {}
    for name, field in (("instrumented", "instrumented_output_sha256"),
                        ("ordinary", "reference_output_sha256")):
        outputs[name] = paired and input_equal and all(
            a.get(field) == b.get(field) for a, b in zip(lf, rf)
        )
    return {"frame_count_standard": len(lf), "frame_count_barrier": len(rf),
            "inputs_equal": input_equal, "outputs_equal": outputs}


def compare_campaigns(standard: dict, barrier: dict) -> dict:
    standard_cases, barrier_cases = _case_map(standard), _case_map(barrier)
    common = sorted(set(standard_cases) & set(barrier_cases))
    rows = []
    for seed, pass_name, repeat in common:
        left, right = standard_cases[(seed, pass_name, repeat)], barrier_cases[(seed, pass_name, repeat)]
        valid = not left.get("error") and not right.get("error")
        row = {"seed": seed, "pass_name": pass_name, "repeat": repeat,
               "valid": valid, "inputs_equal": False, "scratch_equal": {}}
        if valid:
            left_report, right_report = _sequence_report(left), _sequence_report(right)
            row["inputs_equal"] = (
                left_report.get("sequence_hash") == right_report.get("sequence_hash") and
                [f.get("input_frame_sha256", "") for f in left_report.get("frames", [])] ==
                [f.get("input_frame_sha256", "") for f in right_report.get("frames", [])]
            )
            for context in ("instrumented", "ordinary"):
                left_file = left.get("files", {}).get(context, {})
                right_file = right.get("files", {}).get(context, {})
                row["scratch_equal"][context] = (
                    left_file.get("size") == right_file.get("size") and
                    left_file.get("sha256") == right_file.get("sha256") and
                    bool(left_file.get("sha256"))
                )
            if pass_name == "full":
                row["full_rgb"] = _output_comparison(left_report, right_report)
        rows.append(row)

    full_rows = [r for r in rows if r["pass_name"] == "full" and r["valid"]]
    differing_full = [r for r in full_rows if r.get("inputs_equal") and
                      not all(r.get("full_rgb", {}).get("outputs_equal", {}).values())]
    differing_scratch = [r for r in rows if r["valid"] and r.get("inputs_equal") and
                         not all(r.get("scratch_equal", {}).values())]
    complete = len(common) == len(standard_cases) == len(barrier_cases)
    all_inputs_equal = complete and bool(rows) and all(r["valid"] and r["inputs_equal"] for r in rows)
    return {
        "schema": "f4n10.scratch-campaign-variant-comparison.v1",
        "standard_variant": standard.get("variant"),
        "barrier_variant": barrier.get("variant"),
        "standard_case_count": len(standard_cases),
        "barrier_case_count": len(barrier_cases),
        "common_case_count": len(common),
        "case_coverage_complete": complete,
        "missing_from_barrier": [list(k) for k in sorted(set(standard_cases) - set(barrier_cases))],
        "missing_from_standard": [list(k) for k in sorted(set(barrier_cases) - set(standard_cases))],
        "all_common_inputs_equal": all_inputs_equal,
        "full_rgb_differences_on_equal_inputs": len(differing_full),
        "scratch_differences_on_equal_inputs": len(differing_scratch),
        "interpretation": (
            ["Captured results differ between builds on identical inputs. This is consistent with order/timing sensitivity, but existing nondeterminism and independent run state prevent attributing the difference to barriers alone."]
            if differing_full or differing_scratch else
            ["The sampled global-barrier intervention did not change captured results on identical inputs; this does not rule out other synchronization defects."]
        ),
        "cases": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--standard", type=Path, required=True)
    parser.add_argument("--barrier", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    standard = json.loads(args.standard.read_text(encoding="utf-8"))
    barrier = json.loads(args.barrier.read_text(encoding="utf-8"))
    result = compare_campaigns(standard, barrier)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    summary = {k: result[k] for k in (
        "common_case_count", "all_common_inputs_equal", "full_rgb_differences_on_equal_inputs",
        "scratch_differences_on_equal_inputs", "interpretation")}
    print(json.dumps(summary, indent=2))
    return 0 if result["all_common_inputs_equal"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
