from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from f4seq_format import F4SeqError, build_f4seq


def main() -> int:
    parser = argparse.ArgumentParser(description="Pack input render buffers described by sequence.json into .f4seq.")
    parser.add_argument("manifest", type=Path, help="JSON with sequence metadata and frame input paths")
    parser.add_argument("input_root", type=Path, help="root containing the raw input array paths")
    parser.add_argument("output", type=Path, help="output .f4seq file")
    args = parser.parse_args()
    try:
        source = json.loads(args.manifest.read_text(encoding="utf-8"))
        if not isinstance(source, dict) or set(source) != {"sequence", "frames"}:
            raise F4SeqError("source manifest must contain exactly sequence and frames")
        result = build_f4seq(args.output, source["sequence"], source["frames"], args.input_root)
    except (OSError, json.JSONDecodeError, F4SeqError) as error:
        print(f"pack_f4seq: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
