#!/usr/bin/env python3
"""Verify guarded provider model-11 reflected shader content differs from baseline.

This is a compiled-artifact discriminator, not a proof that every DXIL lane is
correct. Both manifests must come from same locked source and scalar mode.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

PASS11 = 'fsr4_model_v07_i8_native_1080_11_permutations.h'


def check_manifests(original: dict, guarded: dict) -> dict:
    bo = original.get('diagnostic_modes', {})
    bg = guarded.get('diagnostic_modes', {})
    if original.get('source_commit') != guarded.get('source_commit'):
        raise ValueError('Upstream source commit differs')
    if bo.get('scalar_dot4') != bg.get('scalar_dot4'):
        raise ValueError('Do not compare differing scalar_dot4 modes')
    if bo.get('pass11_bounds_guard') is not False or bg.get('pass11_bounds_guard') is not True:
        raise ValueError('Expected OFF vs ON bounds toggles')
    if original.get('source_hashes_sha256') != guarded.get('source_hashes_sha256'):
        raise ValueError('Pinned model inputs, weights or other upstream files changed')
    left = {x['file']: x['sha256'] for x in original.get('outputs', [])}
    right = {x['file']: x['sha256'] for x in guarded.get('outputs', [])}
    if set(left) != set(right) or PASS11 not in left:
        raise ValueError('Missing or differing shader files between builds')
    changed = sorted(name for name in left if left[name] != right[name])
    return {'schema': 'f4n10.pass11-shader-manifest-diff.v1',
            'pass11_header': PASS11,
            'pass11_compiled_artifact_changed': PASS11 in changed,
            'changed_shader_headers': changed,
            'unchanged_shader_header_count': len(left) - len(changed),
            'source_hashes_equal': True,
            'warning': 'Different generated headers are necessary but not sufficient to prove the intended guard is present in DXIL.'}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--baseline', type=Path, required=True)
    p.add_argument('--guard', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    try:
        doc = check_manifests(json.loads(args.baseline.read_text(encoding='utf-8')),
                              json.loads(args.guard.read_text(encoding='utf-8')))
    except (OSError, ValueError, KeyError) as exc:
        p.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(doc, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(doc, indent=2))
    return 0 if doc['pass11_compiled_artifact_changed'] else 3


if __name__ == '__main__':
    raise SystemExit(main())
