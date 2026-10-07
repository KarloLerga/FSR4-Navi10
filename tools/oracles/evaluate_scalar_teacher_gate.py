#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def read(path: str | Path) -> dict:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def frame_hashes(report: dict) -> dict[int, str] | None:
    frames = report.get("frames")
    if not isinstance(frames, list):
        return None
    hashes: dict[int, str] = {}
    for frame in frames:
        if not isinstance(frame, dict):
            return None
        index = frame.get("frame_index")
        digest = frame.get("input_frame_sha256")
        if type(index) is not int or not isinstance(digest, str) or len(digest) != 64:
            return None
        if index in hashes:
            return None
        hashes[index] = digest
    return hashes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cpu", required=True)
    ap.add_argument("--gpu", nargs="+", required=True)
    ap.add_argument("--instrumentation", required=True)
    ap.add_argument("--dot4", required=True)
    ap.add_argument("--sequence-report", required=True)
    ap.add_argument("--fsr3-report", required=True)
    ap.add_argument("--basis-audit", required=True)
    ap.add_argument("--repeatability", required=True)
    ap.add_argument("--output", required=True)
    a = ap.parse_args()

    cpu = read(a.cpu)
    gpu = [read(p) for p in a.gpu]
    inst = read(a.instrumentation)
    dot = read(a.dot4)
    sequence = read(a.sequence_report)
    fsr3 = read(a.fsr3_report)
    basis = read(a.basis_audit)
    repeatability = read(a.repeatability)

    cpu_ok = bool(cpu.get("validation", {}).get("all_captures_passed"))
    gpu_ok = bool(gpu) and all(bool(x.get("passed")) for x in gpu)
    inst_ok = bool(inst.get("numerically_close"))
    dot_ok = bool(dot.get("native_matches_scalar"))

    fsr4_hashes = frame_hashes(sequence)
    fsr3_hashes = frame_hashes(fsr3)
    frame_count = sequence.get("frame_count")
    fsr3_sequence = fsr3.get("sequence", {})
    alignment_ok = (
        type(frame_count) is int
        and frame_count > 0
        and sequence.get("sequence_hash") == fsr3_sequence.get("sequence_hash")
        and fsr4_hashes is not None
        and fsr3_hashes is not None
        and set(fsr4_hashes) == set(range(frame_count))
        and fsr3_hashes == fsr4_hashes
    )
    basis_ok = (
        basis.get("passed") is True
        and basis.get("sequence_hash") == sequence.get("sequence_hash")
    )
    repeatability_ok = (
        repeatability.get("repeatable") is True
        and repeatability.get("same_inputs") is True
        and repeatability.get("sequence_hash") == sequence.get("sequence_hash")
        and repeatability.get("first_report_build_commit") == sequence.get("build_commit")
        and repeatability.get("repeat_report_build_commit") == sequence.get("build_commit")
    )

    eligible = cpu_ok and gpu_ok and inst_ok and alignment_ok and basis_ok and repeatability_ok
    if eligible:
        if dot_ok:
            next_action = (
                "Unlock O1-O13 for scalar-literal teacher. Native dot4 conforms; "
                "trace any full-model intrinsic/scalar divergence separately."
            )
        else:
            next_action = (
                "Unlock O1-O13 for scalar-literal teacher. Keep native dot4 disabled "
                "and use scalar signed-I8 semantics as the correctness path."
            )
    else:
        failed = []
        if not cpu_ok:
            failed.append("corrected CPU POST replay")
        if not gpu_ok:
            failed.append("GPU POST oracle")
        if not inst_ok:
            failed.append("instrumented/reference numeric equivalence")
        if not alignment_ok:
            failed.append("FSR3/FSR4 input-frame alignment")
        if not basis_ok:
            failed.append("FSR3 accumulation-site basis audit")
        if not repeatability_ok:
            failed.append("same-input FSR4 run-to-run repeatability")
        next_action = "Keep O1-O13 locked. Fix: " + ", ".join(failed) + "."

    report = {
        "schema": "f4n10.scalar-teacher-gate.v1",
        "teacher_eligible": eligible,
        "cpu_post_ok": cpu_ok,
        "gpu_post_ok": gpu_ok,
        "instrumentation_ok": inst_ok,
        "sequence_alignment_ok": alignment_ok,
        "aligned_frame_count": frame_count if alignment_ok else 0,
        "fsr3_basis_audit_ok": basis_ok,
        "run_to_run_repeatability_ok": repeatability_ok,
        "native_dot4_matches_scalar": dot_ok,
        "next_action": next_action,
    }
    p = Path(a.output)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if eligible else 2


if __name__ == "__main__":
    raise SystemExit(main())
