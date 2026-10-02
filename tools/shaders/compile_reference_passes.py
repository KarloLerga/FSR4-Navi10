#!/usr/bin/env python3
"""Compile pinned upstream FSR4 I8 shader pass sets with DXC."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


PRESETS = ("native", "quality", "balanced", "performance", "drs", "ultraperf")
TIERS = ("1080", "2160", "4320")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fsr4-root", type=Path, required=True)
    parser.add_argument("--dxc", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--preset", choices=(*PRESETS, "all"), default="native")
    parser.add_argument("--tier", choices=(*TIERS, "all"), default="1080")
    args = parser.parse_args()

    fsr4_root = args.fsr4_root.resolve()
    dxc = args.dxc.resolve()
    include_root = fsr4_root / "dx12"
    if not dxc.is_file():
        parser.error(f"DXC executable is missing: {dxc}")

    args.output.mkdir(parents=True, exist_ok=True)
    compiler_version = subprocess.run(
        [str(dxc), "--version"], check=True, capture_output=True, text=True
    ).stdout.strip()

    presets = PRESETS if args.preset == "all" else (args.preset,)
    tiers = TIERS if args.tier == "all" else (args.tier,)
    for preset in presets:
        for tier in tiers:
            source = fsr4_root / "internal" / "shaders" / f"fsr4_model_v07_i8_{preset}" / f"passes_{tier}.hlsl"
            if not source.is_file():
                parser.error(f"upstream shader source is missing: {source}")
            output_dir = args.output / preset / tier
            output_dir.mkdir(parents=True, exist_ok=True)
            passes = []
            for pass_index in range(14):
                entry = f"fsr4_model_v07_i8_pass{pass_index}"
                output = output_dir / f"pass_{pass_index:02d}.dxil"
                command = [
                    str(dxc),
                    "-no-warnings",
                    "-O3",
                    "-enable-16bit-types",
                    "-HV",
                    "2021",
                    "-T",
                    "cs_6_6",
                    f"-DMLSR_PASS_{pass_index}",
                    "-I",
                    str(include_root),
                    "-E",
                    entry,
                    str(source),
                    "-Fo",
                    str(output),
                ]
                subprocess.run(command, check=True)
                roles = {0: "pre_model", 13: "post_model"}
                passes.append(
                    {
                        "index": pass_index,
                        "role": roles.get(pass_index, "model"),
                        "entryPoint": entry,
                        "define": f"MLSR_PASS_{pass_index}",
                        "dxil": output.name,
                        "sizeBytes": output.stat().st_size,
                        "sha256": sha256(output),
                    }
                )

            manifest = {
                "format": "fsr4n10-reference-shader-manifest-v1",
                "backend": "upstream_i8",
                "preset": preset,
                "resolutionTier": tier,
                "source": str(source.relative_to(fsr4_root)).replace("\\", "/"),
                "sourceSha256": sha256(source),
                "target": "cs_6_6",
                "compiler": compiler_version,
                "flags": ["-no-warnings", "-O3", "-enable-16bit-types", "-HV 2021"],
                "passes": passes,
            }
            manifest_path = output_dir / "manifest.json"
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    combinations = []
    indexed_pass_count = 0
    # Build the index from every completed combination so a targeted rebuild
    # does not discard entries produced by an earlier --preset all/--tier all run.
    for manifest_path in sorted(args.output.glob("*/*/manifest.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        indexed_pass_count += len(manifest["passes"])
        combinations.append(
            {
                "preset": manifest["preset"],
                "resolutionTier": manifest["resolutionTier"],
                "manifest": manifest_path.relative_to(args.output).as_posix(),
                "manifestSha256": sha256(manifest_path),
            }
        )

    index = {
        "format": "fsr4n10-reference-shader-index-v1",
        "backend": "upstream_i8",
        "compiler": compiler_version,
        "compiledPassCount": indexed_pass_count,
        "combinations": combinations,
    }
    index_path = args.output / "index.json"
    index_path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    print(f"Indexed {indexed_pass_count} upstream I8 pass entry points across {len(combinations)} preset/tier combinations: {index_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
