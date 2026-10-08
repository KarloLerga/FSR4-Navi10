#!/usr/bin/env python3
"""Map scratch disagreements to the exact Pass-11 FNB_CT2D_ADD tensor geometry.

The source-grounded race candidate is 32 invalid x-threads per dispatch row.
Their 2x output writes alias the first 64 pixels of a subsequent row.
This script supplies a *spatial* discriminator. It does not prove the GPU race.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Iterable

import numpy as np

# Pinned FSR4 I8 Native 1920x1080, FNB_CT2D_ADD<32,1> Pass 11.
INPUT_WIDTH = 480
INPUT_HEIGHT = 270
THREADS_X = 64
DISPATCH_GROUPS_X = (INPUT_WIDTH + THREADS_X - 1) // THREADS_X
OUTPUT_WIDTH = 960
OUTPUT_HEIGHT = 540
OUTPUT_CHANNELS = 16
OUTPUT_BASE = 12_441_600
OUTPUT_STRIDE = OUTPUT_WIDTH * OUTPUT_CHANNELS
OUTPUT_END = OUTPUT_BASE + OUTPUT_STRIDE * OUTPUT_HEIGHT
SCRATCH_BYTES = 20_880_256
OVERFLOW_OUTPUT_PIXELS = 2 * (DISPATCH_GROUPS_X * THREADS_X - INPUT_WIDTH)


def aliases_at_output_row(row: int) -> dict:
    """Show one valid writer and one invalid writer aliasing the same byte."""
    if not 1 <= row < OUTPUT_HEIGHT:
        raise ValueError('row must be between 1 and output height - 1')
    # For row=r, the invalid producer is output x=960 at row r-1.
    # Its launch y and local 2x2 offset depend on the parity of r-1.
    spill_y = row - 1
    return {
        'physical_output_row': row,
        'scratch_byte_offset': OUTPUT_BASE + row * OUTPUT_STRIDE,
        'valid_writer': {
            'dispatch_thread_xy': [0, row // 2],
            'local_xy': [0, row % 2],
            'semantic_output_xy': [0, row],
        },
        'invalid_writer': {
            'dispatch_thread_xy': [INPUT_WIDTH, spill_y // 2],
            'local_xy': [0, spill_y % 2],
            'semantic_output_xy': [OUTPUT_WIDTH, spill_y],
        },
    }


def label_offsets(offsets: Iterable[int]) -> dict:
    """Classify changed scratch offsets without assuming unobserved GPU stores."""
    total = 0
    in_output = 0
    in_alias_columns = 0
    outside_output = 0
    row_counter: Counter[int] = Counter()
    examples = []
    for offset in offsets:
        offset = int(offset)
        total += 1
        if OUTPUT_BASE <= offset < OUTPUT_END:
            in_output += 1
            local = offset - OUTPUT_BASE
            row, row_offset = divmod(local, OUTPUT_STRIDE)
            col, byte_in_pixel = divmod(row_offset, OUTPUT_CHANNELS)
            if row >= 1 and col < OVERFLOW_OUTPUT_PIXELS:
                in_alias_columns += 1
                row_counter[row] += 1
                if len(examples) < 8:
                    examples.append({'offset': offset, 'row': row,
                                     'column': col, 'byte_in_pixel': byte_in_pixel})
        else:
            outside_output += 1
    return {
        'changed_bytes': total,
        'inside_pass11_output': in_output,
        'candidate_alias_zone_bytes': in_alias_columns,
        'fraction_in_alias_zone': in_alias_columns / total if total else 0,
        'outside_pass11_output': outside_output,
        'top_alias_rows': [{'row': r, 'bytes_changed': c}
                           for r, c in row_counter.most_common(20)],
        'alias_examples': examples,
    }


def compare_scratch(a: Path, b: Path) -> dict:
    aa = np.memmap(a, dtype=np.uint8, mode='r')
    bb = np.memmap(b, dtype=np.uint8, mode='r')
    if len(aa) != len(bb):
        raise ValueError(f'Scratch size mismatch: {len(aa)}, {len(bb)}')
    if len(aa) != SCRATCH_BYTES:
        raise ValueError(f'Unexpected pinned Native 1080 scratch size: {len(aa)}')
    changed = np.flatnonzero(aa != bb)
    result = label_offsets(changed)
    result['first_changed_offset'] = int(changed[0]) if changed.size else None
    result['same_bytes'] = not bool(changed.size)
    result['files'] = [str(a), str(b)]
    return result


def analyze_campaign(campaign: dict) -> dict:
    cases = campaign.get('cases', [])
    by_key = {(row['seed'], row['pass_name'], row['repeat']): row for row in cases}
    report = []
    for seed in sorted({row['seed'] for row in cases if row['pass_name'] == 'pass_11'}):
        first = by_key.get((seed, 'pass_11', 1))
        second = by_key.get((seed, 'pass_11', 2))
        if not first or not second:
            continue
        for context in ('ordinary', 'instrumented'):
            lhs = Path(first['files'][context]['path'])
            rhs = Path(second['files'][context]['path'])
            entry = compare_scratch(lhs, rhs)
            report.append({'seed': seed, 'comparison': f'{context}_repeat1_vs_repeat2', **entry})
        for repeat, item in ((1, first), (2, second)):
            lhs = Path(item['files']['ordinary']['path'])
            rhs = Path(item['files']['instrumented']['path'])
            entry = compare_scratch(lhs, rhs)
            report.append({'seed': seed, 'comparison': f'ordinary_vs_instrumented_repeat{repeat}', **entry})
    return {'schema': 'f4n10.pass11-physical-alias.v1',
            'geometry': {
                'input_width': INPUT_WIDTH,
                'input_height': INPUT_HEIGHT,
                'threads_per_group': THREADS_X,
                'dispatch_groups_x': DISPATCH_GROUPS_X,
                'launched_threads_x': DISPATCH_GROUPS_X * THREADS_X,
                'invalid_threads_per_row': DISPATCH_GROUPS_X * THREADS_X - INPUT_WIDTH,
                'output_width': OUTPUT_WIDTH,
                'output_height': OUTPUT_HEIGHT,
                'output_channels': OUTPUT_CHANNELS,
                'output_base': OUTPUT_BASE,
                'output_stride': OUTPUT_STRIDE,
                'output_end': OUTPUT_END,
                'alias_pixels_at_next_row_start': OVERFLOW_OUTPUT_PIXELS,
                'row52_witness': aliases_at_output_row(52)},
            'comparisons': report,
            'interpretation': 'Only a correlation with predicted alias locations; GPU root cause requires guarded shader proof.'}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--campaign', type=Path)
    p.add_argument('--left', type=Path)
    p.add_argument('--right', type=Path)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    if a.campaign and not (a.left or a.right):
        result = analyze_campaign(json.loads(a.campaign.read_text(encoding='utf-8')))
    elif a.left and a.right and not a.campaign:
        result = {'schema': 'f4n10.pass11-physical-alias.v1', 'comparisons': [compare_scratch(a.left, a.right)]}
    else:
        p.error('Choose --campaign OR both --left and --right')
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(f'Wrote Pass11 alias map: {a.output}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
