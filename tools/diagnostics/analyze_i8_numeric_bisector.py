#!/usr/bin/env python3
"""Identify the first *valid model-output* tensor difference of two FSR4 I8 runs.

Use matching guarded, literal-POST, same-input fresh-process scratch snapshots.
No performance/quality verdict is inferred from two arithmetic paths differing.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import numpy as np

from i8_tensor_layout import SCRATCH_BYTES, MODEL, parse_file


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for data in iter(lambda: stream.read(1 << 20), b''):
            h.update(data)
    return h.hexdigest()


def byte_difference(left: np.ndarray, right: np.ndarray, base: int = 0,
                    tensor: dict[str, Any] | None = None) -> dict[str, Any]:
    if left.ndim != 1 or right.ndim != 1 or left.dtype != np.uint8 or right.dtype != np.uint8:
        raise ValueError('byte_difference expects 1D uint8 arrays')
    if left.shape != right.shape or left.size <= 0:
        raise ValueError('snapshot regions must be nonempty and equally sized')
    unequal = left != right
    differing = int(np.count_nonzero(unequal))
    if not differing:
        return {'different_bytes': 0, 'different_fraction': 0.0,
                'first_relative_byte': None, 'first_absolute_byte': None,
                'first_coordinate': None, 'first_values_signed_i8': None,
                'max_abs_signed_delta': 0, 'mean_abs_signed_delta': 0.0,
                'differing_lanes_within_1_lsb_fraction': 1.0,
                'differing_lanes_within_2_lsb_fraction': 1.0,
                'p99_differing_abs_signed_delta': 0.0}
    pos = int(np.argmax(unequal))
    signed_l = left.view(np.int8).astype(np.int16, copy=False)
    signed_r = right.view(np.int8).astype(np.int16, copy=False)
    signed_delta = np.abs(signed_l - signed_r)
    coordinate = None
    if tensor:
        w, h, c = (tensor['width'], tensor['height'], tensor['channels'])
        if left.size != w * h * c:
            raise ValueError('tensor region not contiguous or incorrectly sized')
        coordinate = {'x': (pos // c) % w, 'y': pos // (w * c), 'channel': pos % c}
    return {
        'different_bytes': differing,
        'different_fraction': float(differing / left.size),
        'first_relative_byte': pos,
        'first_absolute_byte': base + pos,
        'first_coordinate': coordinate,
        'first_values_signed_i8': [int(signed_l[pos]), int(signed_r[pos])],
        'max_abs_signed_delta': int(np.max(signed_delta)),
        'mean_abs_signed_delta': float(np.mean(signed_delta)),
        'differing_lanes_within_1_lsb_fraction': float(np.mean(signed_delta[unequal] <= 1)),
        'differing_lanes_within_2_lsb_fraction': float(np.mean(signed_delta[unequal] <= 2)),
        'p99_differing_abs_signed_delta': float(np.quantile(signed_delta[unequal], .99)),
    }


def index_cases(campaign: dict) -> dict[tuple[str, str, int], dict]:
    cases = campaign.get('cases')
    if not isinstance(cases, list) or not cases:
        raise ValueError('campaign is missing case data')
    result = {}
    for item in cases:
        key = (item['seed'], item['pass_name'], item['repeat'])
        if key in result:
            raise ValueError(f'duplicate campaign case {key}')
        result[key] = item
    return result


def snapshot(case: dict, context: str) -> np.ndarray:
    desc = case['scratch'][context]
    path = Path(desc['path'])
    if int(desc['size']) != SCRATCH_BYTES or path.stat().st_size != SCRATCH_BYTES:
        raise ValueError(f'{path}: scratch-size mismatch')
    if sha256(path) != desc['sha256']:
        raise ValueError(f'{path}: scratch SHA256 does not match campaign report')
    return np.memmap(path, dtype=np.uint8, mode='r')


def ensure_modes(left: dict, right: dict) -> None:
    for item in (left, right):
        if item.get('schema') != 'f4n10.i8-numeric-campaign.v1':
            raise ValueError('unrecognized I8 campaign schema')
        flags = item['diagnostic_modes']
        if flags.get('pass11_bounds_guard') is not True:
            raise ValueError('both runs must enable validated Pass 11 guard')
        if flags.get('stable_post_math') is not False:
            raise ValueError('both runs must retain literal source POST')
    if left['source_commit'] != right['source_commit']:
        raise ValueError('upstream source revisions differ')
    if left['sequence_file_sha256'] != right['sequence_file_sha256']:
        raise ValueError('two runs use different .f4seq bytes')
    if left.get('trace_frame') != right.get('trace_frame'):
        raise ValueError('different trace frame indices')
    for name in ('stages', 'seeds', 'repeats'):
        if left.get(name) != right.get(name):
            raise ValueError(f'campaign dimensions differ: {name}')


def analyze(left: dict, right: dict, tensor_contracts: dict) -> dict:
    ensure_modes(left, right)
    lcases, rcases = index_cases(left), index_cases(right)
    if set(lcases) != set(rcases):
        raise ValueError('case matrices are incomplete or not identical')
    tensors = {f'pass_{p["pass_index"]:02d}': p for p in tensor_contracts['passes']}
    rows = []
    clean = True
    same_inputs = True
    machines: set[tuple[str, str]] = set()
    # Inspect both variants separately for repeatability before comparing them.
    included_stages = tuple('full' if s == 'full' else f'pass_{int(s):02d}'
                            for s in left['stages'])
    for variant, cases in ((left['variant'], lcases), (right['variant'], rcases)):
        for seed in left['seeds']:
            for stage in included_stages:
                runs = [cases[(seed, stage, i)] for i in range(1, left['repeats'] + 1)]
                if any(x.get('error') for x in runs):
                    clean = False
                for context in ('ordinary', 'instrumented'):
                    first = runs[0]['scratch'].get(context, {}).get('sha256')
                    if not first or any(run['scratch'].get(context, {}).get('sha256') != first for run in runs):
                        clean = False
                for run in runs:
                    if run['scratch'].get('ordinary', {}).get('sha256') != run['scratch'].get('instrumented', {}).get('sha256'):
                        clean = False
                    frame_hashes = run.get('frame_hashes', [])
                    if stage == 'full' and any(f['ordinary'] != f['instrumented'] for f in frame_hashes):
                        clean = False
                if any(r['input_hashes'] != runs[0]['input_hashes'] or
                       r.get('sequence_hash') != runs[0].get('sequence_hash') for r in runs[1:]):
                    same_inputs = False
    first_output_diffs = []
    for seed in left['seeds']:
        for stage in included_stages:
            for repeat in range(1, left['repeats'] + 1):
                key = (seed, stage, repeat)
                lc, rc = lcases[key], rcases[key]
                if lc.get('error') or rc.get('error'):
                    clean = False
                    continue
                machines.add((lc.get('adapter') or '', lc.get('driver_version') or ''))
                machines.add((rc.get('adapter') or '', rc.get('driver_version') or ''))
                def valid_sha(value: object) -> bool:
                    return isinstance(value, str) and bool(re.fullmatch(r'[0-9a-f]{64}', value))
                if (lc['input_hashes'] != rc['input_hashes'] or
                    lc['sequence_hash'] != rc['sequence_hash'] or
                    not valid_sha(lc.get('sequence_hash')) or
                    not isinstance(lc.get('input_hashes'), list) or
                    not lc['input_hashes'] or
                    not all(valid_sha(h) for h in lc['input_hashes']) or
                    lc.get('adapter') != rc.get('adapter') or
                    lc.get('driver_version') != rc.get('driver_version')):
                    same_inputs = False
                    continue
                for context in ('ordinary', 'instrumented'):
                    a, b = snapshot(lc, context), snapshot(rc, context)
                    whole = byte_difference(a, b)
                    region = None
                    tensor = tensors.get(stage)
                    if tensor is not None:
                        base, count = tensor['byte_base'], tensor['byte_count']
                        region = byte_difference(a[base:base + count], b[base:base + count], base, tensor)
                        if region['different_bytes']:
                            first_output_diffs.append({'pass_index': tensor['pass_index'],
                                                       'seed': seed, 'repeat': repeat,
                                                       'context': context, 'tensor': tensor['name'],
                                                       **region})
                    rows.append({'seed': seed, 'stage': stage, 'repeat': repeat,
                                 'context': context, 'input_aligned': True,
                                 'whole_scratch_different_bytes': whole['different_bytes'],
                                 'whole_scratch_first_byte': whole['first_absolute_byte'],
                                 'valid_tensor': tensor['name'] if tensor else None,
                                 'valid_tensor_byte_base': tensor['byte_base'] if tensor else None,
                                 'valid_tensor_byte_count': tensor['byte_count'] if tensor else None,
                                 'valid_tensor_different_bytes': region['different_bytes'] if region else None,
                                 'valid_tensor_first_absolute_byte': region['first_absolute_byte'] if region else None,
                                 'valid_tensor_first_coordinate': region['first_coordinate'] if region else None,
                                 'max_abs_signed_delta': region['max_abs_signed_delta'] if region else None,
                                 'mean_abs_signed_delta': region['mean_abs_signed_delta'] if region else None,
                                 'physical_mean_abs_delta': (region['mean_abs_signed_delta'] * tensor['quantization_scale']
                                    if region and tensor.get('quantization_scale') is not None else None),
                                 'differing_lanes_within_1_lsb_fraction': (region['differing_lanes_within_1_lsb_fraction'] if region else None),
                                 'differing_lanes_within_2_lsb_fraction': (region['differing_lanes_within_2_lsb_fraction'] if region else None),
                                 'p99_differing_abs_signed_delta': (region['p99_differing_abs_signed_delta'] if region else None),
                                 'valid_tensor_quantization_scale': tensor['quantization_scale'] if tensor else None})
    if len(machines) != 1 or any(not a or not b for a, b in machines):
        same_inputs = False
    first = min((x['pass_index'] for x in first_output_diffs), default=None)
    first_detail = next((x for x in first_output_diffs if x['pass_index'] == first), None)
    # If the first observed mismatch is at a later tensor, preceding output
    # regions are proven equal for all sampled contexts, seeds and repeats.
    return {'schema': 'f4n10.i8-numeric-bisector-analysis.v1',
            'left_variant': left['variant'], 'right_variant': right['variant'],
            'source_commit': left['source_commit'],
            'model_hlsl_sha256': tensor_contracts['source_sha256'],
            'sequence_file_sha256': left['sequence_file_sha256'],
            'same_inputs': same_inputs, 'within_mode_repeatable': clean,
            'machines': [{'adapter': a, 'driver_version': d} for a, d in sorted(machines)],
            'first_valid_output_tensor_difference': first_detail,
            'first_valid_output_pass': first,
            'valid_output_tensor_difference_count': len(first_output_diffs),
            'all_observed_valid_model_outputs_bit_equal': not bool(first_output_diffs),
            'notes': ('Two stable providers can disagree mathematically. This localizes the first '
                      'observed valid I8 output tensor difference but does not prove which '
                      'arithmetic backend matches AMD reference. Scratch dump occurs after POST.'),
            'rows': rows}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--left', type=Path, required=True)
    ap.add_argument('--right', type=Path, required=True)
    ap.add_argument('--repo', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--csv', type=Path)
    args = ap.parse_args()
    contracts = parse_file(args.repo / MODEL)
    left = json.loads(args.left.read_text(encoding='utf-8'))
    right = json.loads(args.right.read_text(encoding='utf-8'))
    analysis = analyze(left, right, contracts)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(analysis, indent=2) + '\n', encoding='utf-8')
    if args.csv:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        with args.csv.open('w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=list(analysis['rows'][0]))
            writer.writeheader()
            for item in analysis['rows']:
                writer.writerow(item)
    print('First valid output tensor difference:', analysis['first_valid_output_pass'])
    print('same inputs:', analysis['same_inputs'],
          'within-mode repeatable:', analysis['within_mode_repeatable'])
    if not analysis['same_inputs'] or not analysis['within_mode_repeatable']:
        return 3
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
