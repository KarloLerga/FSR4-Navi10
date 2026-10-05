#!/usr/bin/env python3
"""Compile every pinned FSR3.1.5 shader permutation used by the reference provider."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path


BASE_FLAGS = (
    "-Zs",
    "-reflection",
    "-deps=gcc",
    "-DFFX_GPU=1",
    "-DFFX_IMPLICIT_SHADER_REGISTER_BINDING_HLSL=0",
    "-DFFX_FSR3UPSCALER_OPTION_UPSAMPLE_SAMPLERS_USE_DATA_HALF=0",
    "-DFFX_FSR3UPSCALER_OPTION_ACCUMULATE_SAMPLERS_USE_DATA_HALF=0",
    "-DFFX_FSR3UPSCALER_OPTION_REPROJECT_SAMPLERS_USE_DATA_HALF=1",
    "-DFFX_FSR3UPSCALER_OPTION_POSTPROCESSLOCKSTATUS_SAMPLERS_USE_DATA_HALF=0",
    "-DFFX_FSR3UPSCALER_OPTION_UPSAMPLE_USE_LANCZOS_TYPE=2",
    "-DFFX_FSR3UPSCALER_OPTION_REPROJECT_USE_LANCZOS_TYPE={0,1}",
    "-DFFX_FSR3UPSCALER_OPTION_HDR_COLOR_INPUT={0,1}",
    "-DFFX_FSR3UPSCALER_OPTION_LOW_RESOLUTION_MOTION_VECTORS={0,1}",
    "-DFFX_FSR3UPSCALER_OPTION_JITTERED_MOTION_VECTORS={0,1}",
    "-DFFX_FSR3UPSCALER_OPTION_INVERTED_DEPTH={0,1}",
    "-DFFX_FSR3UPSCALER_OPTION_APPLY_SHARPENING={0,1}",
    "-embed-arguments",
    "-E",
    "CS",
    "-Wno-for-redefinition",
    "-Wno-ambig-lit-shift",
    "-DFFX_HLSL=1",
    "-DFFX_FSR3UPSCALER_EMBED_ROOTSIG=0",
)

VARIANTS = (
    ("wave32_fp32", "", ("-DFFX_HALF=0", "-DFFX_HLSL_SM=62", "-T", "cs_6_2")),
    ("wave64_fp32", "_wave64", ("-DFFX_HALF=0", "-DFFX_PREFER_WAVE64=[WaveSize(64)]", "-DFFX_HLSL_SM=66", "-T", "cs_6_6")),
    ("wave32_fp16", "_16bit", ("-DFFX_HALF=1", "-enable-16bit-types", "-DFFX_HLSL_SM=62", "-T", "cs_6_2")),
    ("wave64_fp16", "_wave64_16bit", ("-DFFX_HALF=1", "-enable-16bit-types", "-DFFX_PREFER_WAVE64=[WaveSize(64)]", "-DFFX_HLSL_SM=66", "-T", "cs_6_6")),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def shader_sources(sdk_root: Path) -> list[Path]:
    blob_source = sdk_root / "upscalers/fsr3/internal/ffx_fsr3upscaler_shaderblobs.cpp"
    if not blob_source.is_file():
        raise FileNotFoundError(f"pinned FSR3 shader selector is missing: {blob_source}")
    text = blob_source.read_text(encoding="utf-8-sig")
    names = set(re.findall(r"#include\s*<((?:ffx_fsr3upscaler_[A-Za-z0-9_]+)_permutations\.h)>", text))
    shader_names = set()
    for header in names:
        name = header.removesuffix("_permutations.h")
        for suffix in ("_wave64_16bit", "_wave64", "_16bit"):
            if name.endswith(suffix):
                name = name[: -len(suffix)]
                break
        shader_names.add(name)
    shaders = [sdk_root / "upscalers/fsr3/internal/shaders" / f"{name}.hlsl" for name in sorted(shader_names)]
    missing = [str(path) for path in shaders if not path.is_file()]
    if missing:
        raise FileNotFoundError("missing pinned FSR3 shader sources: " + ", ".join(missing))
    if len(shaders) != 10:
        raise RuntimeError(f"expected 10 FSR3 shader sources, found {len(shaders)}")
    return shaders


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk-root", type=Path, required=True)
    parser.add_argument("--compiler", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    sdk_root = args.sdk_root.resolve()
    compiler = args.compiler.resolve()
    if not compiler.is_file():
        parser.error(f"FidelityFX_SC is missing: {compiler}")
    output_root = args.output.resolve()
    output_dir = output_root / "ffx_sc_output"
    output_dir.mkdir(parents=True, exist_ok=True)
    include_dirs = (
        sdk_root / "api/internal/gpu",
        sdk_root / "upscalers/fsr3/include/gpu",
    )
    if not all(path.is_dir() for path in include_dirs):
        parser.error("the pinned SDK is missing an FSR3 shader include directory")

    sources = shader_sources(sdk_root)
    for source in sources:
        shader_name = source.stem
        for variant_name, suffix, variant_flags in VARIANTS:
            command = [
                str(compiler),
                *BASE_FLAGS,
                f"-name={shader_name}{suffix}",
                *variant_flags,
                *(f"-I{path}" for path in include_dirs),
                f"-output={output_dir}",
                str(source),
            ]
            subprocess.run(command, cwd=compiler.parent, check=True)

    blobs = []
    for path in sorted(output_dir.glob("*.h")):
        if path.name.endswith("_permutations.h") or re.fullmatch(r".+_[0-9a-f]{32}\.h", path.name):
            blobs.append({"file": path.relative_to(output_root).as_posix(), "bytes": path.stat().st_size,
                          "sha256": sha256(path)})
    expected_headers = len(sources) * len(VARIANTS)
    permutation_headers = list(output_dir.glob("*_permutations.h"))
    if len(permutation_headers) != expected_headers:
        raise RuntimeError(f"expected {expected_headers} permutation headers, found {len(permutation_headers)}")

    manifest = {
        "schema": "f4n10.fsr3-shader-manifest.v1",
        "provider": "fidelityfx_fsr3_upscaler",
        "providerVersion": "3.1.5",
        "sdkCommit": args.source_commit,
        "compiler": {
            "identity": "FidelityFX_SC.exe",
            "sha256": sha256(compiler),
            "versionString": "not exposed by this compiler; identified by SHA-256",
        },
        "shaderSourceCount": len(sources),
        "permutationHeaderCount": len(permutation_headers),
        "variants": [name for name, _, _ in VARIANTS],
        "flags": list(BASE_FLAGS),
        "shaderSources": [
            {"file": path.relative_to(sdk_root).as_posix(), "sha256": sha256(path)} for path in sources
        ],
        "generatedHeaders": blobs,
    }
    manifest_path = output_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Compiled {len(sources) * len(VARIANTS)} FSR3 shader permutations: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
