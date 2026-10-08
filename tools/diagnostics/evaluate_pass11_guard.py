#!/usr/bin/env python3
"""Evaluate Pass11 bound-guard evidence without unlocking FSR4 O0.

Conservative: shader parity, frame-to-frame repeatability, mode invariance and
scratch repeatability are independent requirements. A diagnostic fix is not a
production-quality or full GPU/CPU image-quality validation result.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def read_cases(campaign: dict) -> dict:
    if campaign.get('schema') != 'f4n10.pass11-guard-campaign.v1':
        raise ValueError('Unexpected campaign schema')
    rows = {}
    for case in campaign['cases']:
        key = (case['seed'], case['pass_name'], case['repeat'])
        if key in rows:
            raise ValueError(f'Duplicate case {key}')
        rows[key] = case
    return rows


def assess_campaign(campaign: dict) -> dict:
    rows = read_cases(campaign)
    errors = [key for key, item in rows.items() if item.get('error') or item.get('exit_code') != 0]
    repeats = defaultdict(list)
    all_frames = defaultdict(list)
    for key, case in rows.items():
        seed, prefix, repeat = key
        repeats[(seed, prefix)].append((repeat, case))
        if prefix == 'full':
            all_frames[seed].append((repeat, case['frames']))
    scratch_checks = {}
    for (seed, prefix), group in sorted(repeats.items()):
        if prefix not in ('pass_10', 'pass_11', 'pass_12', 'full'):
            continue
        group.sort(key=lambda x: x[0])
        scratch_checks[f'{seed}/{prefix}'] = {
            c: len({case['files'].get(c, {}).get('sha256') for _, case in group}) == 1
            for c in ('ordinary', 'instrumented')
        }
    full_rgb_checks = {}
    for seed, group in sorted(all_frames.items()):
        group.sort(key=lambda x: x[0])
        frames = [f for _, f in group]
        n = len(frames[0]) if frames else 0
        if not frames or any(len(f) != n for f in frames) or n == 0:
            full_rgb_checks[seed] = {'complete': False}
            continue
        frame_ids = [f['frame_index'] for f in frames[0]]
        same_input = all([f['frame_index'] for f in sequence] == frame_ids for sequence in frames)
        same_input &= all(all(sequence[i]['input_frame_sha256'] == frames[0][i]['input_frame_sha256']
                              for i in range(n)) for sequence in frames)
        ordinary_repeatable = all(len({sequence[i]['reference_output_sha256'] for sequence in frames}) == 1
                                  for i in range(n))
        instrumented_repeatable = all(len({sequence[i]['instrumented_output_sha256'] for sequence in frames}) == 1
                                      for i in range(n))
        intra_parity = all(all(frame['output_identical'] is True and frame['outputs_finite'] is True
                               for frame in sequence) for sequence in frames)
        full_rgb_checks[seed] = {
            'complete': True, 'frame_count': n, 'input_hashes_repeatable': same_input,
            'ordinary_repeatable': ordinary_repeatable,
            'instrumented_repeatable': instrumented_repeatable,
            'instrumented_matches_ordinary_exact': intra_parity,
        }
    modes = sorted(full_rgb_checks)
    cross_seed_equal = None
    if len(modes) >= 2 and all(full_rgb_checks[m].get('complete') for m in modes):
        # Seed comparisons are made within run 1 of each mode; all input hashes
        # must agree before claiming output independence.
        first = all_frames[modes[0]][0][1]
        cross_seed_equal = True
        for mode in modes[1:]:
            other = all_frames[mode][0][1]
            if len(other) != len(first):
                cross_seed_equal = False
                break
            for x, y in zip(first, other):
                if x['input_frame_sha256'] != y['input_frame_sha256'] or \
                   x['reference_output_sha256'] != y['reference_output_sha256'] or \
                   x['instrumented_output_sha256'] != y['instrumented_output_sha256']:
                    cross_seed_equal = False
                    break
    seeds = sorted({case['seed'] for case in rows.values()})
    required_passes = ('pass_10', 'pass_11', 'pass_12', 'full')
    complete = len(seeds) >= 2 and all(
        len(repeats.get((seed, prefix), [])) >= 2
        for seed in seeds for prefix in required_passes)
    good_scratch = complete and all(
        all(scratch_checks[f'{seed}/pass_11'].values()) for seed in seeds)
    all_full_repeat = bool(full_rgb_checks) and all(
        item.get('input_hashes_repeatable') and item.get('ordinary_repeatable')
        and item.get('instrumented_repeatable') and item.get('instrumented_matches_ordinary_exact')
        for item in full_rgb_checks.values())
    all_inputs = {tuple(case.get('input_hashes', [])) for case in rows.values()}
    all_sequences = {case.get('sequence_hash') for case in rows.values()}
    aligned = len(all_inputs) == 1 and len(all_sequences) == 1 and all_sequences != {None}
    return {
        'variant': campaign.get('variant'),
        'expected_guard': campaign.get('expected_guard'),
        'case_count': len(rows), 'complete_coverage': complete, 'run_failures': len(errors),
        'failed_cases': [list(x) for x in errors[:12]],
        'input_hashes_aligned': aligned,
        'pass11_scratch_repeatable': good_scratch,
        'scratch': scratch_checks,
        'full_rgb': full_rgb_checks,
        'full_rgb_repeatability_and_exact_parity': all_full_repeat,
        'cross_seed_full_rgb_equal': cross_seed_equal,
        'candidate_fixed': not errors and complete and aligned and good_scratch
            and all_full_repeat and cross_seed_equal is True,
    }


def evaluate(baseline: dict, guard_scalar: dict, guard_intrinsic: dict) -> dict:
    results = [assess_campaign(c) for c in (baseline, guard_scalar, guard_intrinsic)]
    if [r['expected_guard'] for r in results] != [False, True, True]:
        raise ValueError('Expected baseline OFF, scalar ON and intrinsic ON manifests')
    aligned = all(r['input_hashes_aligned'] for r in results)
    seqs = {c['cases'][0].get('sequence_hash') for c in (baseline, guard_scalar, guard_intrinsic)}
    frames = {tuple(c['cases'][0].get('input_hashes', [])) for c in (baseline, guard_scalar, guard_intrinsic)}
    aligned &= len(seqs) == 1 and len(frames) == 1
    localized = (aligned and not results[0]['pass11_scratch_repeatable']
                 and results[1]['pass11_scratch_repeatable']
                 and results[2]['pass11_scratch_repeatable'])
    root_candidate_confirmed = (localized and not results[0]['candidate_fixed']
                                and results[1]['candidate_fixed'] and results[2]['candidate_fixed'])
    return {
        'schema': 'f4n10.pass11-bounds-evaluation.v1',
        'input_provenance_aligned': aligned,
        'baseline': results[0], 'guard_scalar': results[1],
        'guard_intrinsic': results[2],
        'pass11_local_scratch_nondeterminism_resolved': bool(localized),
        'pass11_bounds_hypothesis_supported_by_gpu': bool(root_candidate_confirmed),
        'o0_teacher_eligible': False,
        'o0_note': 'Do not change the existing O0 gate. Re-run exact CPU/GPU POST, capture parity, reproducibility, finite arrays and real-scene audits.',
        'next_steps': (
            'If guarded builds stabilize: run existing unmodified O0 gates, build all modes/presets '
            'and investigate first-frame numeric deviations. If not: validate the compiled DXIL actually '
            'contains the guard, then inspect the pass-11 and POST boundaries and all RW resource OOB accesses.'
        ),
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--baseline', type=Path, required=True)
    p.add_argument('--guard-scalar', type=Path, required=True)
    p.add_argument('--guard-intrinsic', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    try:
        doc = evaluate(*[json.loads(path.read_text(encoding='utf-8')) for path in
                          (args.baseline, args.guard_scalar, args.guard_intrinsic)])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        p.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(doc, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps({'pass11_local_scratch_nondeterminism_resolved': doc['pass11_local_scratch_nondeterminism_resolved'],
                      'pass11_bounds_hypothesis_supported_by_gpu': doc['pass11_bounds_hypothesis_supported_by_gpu'],
                      'baseline': doc['baseline']['candidate_fixed'],
                      'guard_scalar': doc['guard_scalar']['candidate_fixed'],
                      'guard_intrinsic': doc['guard_intrinsic']['candidate_fixed']}, indent=2))
    return 0  # A failing technical hypothesis is a valid diagnostic outcome.


if __name__ == '__main__':
    raise SystemExit(main())
