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
    "-DFSR4N10_CAPTURE_DELTA_BASIS=1",
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


def replace_exactly_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected one {label} in pinned FSR3 shader source, found {count}")
    return text.replace(old, new, 1)


def create_delta_basis_overlay(sdk_root: Path, output_root: Path) -> Path:
    source = sdk_root / "upscalers/fsr3/include/gpu/fsr3upscaler/ffx_fsr3upscaler_accumulate.h"
    text = source.read_text(encoding="utf-8-sig")
    old = """    const FfxFloat32 fAlpha = ffxSaturate(data.fUpsampledWeight / data.fHistoryWeight);
    data.fHistoryColor      = ffxLerp(data.fHistoryColor, data.fUpsampledColor, fAlpha);
"""
    new = """    const FfxFloat32 fAlpha = ffxSaturate(data.fUpsampledWeight / data.fHistoryWeight);

#if defined(FSR4N10_CAPTURE_DELTA_BASIS) && FSR4N10_CAPTURE_DELTA_BASIS && defined(FSR3UPSCALER_BIND_UAV_UPSCALED_OUTPUT)
    // Capture-only tap atlas. The ordinary provider uses a normal-width output UAV,
    // so this path is inactive there. A 5x-wide instrumented UAV stores four extra
    // regions without feeding any captured value back into reconstruction.
    FfxUInt32 captureWidth = 0;
    FfxUInt32 captureHeight = 0;
    rw_upscaled_output.GetDimensions(captureWidth, captureHeight);
    const FfxUInt32 baseWidth = FfxUInt32(UpscaleSize().x);
    const FfxUInt32 baseHeight = FfxUInt32(UpscaleSize().y);
    if (captureWidth >= baseWidth * 5u && captureHeight >= baseHeight) {
        const FfxFloat32x3 currentAccum = data.fUpsampledColor;
        const FfxFloat32x3 historyAccum = data.fHistoryColor;
        FfxFloat32x3 currentLinear = YCoCgToRGB(currentAccum);
        FfxFloat32x3 historyLinear = YCoCgToRGB(historyAccum);
#if FFX_FSR3UPSCALER_OPTION_HDR_COLOR_INPUT
        currentLinear = InverseTonemap(currentLinear);
        historyLinear = InverseTonemap(historyLinear);
#endif
        currentLinear = ffxMax(currentLinear / Exposure(), FfxFloat32x3(0.0f, 0.0f, 0.0f));
        historyLinear = ffxMax(historyLinear / Exposure(), FfxFloat32x3(0.0f, 0.0f, 0.0f));
        const FfxInt32 stride = UpscaleSize().x;
        rw_upscaled_output[params.iPxHrPos + FfxInt32x2(stride, 0)] = FfxFloat32x4(currentAccum, fAlpha);
        rw_upscaled_output[params.iPxHrPos + FfxInt32x2(stride * 2, 0)] = FfxFloat32x4(historyAccum, fAlpha);
        rw_upscaled_output[params.iPxHrPos + FfxInt32x2(stride * 3, 0)] = FfxFloat32x4(currentLinear, fAlpha);
        rw_upscaled_output[params.iPxHrPos + FfxInt32x2(stride * 4, 0)] = FfxFloat32x4(historyLinear, fAlpha);
    }
#endif

    data.fHistoryColor      = ffxLerp(data.fHistoryColor, data.fUpsampledColor, fAlpha);
"""
    text = replace_exactly_once(text, old, new, "Delta basis accumulation tap")
    overlay_root = output_root / "capture_overlay"
    destination = overlay_root / "fsr3upscaler" / source.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(text, encoding="utf-8")
    return overlay_root


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
    capture_overlay = create_delta_basis_overlay(sdk_root, output_root)
    include_dirs = (
        capture_overlay,
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
        "deltaBasisCapture": {
            "enabled": True,
            "activation": "output UAV width >= 5 * logical upscale width",
            "regions": [
                "final_output",
                "current_candidate_accum_ycocg_plus_alpha",
                "reprojected_history_accum_ycocg_plus_alpha",
                "current_candidate_linear_rgb_plus_alpha",
                "reprojected_history_linear_rgb_plus_alpha",
            ],
            "overlaySha256": sha256(capture_overlay / "fsr3upscaler/ffx_fsr3upscaler_accumulate.h"),
        },
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
