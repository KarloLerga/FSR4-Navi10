from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from f4seq_format import F4SeqError, validate_f4seq


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a versioned FSR4/FSR3 teacher input sequence.")
    parser.add_argument("sequence", type=Path, help="input .f4seq container")
    args = parser.parse_args()
    try:
        result = validate_f4seq(args.sequence)
    except (OSError, F4SeqError) as error:
        print(f"validate_f4seq: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
