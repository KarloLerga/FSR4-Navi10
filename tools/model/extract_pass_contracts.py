#!/usr/bin/env python3
"""Extract verbatim pass, operator-call, threadgroup and tensor contracts from upstream I8 HLSL."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


PRESETS = ("native", "quality", "balanced", "performance", "drs", "ultraperf")
TIERS = ("1080", "2160", "4320")
ENTRYPOINT = re.compile(
    r"^\s*void\s+(?P<name>fsr4_model_v07_i8_pass(?P<index>\d+)(?P<padding>_post)?)\s*\(",
    re.MULTILINE,
)
TENSOR_DECLARATION = re.compile(
    r"(?P<type>(?:Quantized)?Tensor[1-4][A-Za-z0-9_]*)\s*<\s*"
    r"(?P<storage>(?:[^<>]|<[^<>]*>)*)>\s*(?P<name>\w+)\s*=\s*"
    r"\{(?P<body>.*?)\}\s*;",
    re.DOTALL,
)


class ContractError(RuntimeError):
    """Raised when generated pass HLSL no longer matches expected syntax."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def _source_commit(source_root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(source_root), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.PIPE,
        ).strip()
    except (OSError, subprocess.CalledProcessError) as error:
        raise ContractError(f"cannot read upstream Git commit: {error}") from error


def _split_expressions(text: str) -> list[str]:
    text = re.sub(r"//[^\r\n]*", "", text)
    expressions: list[str] = []
    start = 0
    paren = bracket = brace = angle = 0
    for index, character in enumerate(text):
        if character == "(":
            paren += 1
        elif character == ")":
            paren -= 1
        elif character == "[":
            bracket += 1
        elif character == "]":
            bracket -= 1
        elif character == "{":
            brace += 1
        elif character == "}":
            brace -= 1
        elif character == "<":
            angle += 1
        elif character == ">" and angle:
            angle -= 1
        elif character == "," and not (paren or bracket or brace or angle):
            value = text[start:index].strip()
            if value:
                expressions.append(value)
            start = index + 1
    value = text[start:].strip()
    if value:
        expressions.append(value)
    return expressions


def _extract_function_body(source: str, match: re.Match[str]) -> tuple[str, int]:
    open_brace = source.find("{", match.end())
    if open_brace < 0:
        raise ContractError(f"{match.group('name')}: function body is missing")
    depth = 0
    for index in range(open_brace, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[open_brace + 1 : index], open_brace
    raise ContractError(f"{match.group('name')}: function body is unterminated")


def _matching_open_paren(text: str, closing: int) -> int:
    depth = 0
    for index in range(closing, -1, -1):
        if text[index] == ")":
            depth += 1
        elif text[index] == "(":
            depth -= 1
            if depth == 0:
                return index
    raise ContractError("cannot find opening parenthesis for operator call")


def _operator_calls(body: str) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for candidate in re.finditer(r"\b(?P<name>[A-Z]\w*(?:\s*<[^;\n]+?>)?)\s*\(", body):
        opening = body.find("(", candidate.start(), candidate.end())
        depth = 1
        closing = opening + 1
        while closing < len(body) and depth:
            if body[closing] == "(":
                depth += 1
            elif body[closing] == ")":
                depth -= 1
            closing += 1
        if depth:
            raise ContractError(f"{candidate.group('name')}: function call is unterminated")
        closing -= 1
        if body[closing + 1 :].lstrip().startswith(";"):
            arguments = _split_expressions(body[opening + 1 : closing])
            calls.append(
                {
                    "operator": re.sub(r"\s+", "", candidate.group("name")),
                    "argumentExpressions": arguments,
                }
            )
    return calls


def _tensor_descriptors(body: str, source_start: int) -> list[dict[str, Any]]:
    tensors: list[dict[str, Any]] = []
    for match in TENSOR_DECLARATION.finditer(body):
        field_labels = re.findall(r"//\s*([A-Za-z_]\w*)", match.group("body"))
        field_expressions = _split_expressions(match.group("body"))
        tensors.append(
            {
                "name": match.group("name"),
                "type": match.group("type"),
                "storageType": re.sub(r"\s+", "", match.group("storage")),
                "fieldLabels": field_labels,
                "fieldExpressions": field_expressions,
                "sourceLine": body.count("\n", 0, match.start()) + source_start,
            }
        )
    return tensors


def parse_pass_contracts(source: str) -> list[dict[str, Any]]:
    contracts: list[dict[str, Any]] = []
    for match in ENTRYPOINT.finditer(source):
        name = match.group("name")
        index = int(match.group("index"))
        padding = match.group("padding") is not None
        role = "padding_reset" if padding else "model_pre" if index == 0 else "model_post" if index == 13 else "neural_pass"

        prefix = source[: match.start()]
        threadgroup = re.search(r"\[\s*numthreads\s*\(([^)]*)\)\s*\]\s*$", prefix.rstrip())
        if not threadgroup:
            raise ContractError(f"{name}: numthreads declaration is missing")
        try:
            threadgroup_size = [int(value.strip()) for value in threadgroup.group(1).split(",")]
        except ValueError as error:
            raise ContractError(f"{name}: numthreads must contain integer dimensions") from error
        if len(threadgroup_size) != 3 or any(value <= 0 for value in threadgroup_size):
            raise ContractError(f"{name}: numthreads must have three positive dimensions")

        body, body_start = _extract_function_body(source, match)
        section_macro = f"MLSR_PASS_{index}_POST" if padding else f"MLSR_PASS_{index}"
        section_start = re.search(rf"^\s*#ifdef\s+{section_macro}\s*$", source[: match.start()], re.MULTILINE)
        if not section_start:
            raise ContractError(f"{name}: matching {section_macro} section is missing")
        includes = re.findall(r"^\s*#include\s+\"([^\"]+)\"", source[section_start.end() : match.start()], re.MULTILINE)

        contracts.append(
            {
                "index": index,
                "entryPoint": name,
                "role": role,
                "paddingReset": padding,
                "sourceLine": source.count("\n", 0, match.start()) + 1,
                "sectionMacro": section_macro,
                "numThreads": threadgroup_size,
                "operatorIncludes": includes,
                "operatorCalls": _operator_calls(body),
                "tensorDescriptors": _tensor_descriptors(
                    body,
                    source.count("\n", 0, body_start) + 2,
                ),
            }
        )
    if len(contracts) != 27:
        raise ContractError(f"expected 27 main/padding entrypoints, found {len(contracts)}")
    if sum(contract["role"] == "neural_pass" for contract in contracts) != 12:
        raise ContractError("expected 12 neural pass entrypoints")
    for contract in contracts:
        if not contract["operatorCalls"]:
            raise ContractError(f"{contract['entryPoint']}: no operator call was found")
    return contracts


def build_catalog(source_root: Path, fsr4_root: Path, lock_path: Path) -> dict[str, Any]:
    source_root = source_root.resolve()
    fsr4_root = fsr4_root.resolve()
    expected_fsr4_root = source_root / "Kits/FidelityFX/upscalers/fsr4"
    if fsr4_root != expected_fsr4_root:
        raise ContractError(f"FSR4 root must be {expected_fsr4_root}")
    lock = json.loads(lock_path.read_text(encoding="utf-8-sig"))
    commit = _source_commit(source_root)
    expected_commit = lock["fsr4Source"]["actualCommit"]
    if commit != expected_commit:
        raise ContractError(f"source commit {commit} does not match lock file {expected_commit}")

    combinations = []
    for preset in PRESETS:
        model_dir = fsr4_root / "internal/shaders" / f"fsr4_model_v07_i8_{preset}"
        for tier in TIERS:
            shader_path = model_dir / f"passes_{tier}.hlsl"
            if not shader_path.is_file():
                raise ContractError(f"missing pass source: {shader_path}")
            data = shader_path.read_bytes()
            try:
                source = data.decode("utf-8-sig")
            except UnicodeDecodeError as error:
                raise ContractError(f"{shader_path}: source is not valid UTF-8") from error
            contracts = parse_pass_contracts(source)
            if sum(contract["role"] == "neural_pass" and len(contract["operatorCalls"]) == 1 for contract in contracts) != 12:
                raise ContractError(f"{shader_path}: expected one source operator call for each neural pass")
            combinations.append(
                {
                    "modelId": f"fsr4_model_v07_i8_{preset}",
                    "preset": preset,
                    "resolutionTier": tier,
                    "shader": shader_path.relative_to(source_root).as_posix(),
                    "shaderBytes": len(data),
                    "shaderSha256": _sha256(data),
                    "entryPointCount": len(contracts),
                    "passContracts": contracts,
                }
            )

    return {
        "schemaVersion": 1,
        "catalogKind": "upstream_i8_pass_contracts",
        "sourceCommit": commit,
        "provenance": "Includes, function calls, tensor fields, and threadgroup sizes are parsed from pinned generated HLSL. Operator argument expressions are recorded verbatim; input/output direction and host dispatch dimensions are not inferred.",
        "combinations": combinations,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--fsr4-root", type=Path, required=True)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        catalog = build_catalog(args.source_root, args.fsr4_root, args.lock)
    except (ContractError, KeyError, OSError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(catalog, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"Wrote {args.output}: {len(catalog['combinations'])} preset/tier contracts "
        f"from {catalog['sourceCommit']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
