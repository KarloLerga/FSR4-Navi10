from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path


PROVIDER_RELATIVE = Path("Kits/FidelityFX/upscalers/fsr4/dx12/ffx_provider_fsr4_dx12.cpp")
FSR4_RELATIVE = Path("Kits/FidelityFX/upscalers/fsr4")
PRESETS = ("balanced", "drs", "native", "performance", "quality", "ultraperf")
TIERS = ("1080", "2160", "4320")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def parse_pass_enum(provider_text: str) -> list[dict[str, int | str]]:
    match = re.search(
        r"typedef\s+enum\s+FfxFsr4UpscalerPass\s*\{(?P<body>.*?)\}\s*FfxFsr4UpscalerPass\s*;",
        provider_text,
        re.S,
    )
    if not match:
        raise ValueError("could not locate FfxFsr4UpscalerPass enum in the pinned provider")
    result: list[dict[str, int | str]] = []
    next_value = 0
    for name, explicit in re.findall(r"\b(FFX_FSR4_[A-Z0-9_]+)\s*(?:=\s*(\d+))?\s*,", match["body"]):
        if explicit:
            next_value = int(explicit)
        result.append({"name": name, "value": next_value})
        next_value += 1
    if not result:
        raise ValueError("FSR4 provider pass enum contained no values")
    return result


def numbered_matches(text: str, pattern: str) -> list[dict[str, int | str]]:
    regex = re.compile(pattern)
    return [
        {"line": index, "source": line.strip()}
        for index, line in enumerate(text.splitlines(), start=1)
        if regex.search(line)
    ]


def create_audit(repo_root: Path, preset: str, tier: str) -> dict[str, object]:
    repo_root = repo_root.resolve()
    lock_path = repo_root / "third_party" / "LOCK.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8-sig"))
    source_commit = lock["fsr4Source"]["actualCommit"]
    provider_path = repo_root / "third_party" / "fidelityfx-fsr4-source" / PROVIDER_RELATIVE
    fsr4_root = repo_root / "third_party" / "fidelityfx-fsr4-source" / FSR4_RELATIVE
    provider_text = provider_path.read_text(encoding="utf-8-sig")
    passes = parse_pass_enum(provider_text)
    pass_values = {item["name"]: item["value"] for item in passes}

    expected_ids = {
        "FFX_FSR4_PRE_PASS": 0,
        "FFX_FSR4_MODEL_PASS": 1,
        "FFX_FSR4_POST_PASS": 13,
    }
    for name, value in expected_ids.items():
        if pass_values.get(name) != value:
            raise ValueError(f"provider pass contract changed: {name}={pass_values.get(name)!r}, expected {value}")

    model_directory = f"fsr4_model_v07_i8_{preset}"
    model_base = fsr4_root / "internal" / "shaders" / model_directory
    model_sources = {
        "pre": model_base / "pre.hlsl",
        "model_passes": model_base / f"passes_{tier}.hlsl",
        "post": model_base / "post.hlsl",
    }
    source_paths = {
        "provider": provider_path,
        "pre_common": fsr4_root / "include" / "gpu" / "fsr4" / "pre_common.hlsli",
        "post_common": fsr4_root / "include" / "gpu" / "fsr4" / "post_common.hlsli",
        "shader_selector_header": fsr4_root / "internal" / "shader_selector.h",
        "shader_selector_source": fsr4_root / "internal" / "shader_selector.cpp",
        **{f"model_{name}": path for name, path in model_sources.items()},
    }
    missing = [name for name, path in source_paths.items() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"missing pinned FSR4 source files: {', '.join(missing)}")

    provider_lines = provider_text.splitlines()
    enum_start = next(i for i, line in enumerate(provider_lines, 1) if "typedef enum FfxFsr4UpscalerPass" in line)
    enum_end = next(i for i in range(enum_start, len(provider_lines) + 1) if "} FfxFsr4UpscalerPass;" in provider_lines[i - 1])
    return {
        "format": "f4n10.provider-schedule-audit.v1",
        "source_commit": source_commit,
        "preset": preset,
        "tier": tier,
        "source_hashes_sha256": {
            name: sha256(path).upper()
            for name, path in sorted(source_paths.items())
        },
        "pass_enum": {
            "source_range_lines": [enum_start, enum_end],
            "entries": passes,
        },
        "shader_selection_evidence": numbered_matches(
            provider_text,
            r"passId\s*[><=]|GetModelShaderBlob|GetPaddingResetBlob|GetPreShaderBlob|GetPostShaderBlob",
        ),
        "dispatch_expression_evidence": numbered_matches(
            provider_text,
            r"dispatchSizes\[|paddingDispatchSizes\[|scheduleDispatch\(internal_context,\s*&internal_context->model_pso|scheduleDispatch\(internal_context,\s*&internal_context->padding_pso",
        ),
        "interpretation": {
            "pre_pass_id": pass_values["FFX_FSR4_PRE_PASS"],
            "model_pass_ids": [pass_values["FFX_FSR4_MODEL_PASS"], pass_values["FFX_FSR4_POST_PASS"] - 1],
            "post_pass_id": pass_values["FFX_FSR4_POST_PASS"],
            "padding_pass_ids": {
                "pre": pass_values["FFX_FSR4_PRE_PASS_PADDING"],
                "post": pass_values["FFX_FSR4_POST_PASS_PADDING"],
            },
            "dispatch_values_are_not_evaluated": True,
            "dispatch_expressions_are_verbatim_provider_evidence": True,
        },
        "limitations": [
            "This audit records source expressions and hashes; it does not create or execute a GPU teacher frame graph.",
            "The selected model HLSL sources are hashed, but compiled DXIL hashes require a separate deterministic shader build.",
            "Runtime branch selection depends on provider context and device capabilities and must be supplied by the actual provider path.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract a source-hashed audit of the pinned FSR4 D3D12 provider schedule.")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--preset", choices=PRESETS, default="native")
    parser.add_argument("--tier", choices=TIERS, default="1080")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        audit = create_audit(args.repo_root, args.preset, args.tier)
        output = args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(audit, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    except (OSError, KeyError, json.JSONDecodeError, ValueError) as error:
        print(f"audit_provider_schedule: {error}", file=sys.stderr)
        return 2
    print(f"Wrote provider schedule audit for commit {audit['source_commit']} to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
