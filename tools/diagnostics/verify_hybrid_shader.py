#!/usr/bin/env python3
"""Verify single-pass scalar shader payload changed and all other passes did not.

Selector headers may reorder; compares actual content-addressed blob SHA-256 sets.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

MODEL = 'fsr4_model_v07_i8_native_1080'


def payload_sets(manifest: dict) -> dict[str, list[tuple[str, int | None]]]:
    files = {Path(x['file']).name: x for x in manifest.get('outputs', [])}
    selectors = [name for name in files if name.endswith('_permutations.h')]
    if not selectors:
        raise ValueError('missing reflected shader selector headers')
    result = {}
    for sel in selectors:
        stem = sel[:-len('_permutations.h')]
        pattern = re.compile(r'^' + re.escape(stem) + r'_([0-9a-fA-F]{32})\.h$')
        values = [(item['sha256'], item.get('size_bytes'))
                  for name, item in files.items() if pattern.fullmatch(name)]
        if not values:
            raise ValueError(f'missing compiled payload for selector {sel}')
        result[sel] = sorted(values)
    return result


def verify(native: dict, hybrid: dict, selected_pass: int) -> dict:
    if selected_pass not in range(1, 13):
        raise ValueError('selected pass must be 1..12')
    for m in (native, hybrid):
        d = m.get('diagnostic_modes', {})
        if d.get('pass11_bounds_guard') is not True or d.get('scalar_dot4') is not False:
            raise ValueError('both manifests require guarded native baseline mode')
        if d.get('stable_post_math') is not False:
            raise ValueError('must compare identical literal POST compilation')
    native_set = native['diagnostic_modes'].get('scalar_dot4_pass_set', [])
    hybrid_set = hybrid['diagnostic_modes'].get('scalar_dot4_pass_set', [])
    if native_set or hybrid_set != [selected_pass]:
        raise ValueError('expected [] vs precisely one selected-pass scalar shim')
    if native.get('source_commit') != hybrid.get('source_commit') or (
        native.get('source_hashes_sha256') != hybrid.get('source_hashes_sha256')):
        raise ValueError('upstream source or weights changed')
    a, b = payload_sets(native), payload_sets(hybrid)
    if set(a) != set(b):
        raise ValueError('different selector sets; not an isolated experiment')
    changed = sorted(x for x in a if a[x] != b[x])
    expected = f'{MODEL}_{selected_pass}_permutations.h'
    return {'schema': 'f4n10.i8-hybrid-artifact-verification.v1',
            'pass_index': selected_pass, 'source_commit': native['source_commit'],
            'changed_compiled_payload_selectors': changed,
            'expected_changed_selector': expected,
            'verified_isolated_pass_change': changed == [expected],
            'unchanged_selector_count': len(a) - len(changed)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--native', type=Path, required=True)
    ap.add_argument('--hybrid', type=Path, required=True)
    ap.add_argument('--pass', dest='pass_index', type=int, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    result = verify(json.loads(args.native.read_text(encoding='utf-8')),
                    json.loads(args.hybrid.read_text(encoding='utf-8')),
                    args.pass_index)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2))
    return 0 if result['verified_isolated_pass_change'] else 3


if __name__ == '__main__':
    raise SystemExit(main())
