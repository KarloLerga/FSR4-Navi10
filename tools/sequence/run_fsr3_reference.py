from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from f4seq_format import F4SeqError, validate_f4seq

REPO_ROOT = Path(__file__).resolve().parents[2]


def normalize_repo_paths(report: dict) -> None:
    for key in ("shader_manifest",):
        path = report.get(key)
        if isinstance(path, str):
            try:
                report[key] = Path(path).resolve().relative_to(REPO_ROOT).as_posix()
            except ValueError:
                pass
    for frame in report.get("frames", []):
        path = frame.get("capture_manifest") if isinstance(frame, dict) else None
        if isinstance(path, str):
            try:
                frame["capture_manifest"] = Path(path).resolve().relative_to(REPO_ROOT).as_posix()
            except ValueError:
                pass


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate and run one .f4seq through the pinned FSR3.1.5 reference provider."
    )
    parser.add_argument("executable", type=Path, help="built fsr4n10_fsr3_reference.exe")
    parser.add_argument("sequence", type=Path, help="input .f4seq")
    parser.add_argument("report", type=Path, help="output sequence report JSON")
    parser.add_argument("--capture-root", type=Path,
                        help="write raw FSR3 input/output/tap arrays for first, last, reset, and cut frames")
    args = parser.parse_args()
    try:
        validate_f4seq(args.sequence)
        report = args.report.resolve()
        report.parent.mkdir(parents=True, exist_ok=True)
        command = [str(args.executable.resolve()), str(args.sequence.resolve()), str(report)]
        if args.capture_root is not None:
            command.append(str(args.capture_root.resolve()))
        completed = subprocess.run(command, check=False)
        if completed.returncode != 0:
            return completed.returncode
        report_data = json.loads(report.read_text(encoding="utf-8"))
        normalize_repo_paths(report_data)
        report.write_text(json.dumps(report_data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"FSR3.1.5 reference report: {report}")
        return 0
    except (OSError, json.JSONDecodeError, F4SeqError) as error:
        print(f"run_fsr3_reference: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
