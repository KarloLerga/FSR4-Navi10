from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from f4seq_format import F4SeqError, validate_f4seq

REPO_ROOT = Path(__file__).resolve().parents[2]
TEACHER_TOOLS = Path(__file__).resolve().parents[1] / "teacher"
sys.path.insert(0, str(TEACHER_TOOLS))
from capture_format import CaptureFormatError, package_capture  # noqa: E402


def normalize_repo_path(value: object) -> object:
    if not isinstance(value, str):
        return value
    try:
        return Path(value).resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return value


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate and run one stateful .f4seq through the pinned GPU FSR4 provider."
    )
    parser.add_argument("harness", type=Path, help="built fsr4n10_harness.exe")
    parser.add_argument("sequence", type=Path, help="input .f4seq")
    parser.add_argument("report", type=Path, help="output sequence report JSON")
    parser.add_argument("--capture-root", type=Path,
                        help="also read provider taps for first/last frames and package audit .f4cap files")
    args = parser.parse_args()
    try:
        validate_f4seq(args.sequence)
        command = [str(args.harness.resolve()), "--run-fsr4-provider-sequence",
                   str(args.sequence.resolve()), str(args.report.resolve())]
        capture_root = args.capture_root.resolve() if args.capture_root else None
        if capture_root is not None:
            command.append(str(capture_root))
        completed = subprocess.run(command, check=False)
        if completed.returncode != 0:
            return completed.returncode
        report_path = args.report.resolve()
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if capture_root is not None:
            captures = []
            for manifest_path in sorted(capture_root.glob("frame_*/manifest.json")):
                frame_root = manifest_path.parent
                package_path = frame_root.with_suffix(".f4cap")
                summary = package_capture(json.loads(manifest_path.read_text(encoding="utf-8")),
                                          frame_root, package_path)
                captures.append({"path": str(package_path), **summary})
                for frame in report["frames"]:
                    if frame["frame_index"] == summary["frame_index"]:
                        frame["capture_package"] = str(package_path)
            if not captures:
                raise F4SeqError("provider completed but did not emit the requested audit frames")
            report["audit_capture_packages"] = captures
        report["shader_manifest"] = normalize_repo_path(report.get("shader_manifest"))
        for frame in report.get("frames", []):
            for key in ("capture_manifest", "capture_package"):
                if key in frame:
                    frame[key] = normalize_repo_path(frame[key])
        for capture in report.get("audit_capture_packages", []):
            capture["path"] = normalize_repo_path(capture.get("path"))
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"FSR4 teacher sequence report: {args.report}")
        return 0
    except (OSError, json.JSONDecodeError, F4SeqError, CaptureFormatError) as error:
        print(f"run_fsr4_teacher: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
