#!/usr/bin/env python3
"""Verify guarded provider model-11 reflected shader content differs from baseline.

This is a compiled-artifact discriminator, not a proof that every DXIL lane is
correct. Both manifests must come from same locked source and scalar mode.
"""
from __future__ import annotations

import argparse
import json
import re
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
    source_operator_hash = original.get('source_hashes_sha256', {}).get('pass11_fnb_operator')
    original_include = original.get('pass11_operator_include', {})
    guarded_include = guarded.get('pass11_operator_include', {})
    if not source_operator_hash or original_include.get('sha256') != source_operator_hash:
        raise ValueError('Baseline Pass 11 did not resolve the pinned upstream FNB operator')
    original_path = original_include.get('path', '').replace('\\', '/')
    if 'capture_shader_overrides' in original_path:
        raise ValueError('Baseline unexpectedly resolves a build-local Pass 11 override')
    overlay_hash = guarded.get('capture_overlay_hashes_sha256', {}).get('pass11_fnb_bounds_guard')
    guarded_path = guarded_include.get('path', '').replace('\\', '/')
    operator_suffix = '/'.join(('capture_shader_overrides',
                                'FSR4N10_FNB_CT2D_ADD_PASS11_GUARD.hlsli'))
    if (not overlay_hash or guarded_include.get('sha256') != overlay_hash or
            not guarded_path.lower().endswith(operator_suffix.lower())):
        raise ValueError('Guarded Pass 11 did not resolve the build-local FNB overlay')
    left_outputs = {x['file']: x for x in original.get('outputs', [])}
    right_outputs = {x['file']: x for x in guarded.get('outputs', [])}
    left = {name: output['sha256'] for name, output in left_outputs.items()}
    right = {name: output['sha256'] for name, output in right_outputs.items()}
    # FidelityFX_SC may reorder a selector's include list and permutation
    # table without changing the content-addressed shader blob set. Compare
    # the blobs by digest/size and report selector-header hashes separately.
    stable_left = {name: digest for name, digest in left.items() if name.endswith('_permutations.h')}
    stable_right = {name: digest for name, digest in right.items() if name.endswith('_permutations.h')}
    if set(stable_left) != set(stable_right) or PASS11 not in stable_left:
        raise ValueError('Missing or differing stable shader selector headers between builds')
    def payloads(selector: str, outputs: dict) -> list[tuple[str, int | None]]:
        stem = selector[:-len('_permutations.h')]
        prefix = stem + '_'
        blobs = []
        for name, output in outputs.items():
            suffix = name[len(prefix):-2] if name.startswith(prefix) and name.endswith('.h') else ''
            if re.fullmatch(r'[0-9a-fA-F]{32}', suffix):
                blobs.append((output['sha256'], output.get('size_bytes')))
        return sorted(blobs)

    changed_payloads = sorted(name for name in stable_left
                              if payloads(name, left_outputs) != payloads(name, right_outputs))
    selector_hash_changed = sorted(name for name in stable_left
                                   if stable_left[name] != stable_right[name])
    selector_hash_changed_same_payloads = sorted(
        name for name in selector_hash_changed
        if payloads(name, left_outputs) == payloads(name, right_outputs))
    is_blob = lambda name: bool(re.search(r'_[0-9a-fA-F]{32}\.h$', name))
    added_blob_headers = sorted(name for name in set(right) - set(left) if is_blob(name))
    removed_blob_headers = sorted(name for name in set(left) - set(right) if is_blob(name))
    return {'schema': 'f4n10.pass11-shader-manifest-diff.v1',
            'pass11_header': PASS11,
            'pass11_compiled_artifact_changed': PASS11 in changed_payloads,
            'baseline_resolved_upstream_operator': True,
            'guard_resolved_overlay_operator': True,
            'upstream_operator_hash': source_operator_hash,
            'guard_operator_hash': guarded_include['sha256'],
            'changed_shader_payloads': changed_payloads,
            'selector_header_hash_changed': selector_hash_changed,
            'selector_header_hash_changed_with_same_payload_set': selector_hash_changed_same_payloads,
            'unchanged_shader_payload_count': len(stable_left) - len(changed_payloads),
            'content_addressed_blob_headers_added': added_blob_headers,
            'content_addressed_blob_headers_removed': removed_blob_headers,
            'source_hashes_equal': True,
            'warning': 'A changed Pass 11 payload and resolved overlay prove compilation selection, not numeric correctness or quality.'}


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
