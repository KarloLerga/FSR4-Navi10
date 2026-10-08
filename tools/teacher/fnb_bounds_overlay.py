#!/usr/bin/env python3
"""Build-local shader override for the pinned FSR 4.0.2 I8 FNB_CT2D_ADD<32,1>.

No vendor source edits, no shader weight changes, and strict source-structure checks.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

OPERATOR_REL = Path('ml2code_runtime/operators/int8_NHWC/Fused/FNB_CT2D_ADD.hlsli')
SENTINEL = 'FSR4N10_BOUNDS_GUARD_PASS11_V1'
START = '_Static_assert(numFeatures == 32, "NumFeatures must be 32");'
END = '#if WMMA_ENABLED'
BEFORE_INPUT = '''    _Static_assert(numGroups == 1, "NumGroups must be 1");

    const int3 workOffset = int3(computeShaderParams.dispatchThreadID.xy, 0);'''
AFTER_INPUT = '''    _Static_assert(numGroups == 1, "NumGroups must be 1");

    // FSR4N10_BOUNDS_GUARD_PASS11_V1: the provider rounds 480 to 8 x 64
    // threads. Lanes x=480..511 would otherwise read beyond the input
    // tensor and write into the beginning of the next output row.
    if (any(computeShaderParams.dispatchThreadID.xy >= input.logicalSize.xy))
        return;

    const int3 workOffset = int3(computeShaderParams.dispatchThreadID.xy, 0);'''
BEFORE_OUTPUT = '''        const uint2 poBase2D = computeShaderParams.dispatchThreadID.xy * 2 + pk;

        uint4 storeDwords = uint4(0,0,0,0);'''
AFTER_OUTPUT = '''        const uint2 poBase2D = computeShaderParams.dispatchThreadID.xy * 2 + pk;
        // Defense in depth for non-exact dispatches and future model sizes.
        if (any(poBase2D >= output.logicalSize.xy))
            continue;

        uint4 storeDwords = uint4(0,0,0,0);'''


def sha256(contents: bytes) -> str:
    return hashlib.sha256(contents).hexdigest()


def verify_pass11_source(fsr4_root: Path) -> dict:
    """Fail closed if the pinned 1080p model no longer matches this analysis."""
    model = (fsr4_root / 'internal' / 'shaders' /
             'fsr4_model_v07_i8_native' / 'passes_1080.hlsl')
    source = model.read_text(encoding='utf-8-sig').replace('\r\n', '\n')
    section_start = '#ifdef MLSR_PASS_11\n'
    section_end = '#endif // #ifdef MLSR_PASS_11'
    matches = list(re.finditer(r'(?m)^[ \t]*#ifdef MLSR_PASS_11[ \t]*$', source))
    if len(matches) != 1 or section_end not in source[matches[0].end():]:
        raise ValueError('Expected one Native 1080 pass11 section')
    part = source[matches[0].end():].split(section_end, 1)[0]
    required = [
        '[numthreads(64, 1, 1)]',
        'FNB_CT2D_ADD<32, 1>(',
        'uint3(480, 270, 32)',
        'uint3(960, 540, 16)',
        'threadGroupByteOffsetInTensor_slice_22 + 12441600',
    ]
    missing = [x for x in required if x not in part]
    if missing:
        raise ValueError(f'Pinned Native 1080 pass11 geometry changed: {missing}')
    return {'pass11_source_sha256': sha256(model.read_bytes()),
            'pass11_geometry_verified': True}


def guarded_operator(text: str) -> str:
    """Patch only the scalar <32,1> overload before the separate WMMA section."""
    canonical = text.replace('\r\n', '\n')
    if SENTINEL in canonical:
        raise ValueError('Source already contains the FSR4N10 Pass 11 guard; double patch refused')
    specializations = list(re.finditer(re.escape(START), canonical))
    if len(specializations) != 2:
        raise ValueError(f'Expected scalar and WMMA <32,1> specializations, got {len(specializations)}')
    start = specializations[0].start()
    wmma_specialization = specializations[1].start()
    finish = canonical.find(END, specializations[0].end())
    if finish < 0 or finish >= wmma_specialization:
        raise ValueError('Could not prove the scalar <32,1> overload ends before the WMMA overload')
    directive_end = canonical.find('\n', finish)
    if directive_end < 0 or canonical[finish:directive_end].strip() != END:
        raise ValueError('Expected an exact WMMA_ENABLED branch boundary after the scalar overload')
    wmma_end = canonical.find('#endif // #if WMMA_ENABLED', wmma_specialization)
    if wmma_end < wmma_specialization:
        raise ValueError('Could not delimit the separate WMMA <32,1> overload')
    fragment = canonical[start:finish]
    if fragment.count(START) != 1:
        raise ValueError('The scalar overload scope does not contain exactly one <32,1> specialization')
    for old, replacement, label in (
        (BEFORE_INPUT, AFTER_INPUT, 'early input bounds'),
        (BEFORE_OUTPUT, AFTER_OUTPUT, 'output bounds'),
    ):
        if fragment.count(old) != 1:
            raise ValueError(f'Unexpected pinned {label} anchor count: {fragment.count(old)}')
        fragment = fragment.replace(old, replacement, 1)
    if fragment.count('if (any(computeShaderParams.dispatchThreadID.xy >= input.logicalSize.xy))') != 1:
        raise ValueError('Input bounds check was not installed exactly once')
    if fragment.count('if (any(poBase2D >= output.logicalSize.xy))') != 1:
        raise ValueError('Output bounds check was not installed exactly once')
    result = canonical[:start] + fragment + canonical[finish:]
    assert result[:start] == canonical[:start]
    assert result[start + len(fragment):] == canonical[finish:]
    return result


def create_overlay(fsr4_root: Path, output_dir: Path) -> dict:
    provenance = verify_pass11_source(fsr4_root)
    source = fsr4_root / 'dx12' / OPERATOR_REL
    destination = output_dir / 'capture_shader_overrides' / OPERATOR_REL
    if not source.is_file():
        raise FileNotFoundError(f'Pinned FSR4 operator missing: {source}')
    original = source.read_bytes()
    transformed = guarded_operator(original.decode('utf-8-sig')).encode('utf-8')
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(transformed)
    return {
        'schema': 'f4n10.pass11-bounds-guard-overlay.v1',
        **provenance,
        'source': source.as_posix(),
        'source_sha256': sha256(original),
        'overlay': destination.as_posix(),
        'overlay_sha256': sha256(transformed),
        'guard_marker': SENTINEL,
        'overload': 'FNB_CT2D_ADD<32,1>',
        'scope': 'Build-local shader include, original model and weights unchanged',
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fsr4-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    result = create_overlay(args.fsr4_root, args.output)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
