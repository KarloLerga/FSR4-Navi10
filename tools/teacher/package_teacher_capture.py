from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from capture_format import CaptureFormatError, package_capture


def main() -> int:
    parser = argparse.ArgumentParser(description="Package and validate one deterministic FSR4 teacher frame capture.")
    parser.add_argument("manifest", type=Path, help="input JSON manifest; array entries use file, dtype and shape")
    parser.add_argument("arrays_dir", type=Path, help="root directory containing arrays/<name> raw files")
    parser.add_argument("output", type=Path, help="output .f4cap package")
    args = parser.parse_args()
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        summary = package_capture(manifest, args.arrays_dir, args.output)
    except (OSError, json.JSONDecodeError, CaptureFormatError) as error:
        print(f"package_teacher_capture: {error}", file=sys.stderr)
        return 2
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
