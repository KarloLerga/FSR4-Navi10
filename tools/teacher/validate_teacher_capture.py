from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from capture_format import CaptureFormatError, validate_capture


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate FSR4 teacher capture package structure and integrity.")
    parser.add_argument("capture", type=Path, help=".f4cap ZIP package")
    args = parser.parse_args()
    try:
        summary = validate_capture(args.capture)
    except (OSError, CaptureFormatError) as error:
        print(f"validate_teacher_capture: {error}", file=sys.stderr)
        return 2
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
