#!/usr/bin/env python3
"""Read-only I8 preset/tier survey of Pass11 overdispatch risk.

Conservative source-only audit, not DXIL or full memory safety proof. The
non-WMMA FSR4 provider dispatches ceil(second encoder width / 64) x encoder
height groups. Checks whether Pass11's source operator is FNB_CT2D_ADD<32,1>.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

PRESETS = ('native', 'quality', 'balanced', 'performance', 'drs', 'ultraperf')
TIERS = ('1080', '2160', '4320')
MODEL = 'fsr4_model_v07_i8_'
THREAD_GROUP_SIZE = 64


def audit_pass11(path: Path) -> dict:
    content = path.read_text(encoding='utf-8-sig').replace('\r\n', '\n')
    start = re.search(r'(?m)^#ifdef MLSR_PASS_11[ \t]*$', content)
    if not start:
        raise ValueError(f'Pass11 not found: {path}')
    end = content.find('#endif // #ifdef MLSR_PASS_11', start.end())
    if end < 0:
        raise ValueError(f'Pass11 end marker missing: {path}')
    segment = content[start.end():end]
    entry = re.search(r'\[numthreads\((\d+),\s*(\d+),\s*(\d+)\)\]\s*void\s+fsr4_model_v07_i8_pass11', segment)
    if not entry:
        raise ValueError(f'Unexpected pass11 entry point: {path}')
    dims = tuple(int(n) for n in entry.groups())
    matches = re.findall(
        r'const\s+(?:Quantized)?Tensor3i8_NHWC\s*<\s*RWBufferStorage\s*>\s+\w+\s*=\s*\{\s*'
        r'uint3\((\d+),\s*(\d+),\s*(\d+)\)', segment)
    if len(matches) < 2:
        raise ValueError(f'Cannot identify pass11 input/output tensor shapes: {path}')
    width, height, channels = [int(x) for x in matches[0]]
    out_width, out_height, out_channels = [int(x) for x in matches[-1]]
    specialized = 'FNB_CT2D_ADD<32, 1>(' in segment
    excess = ((width + THREAD_GROUP_SIZE - 1) // THREAD_GROUP_SIZE) * THREAD_GROUP_SIZE - width
    two_x = out_width == 2 * width and out_height == 2 * height
    source_unchecked = specialized and dims == (64, 1, 1) and excess > 0 and two_x
    return {'source': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'numthreads': list(dims), 'input': [width, height, channels],
            'output': [out_width, out_height, out_channels],
            'operator_32_1': specialized, 'non_wmma_overhang_threads_per_row': excess,
            'predicted_next_row_alias_pixels': excess * 2 if two_x else None,
            'requires_bounds_guard_or_corrected_dispatch': source_unchecked,
            'source_only': True}


def audit_all(fsr4_root: Path) -> dict:
    records = []
    for preset in PRESETS:
        for tier in TIERS:
            path = (fsr4_root / 'internal/shaders' / f'{MODEL}{preset}' /
                    f'passes_{tier}.hlsl')
            try:
                info = audit_pass11(path)
                info['audit_status'] = 'parsed'
            except (OSError, ValueError) as exc:
                # Other presets may diverge structurally; never abort the
                # Native/1080 repair campaign for a secondary survey.
                info = {'source': str(path), 'audit_status': 'unknown',
                        'error': str(exc), 'requires_bounds_guard_or_corrected_dispatch': False}
            info.update({'preset': preset, 'resolution_tier': tier})
            records.append(info)
    return {'schema': 'f4n10.i8-pass11-coverage-audit.v1',
            'provider_dispatch_rule': 'ceil(second-encoder-width/64) groups X; second-encoder-height groups Y',
            'cases': records,
            'unparsed_cases': [f"{x['preset']}/{x['resolution_tier']}" for x in records
                               if x['audit_status'] != 'parsed'],
            'possible_overdispatch_hazard_cases': [
                f"{x['preset']}/{x['resolution_tier']}" for x in records
                if x['requires_bounds_guard_or_corrected_dispatch']],
            'caveat': 'Source geometry only; compiler, model variant and actual device dispatch must be verified.'}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--fsr4-root', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    try:
        report = audit_all(a.fsr4_root)
    except (OSError, ValueError) as exc:
        p.error(str(exc))
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(f"Audited {len(report['cases'])} I8 source variants; potential overdispatch hazards: "
          f"{', '.join(report['possible_overdispatch_hazard_cases'])}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
