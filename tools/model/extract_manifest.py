#!/usr/bin/env python3
"""Inventory the pinned FSR4 model sources without copying upstream assets."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


ENTRYPOINT = re.compile(
    r"^\s*void\s+(?P<name>fsr4_model_v07_(?:i8|fp8_no_scale)_pass"
    r"(?P<index>\d+)(?P<padding>_post)?)\s*\(",
    re.MULTILINE,
)
MODEL_DIR = Path("Kits/FidelityFX/upscalers/fsr4")
PRESETS = ("native", "quality", "balanced", "performance", "ultraperf", "drs")
RESOLUTIONS = ("1080", "2160", "4320")


class InventoryError(RuntimeError):
    """Raised when the upstream does not match the pinned model contract."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relative_posix(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def read_commit(source_root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(source_root), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.PIPE,
        ).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise InventoryError(f"cannot read upstream Git commit: {exc}") from exc


def classify_entrypoint(name: str, index: int, padding: bool) -> str:
    if padding:
        return "padding_reset"
    if index == 0:
        return "model_pre"
    if index == 13:
        return "model_post"
    if 1 <= index <= 12:
        return "neural_pass"
    raise InventoryError(f"unexpected upstream model entry point: {name}")


def parse_entrypoints(shader_path: Path) -> list[dict[str, Any]]:
    source = shader_path.read_text(encoding="utf-8")
    entrypoints = []
    for match in ENTRYPOINT.finditer(source):
        name = match.group("name")
        index = int(match.group("index"))
        padding = match.group("padding") is not None
        entrypoints.append(
            {
                "name": name,
                "index": index,
                "role": classify_entrypoint(name, index, padding),
                "paddingReset": padding,
                "line": source.count("\n", 0, match.start()) + 1,
            }
        )
    return entrypoints


def source_record(path: Path, source_root: Path) -> dict[str, Any]:
    return {
        "path": relative_posix(path, source_root),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def provider_contract(source_root: Path, fsr4_root: Path) -> dict[str, Any]:
    provider_path = fsr4_root / "dx12/ffx_provider_fsr4_dx12.cpp"
    selector_path = fsr4_root / "internal/shader_selector.cpp"
    provider = provider_path.read_text(encoding="utf-8")
    selector = selector_path.read_text(encoding="utf-8")

    loop = re.search(
        r"for\s*\(\s*uint32_t\s+passIndex\s*=\s*(\d+)\s*;"
        r"\s*passIndex\s*<\s*(\d+)\s*;",
        provider,
    )
    if not loop:
        raise InventoryError("could not derive the neural pass range from the upstream provider")
    first_network_pass, pass_end = map(int, loop.groups())
    if first_network_pass != 1 or pass_end != 13:
        raise InventoryError(
            "unexpected provider neural pass range: "
            f"[{first_network_pass}, {pass_end}); review the source before updating the parser"
        )
    if "GetPreShaderBlob" not in selector or "GetPostShaderBlob" not in selector:
        raise InventoryError("upstream shader selector no longer exposes pre/post model shaders")

    return {
        "preEntryPointIndex": 0,
        "neuralPassFirst": first_network_pass,
        "neuralPassLast": pass_end - 1,
        "postEntryPointIndex": 13,
        "paddingResetIndices": list(range(13)),
        "providerLoop": source_record(provider_path, source_root),
        "shaderSelector": source_record(selector_path, source_root),
    }


def build_model(
    source_root: Path,
    fsr4_root: Path,
    preset: str,
    representation: str,
    initializer_path: Path,
    pass_directory: Path,
    pass_filename: str,
) -> dict[str, Any]:
    initializer = source_record(initializer_path, source_root)
    resolution_records: list[dict[str, Any]] = []
    for resolution in RESOLUTIONS:
        shader_path = pass_directory / pass_filename.format(resolution=resolution)
        if not shader_path.is_file():
            raise InventoryError(f"missing {resolution} shader source: {shader_path}")
        entrypoints = parse_entrypoints(shader_path)
        neural = [entry for entry in entrypoints if entry["role"] == "neural_pass"]
        pre = [entry for entry in entrypoints if entry["role"] == "model_pre"]
        post = [entry for entry in entrypoints if entry["role"] == "model_post"]
        resets = [entry for entry in entrypoints if entry["role"] == "padding_reset"]
        if len(neural) != 12 or len(pre) != 1 or len(post) != 1 or len(resets) != 13:
            raise InventoryError(
                f"unexpected pass layout in {shader_path}: neural={len(neural)}, "
                f"pre={len(pre)}, post={len(post)}, padding-reset={len(resets)}"
            )
        resolution_records.append(
            {
                "resolutionTier": resolution,
                "shader": source_record(shader_path, source_root),
                "entryPoints": entrypoints,
            }
        )

    return {
        "modelId": f"fsr4_model_v07_{representation}_{preset}",
        "representation": representation,
        "preset": preset,
        "initializer": initializer,
        "resolutions": resolution_records,
    }


def create_inventory(source_root: Path, lock_path: Path) -> dict[str, Any]:
    source_root = source_root.resolve()
    lock = json.loads(lock_path.read_text(encoding="utf-8-sig"))
    locked_source = lock["fsr4Source"]
    actual_commit = read_commit(source_root)
    if actual_commit != locked_source["actualCommit"]:
        raise InventoryError(
            f"source commit {actual_commit} does not match third_party/LOCK.json "
            f"({locked_source['actualCommit']})"
        )

    fsr4_root = source_root / MODEL_DIR
    shader_root = fsr4_root / "internal/shaders"
    if not fsr4_root.is_dir():
        raise InventoryError(f"missing required source directory: {fsr4_root}")
    contract = provider_contract(source_root, fsr4_root)

    models: list[dict[str, Any]] = []
    for preset in PRESETS:
        i8_dir = shader_root / f"fsr4_model_v07_i8_{preset}"
        models.append(
            build_model(
                source_root,
                fsr4_root,
                preset,
                "i8",
                i8_dir / "initializers.bin",
                i8_dir,
                "passes_{resolution}.hlsl",
            )
        )

        fp8_dir = shader_root / f"fsr4_model_v07_fp8_no_scale_{preset}"
        models.append(
            build_model(
                source_root,
                fsr4_root,
                preset,
                "fp8_no_scale",
                fp8_dir / "initializers.bin",
                shader_root,
                "fsr4_model_v07_fp8_no_scale_passes_{resolution}.hlsl",
            )
        )

    return {
        "schemaVersion": 1,
        "inventoryKind": "upstream_source_inventory",
        "sourceCommit": actual_commit,
        "sourceRepository": locked_source["repository"],
        "license": "MIT (see the fetched upstream docs/license.md)",
        "sourcePath": locked_source["requiredPath"],
        "providerContract": contract,
        "models": models,
        "coverage": {
            "presets": list(PRESETS),
            "resolutionTiers": list(RESOLUTIONS),
            "neuralPassCount": contract["neuralPassLast"] - contract["neuralPassFirst"] + 1,
            "includesTensorExtraction": False,
            "includesFP16Conversion": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("third_party/fidelityfx-fsr4-source"),
        help="path to the clean pinned FidelityFX source checkout",
    )
    parser.add_argument(
        "--lock",
        type=Path,
        default=Path("third_party/LOCK.json"),
        help="upstream lock file",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("generated/manifests/upstream_inventory.json"),
        help="deterministic JSON output path",
    )
    args = parser.parse_args()

    try:
        manifest = create_inventory(args.source, args.lock)
    except (InventoryError, KeyError, OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    args.output.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    args.output.write_text(encoded, encoding="utf-8", newline="\n")
    print(
        f"Wrote {args.output}: {len(manifest['models'])} models, "
        f"{manifest['coverage']['neuralPassCount']} neural passes, "
        f"source {manifest['sourceCommit']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
