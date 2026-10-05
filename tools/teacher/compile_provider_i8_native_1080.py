#!/usr/bin/env python3
"""Build the pinned FSR4 native/1080 I8 provider shader blobs with FidelityFX_SC."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


MODEL = "fsr4_model_v07_i8_native"
TIER = "1080"
BASE_FLAGS = (
    "-deps=gcc",
    "-enable-16bit-types",
    "-HV",
    "2021",
    "-O3",
    "-no-warnings",
    "-reflection",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def replace_exactly_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected one {label} in pinned shader source, found {count}")
    return text.replace(old, new, 1)


def create_capture_shader_overlays(fsr4_root: Path, output_dir: Path) -> tuple[Path, dict[str, Path]]:
    """Build derived capture-only include overrides without editing the pinned source tree."""
    source_dir = fsr4_root / "include" / "gpu" / "fsr4"
    overlay_dir = output_dir / "capture_shader_overrides"
    overlay_dir.mkdir(parents=True, exist_ok=True)

    resources_source = source_dir / "ffx_fsr4_upscale_resources.h"
    resources_text = resources_source.read_text(encoding="utf-8-sig")
    resources_text = replace_exactly_once(
        resources_text,
        "Texture2D<float>                      r_debug_visualization",
        "Texture2D<float4>                     r_debug_visualization",
        "debug visualization SRV declaration",
    )
    resources_text = replace_exactly_once(
        resources_text,
        "RWTexture2D<float>                    rw_debug_visualization",
        "RWTexture2D<float4>                   rw_debug_visualization",
        "debug visualization UAV declaration",
    )

    optimized_source = source_dir / "mlsr_optimized_includes.hlsli"
    optimized_text = optimized_source.read_text(encoding="utf-8-sig")
    old_debug_helpers = """void DebugWritePredictedBlendFactor(int2 iPxPos, float blendFactor)
{
#if FFX_DEBUG_VISUALIZE
    rw_debug_visualization[iPxPos] = blendFactor;
#endif
}

float DebugSamplePredictedBlendFactor(float2 fUv)
{
#if FFX_DEBUG_VISUALIZE
    return r_debug_visualization.SampleLevel(g_history_sampler, fUv, 0);
#else
    return 0.0f;
#endif
}"""
    new_debug_helpers = """void DebugWritePredictedBlendFactor(int2 iPxPos, float4 modelParameters)
{
#if FFX_DEBUG_VISUALIZE
    rw_debug_visualization[iPxPos] = modelParameters;
#endif
}

float DebugSamplePredictedBlendFactor(float2 fUv)
{
#if FFX_DEBUG_VISUALIZE
    const float2 controlsUv = float2((fUv.x + 4.0f) / 5.0f, fUv.y);
    return r_debug_visualization.SampleLevel(g_history_sampler, controlsUv, 0).w;
#else
    return 0.0f;
#endif
}"""
    optimized_text = replace_exactly_once(
        optimized_text, old_debug_helpers, new_debug_helpers, "debug capture helper block"
    )

    pre_source = source_dir / "pre_common.hlsli"
    pre_text = pre_source.read_text(encoding="utf-8-sig")
    pre_anchor = """        downscaleInputs[1].w = 0;
    }

    // Downscale"""
    pre_capture = """        downscaleInputs[1].w = 0;
    }

#if FFX_DEBUG_VISUALIZE
    // Capture-only taps. The debug UAV is five output-width regions wide:
    // the current input sampled by POST, semantic channels 0..3,
    // semantic channels 4..6, raw model parameters, then physical controls.
    rw_debug_visualization[dtid.xy] = float4(LoadInputColor(int2(dtid.xy)), 1.0f);
    rw_debug_visualization[uint2(dtid.x + width, dtid.y)] = float4(downscaleInputs[0]);
    rw_debug_visualization[uint2(dtid.x + width * 2, dtid.y)] = float4(downscaleInputs[1]);
#endif

    // Downscale"""
    pre_text = replace_exactly_once(pre_text, pre_anchor, pre_capture, "PRE semantic-channel tap location")

    post_source = source_dir / "post_common.hlsli"
    post_text = post_source.read_text(encoding="utf-8-sig")
    post_anchor = """    const float blending_factor = (1.0 / (1.0 + exp(-filter[3])));

    float3 res"""
    post_capture = """    const float blending_factor = (1.0 / (1.0 + exp(-filter[3])));

#if FFX_DEBUG_VISUALIZE
    // Record mathematically equivalent transforms with stable exponent ranges.
    // These capture-only values do not feed the provider's reconstruction.
    const float exp_rho = exp(-2.0f * abs(filter[0]));
    const float captured_rho = (filter[0] >= 0.0f ? 1.0f : -1.0f) *
        ((1.0f - exp_rho) / (1.0f + exp_rho));
    const float exp_sx = exp(-abs(filter[1]));
    const float captured_sx = 2.0f * (filter[1] >= 0.0f ?
        (1.0f / (1.0f + exp_sx)) : (exp_sx / (1.0f + exp_sx)));
    const float exp_sy = exp(-abs(filter[2]));
    const float captured_sy = 2.0f * (filter[2] >= 0.0f ?
        (1.0f / (1.0f + exp_sy)) : (exp_sy / (1.0f + exp_sy)));
    const float exp_blend = exp(-abs(filter[3]));
    const float captured_blend = filter[3] >= 0.0f ?
        (1.0f / (1.0f + exp_blend)) : (exp_blend / (1.0f + exp_blend));
    rw_debug_visualization[uint2(x + width * 4, y)] =
        float4(captured_rho, captured_sx, captured_sy, captured_blend);
#endif

    float3 res"""
    post_text = replace_exactly_once(post_text, post_anchor, post_capture, "physical-control tap location")
    old_parameter_capture = """        {
            float blending_factor = (1.0f / (1.0f + exp(-model_parameters.w)));
            blending_factor = 1.0f - blending_factor;
            DebugWritePredictedBlendFactor(tid, blending_factor);
        }"""
    new_parameter_capture = """        {
            DebugWritePredictedBlendFactor(int2(tid.x + width * 3, tid.y), model_parameters);
        }"""
    post_text = replace_exactly_once(
        post_text, old_parameter_capture, new_parameter_capture, "raw model-parameter tap location"
    )

    overlays = {
        "resources": overlay_dir / resources_source.name,
        "optimized_includes": overlay_dir / optimized_source.name,
        "pre_common": overlay_dir / pre_source.name,
        "post_common": overlay_dir / post_source.name,
    }
    for name, content in (
        ("resources", resources_text),
        ("optimized_includes", optimized_text),
        ("pre_common", pre_text),
        ("post_common", post_text),
    ):
        overlays[name].write_text(content, encoding="utf-8")
    return overlay_dir, overlays


def run_shader_compiler(
    compiler: Path,
    output_dir: Path,
    source: Path,
    shader_name: str,
    entry: str,
    definitions: tuple[str, ...],
    include_dirs: tuple[Path, ...],
    target: str,
) -> None:
    args = [
        str(compiler),
        f"-name={shader_name}",
        f"-output={output_dir}",
        "-E",
        entry,
        *BASE_FLAGS,
        "-T",
        target,
        *definitions,
    ]
    args.extend(f"-I{include_dir}" for include_dir in include_dirs)
    args.append(str(source))
    subprocess.run(args, cwd=compiler.parent, check=True)


def promote_shader_output(temporary_dir: Path, output_dir: Path, temporary_name: str, final_name: str) -> list[Path]:
    """Rename FFX_SC identifiers and files from compact names to upstream selector names."""
    outputs: list[Path] = []
    for source in sorted(temporary_dir.iterdir()):
        if not source.is_file():
            continue
        destination_name = source.name.replace(temporary_name, final_name)
        destination = output_dir / destination_name
        if source.suffix.lower() in {".h", ".d"}:
            content = source.read_text(encoding="utf-8")
            destination.write_text(content.replace(temporary_name, final_name), encoding="utf-8")
        else:
            shutil.copyfile(source, destination)
        outputs.append(destination)
    permutation_header = output_dir / f"{final_name}_permutations.h"
    if not permutation_header.is_file():
        raise RuntimeError(f"FidelityFX_SC did not emit the expected header: {permutation_header.name}")
    return outputs


def generate_initializer_sources(model_dir: Path, output_dir: Path) -> list[Path]:
    input_path = model_dir / "initializers.bin"
    data = input_path.read_bytes()
    words = ",".join(f"0x{byte:02x}" for byte in data)
    cpp_path = output_dir / f"{MODEL}.cpp"
    header_path = output_dir / f"{MODEL}.h"
    cpp_path.write_text(
        f"// Generated from the pinned upstream initializers.bin.\n"
        f"extern const unsigned char g_{MODEL}_initializers_data[] = {{{words}}};\n",
        encoding="utf-8",
    )
    header_path.write_text(
        "// Generated from the pinned upstream initializers.bin.\n"
        "#pragma once\n"
        "#include <cstddef>\n"
        f"extern const unsigned char g_{MODEL}_initializers_data[];\n"
        f"static const size_t g_{MODEL}_initializers_size = {len(data)};\n",
        encoding="utf-8",
    )
    return [header_path, cpp_path]


def compile_provider_set(repo_root: Path, output_dir: Path) -> dict[str, object]:
    sdk_root = repo_root / "third_party" / "fidelityfx-fsr4-source" / "Kits" / "FidelityFX"
    fsr4_root = sdk_root / "upscalers" / "fsr4"
    model_dir = fsr4_root / "internal" / "shaders" / MODEL
    compiler = sdk_root / "tools" / "ffx_sc" / "bin" / "FidelityFX_SC.exe"
    if not compiler.is_file():
        raise FileNotFoundError(f"pinned FidelityFX_SC.exe is missing: {compiler}")

    source_files = {
        "pre": model_dir / "pre.hlsl",
        "model": model_dir / f"passes_{TIER}.hlsl",
        "post": model_dir / "post.hlsl",
        "initializers": model_dir / "initializers.bin",
        "rcas": fsr4_root / "internal" / "shaders" / "rcas.hlsl",
        "spd_auto_exposure": fsr4_root / "internal" / "shaders" / "spd_auto_exposure.hlsl",
        "debug_view": fsr4_root / "internal" / "shaders" / "debug_view.hlsl",
        "watermark": sdk_root / "api" / "internal" / "gpu" / "ffx_watermark.hlsl",
    }
    for path in source_files.values():
        if not path.is_file():
            raise FileNotFoundError(f"pinned FSR4 provider source is missing: {path}")

    output_dir.mkdir(parents=True, exist_ok=True)
    capture_overlay_dir, capture_overlays = create_capture_shader_overlays(fsr4_root, output_dir)
    include_dirs = (
        sdk_root / "api" / "internal" / "gpu",
        sdk_root / "api" / "internal" / "dx12",
        fsr4_root / "include" / "gpu",
        fsr4_root / "include" / "gpu" / "fsr4",
        fsr4_root / "dx12",
    )
    if any(not path.is_dir() for path in include_dirs):
        raise FileNotFoundError("one or more pinned FidelityFX shader include directories are missing")

    compiled: list[Path] = []

    def compile_one(
        final_name: str,
        source: Path,
        entry: str,
        definitions: tuple[str, ...],
        short_name: str,
        shader_includes: tuple[Path, ...] = include_dirs,
        target: str = "cs_6_6",
    ) -> None:
        with tempfile.TemporaryDirectory(prefix=f".ffxsc-{short_name}-", dir=output_dir) as temporary_path:
            temporary_dir = Path(temporary_path)
            run_shader_compiler(
                compiler, temporary_dir, source, short_name, entry, definitions, shader_includes, target
            )
            compiled.extend(promote_shader_output(temporary_dir, output_dir, short_name, final_name))

    pre_definitions = (
        "-DFFX_MLSR_DEPTH_INVERTED={0,1}",
        "-DFFX_MLSR_LOW_RES_MV={0,1}",
        "-DFFX_MLSR_AUTOEXPOSURE_ENABLED={0,1}",
        "-DFFX_MLSR_COLORSPACE={0,1,2,3}",
        "-DFFX_MLSR_JITTERED_MOTION_VECTORS={0,1}",
        "-DFFX_MLSR_RESOLUTION={0,1,2}",
        "-DFFX_DEBUG_VISUALIZE={0,1}",
    )
    capture_shader_includes = (capture_overlay_dir, *include_dirs)
    compile_one(
        f"{MODEL}_0", source_files["pre"], "main", pre_definitions, "n10pre", capture_shader_includes
    )

    for pass_index in range(1, 13):
        compile_one(
            f"{MODEL}_{TIER}_{pass_index}",
            source_files["model"],
            f"fsr4_model_v07_i8_pass{pass_index}",
            (f"-DMLSR_PASS_{pass_index}=1",),
            f"n10p{pass_index}",
            (fsr4_root / "dx12", sdk_root / "api" / "internal" / "dx12"),
        )

    for pass_index in range(13):
        compile_one(
            f"{MODEL}_{TIER}_{pass_index}_post",
            source_files["model"],
            f"fsr4_model_v07_i8_pass{pass_index}_post",
            (f"-DMLSR_PASS_{pass_index}_POST=1",),
            f"n10z{pass_index}",
            (fsr4_root / "dx12", sdk_root / "api" / "internal" / "dx12"),
        )

    post_definitions = (
        "-DNUM_MODEL_CHANNELS=7",
        "-DRFM_CHANNELS=4",
        "-DFILTER_CHANNELS=4",
        "-DRFM_ACTIVATION=RfmActivation_Sigmoid",
        "-DFFX_MLSR_COLORSPACE={0,1,2,3}",
        "-DAUTOEXPOSURE_ENABLED={0,1}",
        "-DRESOLUTION={0,1,2}",
        "-DFFX_DEBUG_VISUALIZE={0,1}",
    )
    compile_one(
        f"{MODEL}_13", source_files["post"], "main", post_definitions, "n10post", capture_shader_includes
    )

    compile_one(
        "rcas",
        source_files["rcas"],
        "main",
        ("-DFFX_MLSR_COLORSPACE={0,1,2,3}", "-DFFX_MLSR_AUTOEXPOSURE_ENABLED={0,1}"),
        "n10rcas",
        (sdk_root / "api" / "internal" / "gpu", fsr4_root / "include" / "gpu"),
    )
    compile_one(
        "spd_auto_exposure",
        source_files["spd_auto_exposure"],
        "main",
        ("-DFFX_GPU=1", "-DFFX_HLSL=1"),
        "n10spd",
        (sdk_root / "api" / "internal" / "gpu", fsr4_root / "include" / "gpu"),
    )
    compile_one(
        "debug_view",
        source_files["debug_view"],
        "main",
        ("-DFFX_GPU=1", "-DFFX_HLSL=1", "-DFFX_DEBUG_VISUALIZE=1", "-DFFX_MLSR_JITTERED_MOTION_VECTORS={0,1}"),
        "n10debug",
        (capture_overlay_dir, fsr4_root / "dx12", fsr4_root / "include" / "gpu" / "fsr4"),
    )
    compile_one(
        "ffx_watermark",
        source_files["watermark"],
        "main",
        ("-DFFX_GPU=1", "-DFFX_HLSL=1", "-T", "cs_6_4"),
        "n10watermark",
        (sdk_root / "api" / "internal" / "gpu",),
        "cs_6_4",
    )
    compiled.extend(generate_initializer_sources(model_dir, output_dir))

    expected_headers = [
        output_dir / f"{MODEL}_0_permutations.h",
        output_dir / f"{MODEL}_13_permutations.h",
        output_dir / "rcas_permutations.h",
        output_dir / "spd_auto_exposure_permutations.h",
        output_dir / "debug_view_permutations.h",
        output_dir / "ffx_watermark_permutations.h",
        *[output_dir / f"{MODEL}_{TIER}_{index}_permutations.h" for index in range(1, 13)],
        *[output_dir / f"{MODEL}_{TIER}_{index}_post_permutations.h" for index in range(13)],
    ]
    missing_headers = [path.name for path in expected_headers if not path.is_file()]
    if missing_headers:
        raise RuntimeError(f"provider shader build is incomplete; missing: {', '.join(missing_headers)}")

    lock = json.loads((repo_root / "third_party" / "LOCK.json").read_text(encoding="utf-8-sig"))
    shader_outputs = sorted(
        (path for path in output_dir.iterdir() if path.is_file() and path.suffix.lower() == ".h"),
        key=lambda item: item.name,
    )
    manifest = {
        "format": "f4n10.provider-i8-native-1080-shader-build.v1",
        "source_commit": lock["fsr4Source"]["actualCommit"],
        "preset": "native",
        "tier": TIER,
        "target": "cs_6_6",
        "watermark_target": "cs_6_4",
        "compiler": "FidelityFX_SC.exe from pinned FidelityFX source tree",
        "flags": list(BASE_FLAGS),
        "shader_counts": {
            "pre_permutations": 384,
            "model": 12,
            "padding": 13,
            "post_permutations": 48,
            "rcas_permutations": 8,
            "spd_auto_exposure": 1,
            "debug_view_permutations": 2,
            "watermark_permutations": 1,
        },
        "source_hashes_sha256": {
            **{name: sha256(path) for name, path in source_files.items()},
            "pre_common": sha256(fsr4_root / "include" / "gpu" / "fsr4" / "pre_common.hlsli"),
            "post_common": sha256(fsr4_root / "include" / "gpu" / "fsr4" / "post_common.hlsli"),
            "mlsr_optimized_includes": sha256(fsr4_root / "include" / "gpu" / "fsr4" / "mlsr_optimized_includes.hlsli"),
            "shader_resources": sha256(fsr4_root / "include" / "gpu" / "fsr4" / "ffx_fsr4_upscale_resources.h"),
        },
        "capture_overlay_hashes_sha256": {name: sha256(path) for name, path in capture_overlays.items()},
        "capture_taps_enabled_in_debug_variant": True,
        "outputs": [
            {"file": path.name, "size_bytes": path.stat().st_size, "sha256": sha256(path)}
            for path in shader_outputs
        ],
        "limitations": [
            "This builds and embeds shader blobs; it does not create or execute the FSR4 D3D12 provider frame graph.",
            "FidelityFX_SC output metadata and shader hashes do not constitute teacher captures.",
        ],
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        manifest = compile_provider_set(args.repo_root.resolve(), args.output.resolve())
    except (OSError, KeyError, json.JSONDecodeError, subprocess.CalledProcessError, RuntimeError) as error:
        print(f"compile_provider_i8_native_1080: {error}", file=sys.stderr)
        return 2
    print(
        "Built native/1080 FSR4 I8 PRE/model/padding/POST shader set "
        f"from upstream commit {manifest['source_commit']} ({len(manifest['outputs'])} reflected headers)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
