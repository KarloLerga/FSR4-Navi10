#!/usr/bin/env python3
"""First fused-Pass1 DP4A operands vs source-derived independent CPU oracle.

Both variants must use the ``dot0`` probe (16 bytes per pixel at slice_2):
packed a:uint32, packed b:uint32, accumulator:int32, result:int32.
The probe returns from ConvNextBlock immediately after writing those words.
It must never be used as ordinary image output.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'tools/diagnostics'))
from pass1_golden import load_model, sample_coordinates  # type: ignore  # noqa: E402

SCRATCH_SIZE = 20_880_256
OUTPUT_OFFSET = 8_294_400
MODEL = REPO / 'third_party/fidelityfx-fsr4-source/Kits/FidelityFX/upscalers/fsr4/internal/shaders/fsr4_model_v07_i8_native/passes_1080.hlsl'


def hash_file(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            sha.update(block)
    return sha.hexdigest()


def case_index(campaign: dict) -> dict:
    if campaign.get('schema') != 'f4n10.i8-numeric-campaign.v1':
        raise ValueError('unknown campaign schema')
    if campaign.get('diagnostic_modes', {}).get('pass1_probe_stage') != 'dot0':
        raise ValueError('expected dot0 probe, not a normal Pass 1 output')
    if campaign.get('diagnostic_modes', {}).get('pass11_bounds_guard') is not True:
        raise ValueError('Pass11 guard must remain enabled')
    result = {}
    for case in campaign['cases']:
        key = (case['seed'], case['pass_name'], case['repeat'])
        if key in result or case.get('error'):
            raise ValueError('duplicate or failed campaign case')
        result[key] = case
    return result


def snapshot(case: dict) -> np.ndarray:
    desc = case['scratch']['ordinary']
    path = Path(desc['path'])
    if not path.is_file() or path.stat().st_size != SCRATCH_SIZE:
        raise ValueError(f'invalid or missing scratch: {path}')
    if hash_file(path) != desc['sha256']:
        raise ValueError(f'SHA mismatch: {path}')
    return np.memmap(path, dtype='u1', mode='r')


def pack_bytes(data: np.ndarray) -> int:
    result = 0
    for i, v in enumerate(np.asarray(data, dtype=np.uint8)):
        result |= int(v) << (8 * i)
    return result


def signed_bytes(word: int) -> list[int]:
    return [(((word >> (8 * i)) & 255) - 256 if ((word >> (8 * i)) & 128) else ((word >> (8 * i)) & 255)) for i in range(4)]


def dot_signed(a: int, b: int, acc: int) -> int:
    return acc + sum(x * y for x, y in zip(signed_bytes(a), signed_bytes(b)))


def first_valid_kernel(x: int, y: int) -> tuple[int, int, int, int]:
    for ky in range(3):
        yy = y + ky - 1
        for kx in range(3):
            xx = x + kx - 1
            if 0 <= yy < 540 and 0 <= xx < 960:
                return ky, kx, yy, xx
    raise ValueError('no valid kernel location')


def run_report(scalar_campaign: Path, candidate_campaign: Path, model_path: Path, samples: int) -> dict:
    model = load_model(model_path)
    left = json.loads(scalar_campaign.read_text(encoding='utf-8'))
    right = json.loads(candidate_campaign.read_text(encoding='utf-8'))
    lcases, rcases = case_index(left), case_index(right)
    if set(lcases) != set(rcases):
        raise ValueError('campaign matrices do not match')
    if left['sequence_file_sha256'] != right['sequence_file_sha256'] or left['source_commit'] != right['source_commit']:
        raise ValueError('different sequence or pinned source')
    if left['trace_frame'] != right['trace_frame']:
        raise ValueError('different trace frame')
    coords = sample_coordinates(samples)
    totals = {'scalar': {'operand_mismatch': 0, 'result_mismatch': 0},
              'candidate': {'operand_mismatch': 0, 'result_mismatch': 0}}
    examples = []
    actual = 0
    for key in sorted(lcases):
        if key[1] != 'pass_01':
            continue
        lzero = lcases[(key[0], 'pass_00', key[2])]
        rzero = rcases[(key[0], 'pass_00', key[2])]
        input_left, input_right = snapshot(lzero), snapshot(rzero)
        if not np.array_equal(input_left[:OUTPUT_OFFSET], input_right[:OUTPUT_OFFSET]):
            raise ValueError('unaligned Pass0 tensor inputs')
        out_l, out_r = snapshot(lcases[key]), snapshot(rcases[key])
        inp = input_left[:OUTPUT_OFFSET].view(np.int8).reshape(540,960,16)
        for x,y in coords:
            ky,kx,iy,ix=first_valid_kernel(x,y)
            expected_a=pack_bytes(inp[iy,ix,0:4])
            expected_b=pack_bytes(model.w0[0,ky,kx,0:4])
            expected_acc=0 # FP16 bias variant first convolution initial accumulator
            expected_result=dot_signed(expected_a,expected_b,expected_acc)
            pixel_offset=OUTPUT_OFFSET+(y*960+x)*16
            for label,mem in [('scalar',out_l),('candidate',out_r)]:
                got=np.frombuffer(mem[pixel_offset:pixel_offset+16],dtype='<u4',count=4)
                ga,gb,gacc,gresult=[int(v) for v in got]
                result_signed=gresult - (1 << 32) if gresult >= (1 << 31) else gresult
                mismatch=(ga!=expected_a or gb!=expected_b or gacc!=expected_acc)
                totals[label]['operand_mismatch']+=int(mismatch)
                totals[label]['result_mismatch']+=int(result_signed!=expected_result)
                if (mismatch or result_signed!=expected_result) and len(examples)<20:
                    examples.append({'mode':label,'x':x,'y':y,'ky':ky,'kx':kx,
                                     'expected_a':hex(expected_a),'got_a':hex(ga),
                                     'expected_b':hex(expected_b),'got_b':hex(gb),
                                     'expected_acc':expected_acc,'got_acc':gacc,
                                     'expected_result':expected_result,'got_result':result_signed})
            actual+=1
    if actual==0:
        raise ValueError('no paired Pass1 cases')
    if totals['scalar']['operand_mismatch'] or totals['scalar']['result_mismatch']:
        raise ValueError('scalar dot0 trace does not match CPU; cannot use it as oracle')
    return {'schema':'f4n10.pass1-dot0-oracle.v1',
            'source_sha256':model.source_sha256,
            'sequence_file_sha256':left['sequence_file_sha256'],
            'checked_pixels':actual,
            'candidate_mode':right['diagnostic_modes'].get('pass1_dot4_experiment',''),
            'comparisons':totals,
            'candidate_matched':not any(totals['candidate'].values()),
            'examples':examples,
            'note':'A matching first DOT4 cannot prove the full fused Pass1 is correct.'}


def main()->int:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--scalar-campaign',type=Path,required=True)
    ap.add_argument('--candidate-campaign',type=Path,required=True)
    ap.add_argument('--source',type=Path,default=MODEL)
    ap.add_argument('--samples',type=int,default=128)
    ap.add_argument('--output',type=Path,required=True)
    a=ap.parse_args()
    if a.samples < 18:
        ap.error('require at least 18 samples covering deterministic edges')
    doc=run_report(a.scalar_campaign,a.candidate_campaign,a.source,a.samples)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(doc,indent=2)+'\n',encoding='utf-8')
    print(f"First DOT4 candidate matched: {doc['candidate_matched']}, {doc['checked_pixels']} samples")
    return 0 if doc['candidate_matched'] else 3

if __name__=='__main__':
    raise SystemExit(main())
