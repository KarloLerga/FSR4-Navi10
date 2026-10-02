#!/usr/bin/env python3
"""Generate a deterministic 960x540 sRGB PPM fixture for the I8 image smoke."""

from __future__ import annotations

import argparse
from pathlib import Path


WIDTH = 960
HEIGHT = 540


def generate_frame() -> bytes:
    pixels = bytearray()
    for y in range(HEIGHT):
        for x in range(WIDTH):
            u = x / WIDTH
            v = y / HEIGHT
            red = int(35 + 90 * u)
            green = int(55 + 120 * v)
            blue = int(145 - 80 * u + 25 * v)

            dx = (x - 480) / 190
            dy = (y - 260) / 135
            if dx * dx + dy * dy < 1:
                red, green, blue = 210, 65 + int(50 * (1 - v)), 35
                if ((x // 9) + (y // 9)) % 2:
                    red, green, blue = 235, 125, 40

            if 90 < x < 190 and 380 < y < 475:
                red, green, blue = (35, 215, 170) if ((x // 4) ^ (y // 4)) & 1 else (15, 70, 95)
            if x % 64 == 0 or y % 64 == 0:
                red, green, blue = 245, 245, 235

            pixels.extend((red, green, blue))

    return f"P6\n{WIDTH} {HEIGHT}\n255\n".encode("ascii") + pixels


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="destination PPM path")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    data = generate_frame()
    args.output.write_bytes(data)
    print(f"Wrote deterministic {WIDTH}x{HEIGHT} P6 sRGB fixture ({len(data)} bytes): {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
