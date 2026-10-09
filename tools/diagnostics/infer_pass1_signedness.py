#!/usr/bin/env python3
"""Explain fused Pass1 acc0 intrinsic errors as signed/unsigned packed byte lanes.

Given the original pinned model, Pass0 scratch, and four intrinsic acc0_0..3
scratch captures, this tool calculates expected INT32 arithmetic under all
256 independent input/weight lane-sign masks (4 lanes per operand).

It does not infer hardware semantics from MOD256 alone: the winning mask must
predict all sampled 16-channel INT32 accumulators, exactly, or no conclusion.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools/diagnostics'))
from pass1_golden import load_model, sample_coordinates  # type: ignore # noqa: E402
SOURCE=ROOT/'third_party/fidelityfx-fsr4-source/Kits/FidelityFX/upscalers/fsr4/internal/shaders/fsr4_model_v07_i8_native/passes_1080.hlsl'
CHUNKS=4
SHAPE=(540,960,16)
OUTPUT_OFFSET=8_294_400
SCRATCH_BYTES=20_880_256


def memory(path:Path)->np.memmap:
    if not path.is_file() or path.stat().st_size!=SCRATCH_BYTES:
        raise ValueError(f'expected {SCRATCH_BYTES}-byte local GPU scratch file: {path}')
    return np.memmap(path,dtype='u1',mode='r')


def samples_from_oracles(root:Path,source:Path,count:int)->tuple[object,np.ndarray,np.ndarray,list]:
    model=load_model(source)
    docs=[json.loads((root/f'oracle-acc0_{i}.json').read_text(encoding='utf-8')) for i in range(CHUNKS)]
    for index,doc in enumerate(docs):
        if (doc.get('stage')!=f'acc0_{index}' or not doc.get('pass0_inputs_equal') or
            doc.get('source_sha256')!=model.source_sha256):
            raise ValueError(f'oracle-acc0_{index}.json does not match pinned model/inputs')
    base_path=Path(docs[0]['input_paths']['intrinsic_pass0'])
    inp=memory(base_path)[:OUTPUT_OFFSET].view('i1').reshape(SHAPE)
    outputs=[]
    for index,doc in enumerate(docs):
        path=Path(doc['input_paths']['intrinsic_pass1'])
        current_in=memory(Path(doc['input_paths']['intrinsic_pass0']))[:OUTPUT_OFFSET]
        if not np.array_equal(current_in,inp.view('u1').reshape(-1)):
            raise ValueError(f'Pass0 inputs differ between acc0_{index} builds')
        mem=memory(path)
        outputs.append(mem[OUTPUT_OFFSET:OUTPUT_OFFSET+OUTPUT_OFFSET].view('<i4').reshape(540,960,4))
    coords=sample_coordinates(count)
    observed=np.stack([np.concatenate([chunk[y,x] for chunk in outputs]).astype(np.int64)
                       for x,y in coords])
    return model,inp,observed,coords


def correction_features(w0:np.ndarray,inp:np.ndarray,coords:list[tuple[int,int]]):
    """Compute baseline signed INT32 plus analytic corrections for masks.

    A signed byte x reinterpreted as unsigned becomes x + 256*I(x<0).
    Thus product corrections are linear in each operand's sign mask, with
    a cross term 65536 when both signed operands were negative.
    """
    n=len(coords)
    base=np.zeros((n,16),dtype=np.int64)
    input_corr=np.zeros((n,16,4),dtype=np.int64)
    weight_corr=np.zeros((n,16,4),dtype=np.int64)
    cross_corr=np.zeros((n,16,4),dtype=np.int64)
    w0=np.asarray(w0,dtype=np.int64)
    if w0.shape!=(16,3,3,16):
        raise ValueError('expected original Pass1 16x3x3x16 signed-I8 weights')
    for i,(x,y) in enumerate(coords):
        if not (0<=x<960 and 0<=y<540):
            raise ValueError('Pass1 coordinate outside expected geometry')
        for ky in range(3):
            yy=y+ky-1
            if not (0<=yy<540):continue
            for kx in range(3):
                xx=x+kx-1
                if not (0<=xx<960):continue
                w=w0[:,ky,kx,:]
                a=np.asarray(inp[yy,xx,:],dtype=np.int64)
                base[i]+=w@a
                for lane in range(4):
                    z=np.arange(lane,16,4)
                    wl=w[:,z]
                    al=a[z]
                    am=(al<0).astype(np.int64)
                    wm=(wl<0).astype(np.int64)
                    input_corr[i,:,lane]+=256*(wl@am)
                    weight_corr[i,:,lane]+=256*(wm@al)
                    cross_corr[i,:,lane]+=65536*(wm@am)
    return base,input_corr,weight_corr,cross_corr


def evaluate_masks(base:np.ndarray,input_corr:np.ndarray,weight_corr:np.ndarray,
                   cross_corr:np.ndarray,observed:np.ndarray)->list[dict]:
    if base.shape!=observed.shape or input_corr.shape!=base.shape+(4,):
        raise ValueError('feature/observation shape mismatch')
    ranking=[]
    for imask in range(16):
        iu=np.array([(imask>>j)&1 for j in range(4)],dtype=np.int64)
        for wmask in range(16):
            wu=np.array([(wmask>>j)&1 for j in range(4)],dtype=np.int64)
            pred=(base+input_corr@iu+weight_corr@wu+cross_corr@(iu*wu))
            delta=pred-observed
            ranking.append({
                'input_unsigned_lane_mask':imask,
                'weight_unsigned_lane_mask':wmask,
                'exact_lanes':int(np.count_nonzero(delta==0)),
                'total_lanes':int(delta.size),
                'max_abs_error':int(np.abs(delta).max(initial=0)),
                'mean_abs_error':float(np.abs(delta).mean()),
            })
    ranking.sort(key=lambda r:(-r['exact_lanes'],r['mean_abs_error'],r['max_abs_error']))
    return ranking


def main()->int:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--oracles',type=Path,required=True,
                    help='artifacts/results/pass1-golden/ with oracle-acc0_0..3.json')
    ap.add_argument('--source',type=Path,default=SOURCE)
    ap.add_argument('--samples',type=int,default=128)
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    if args.samples<18 or args.samples>16384:
        ap.error('samples must be 18..16384')
    model,inp,actual,coords=samples_from_oracles(args.oracles,args.source,args.samples)
    base,ic,wc,cc=correction_features(model.w0,inp,coords)
    if not np.array_equal(base,base.astype(np.int32).astype(np.int64)):
        raise ValueError('unexpected INT32 overflow in CPU oracle')
    delta=actual-base
    ranking=evaluate_masks(base,ic,wc,cc,actual)
    winner=ranking[0]
    report={
        'schema':'f4n10.pass1-signedness-inference.v1',
        'source_sha256':model.source_sha256,
        'samples':len(coords),
        'channels':16,
        'acc0_mismatch_count':int(np.count_nonzero(delta)),
        'all_observed_acc0_errors_multiples_of_256':bool(np.all((delta%256)==0)),
        'observed_error_mod_256_histogram':{str(i):int(np.count_nonzero((delta%256)==i))
                                             for i in range(256) if np.any((delta%256)==i)},
        'winning_model':winner,
        'exact_signedness_model_found':winner['exact_lanes']==winner['total_lanes'],
        'top_models':ranking[:15],
        'interpretation':('Identified a global four-byte-lane sign mask consistent with all sampled output. '
                          'Still verify actual FFX_SC/DXIL operands and AMD reference before production.'
                          if winner['exact_lanes']==winner['total_lanes'] else
                          'No signed/unsigned lane mask explains all observations: investigate packing, '
                          'operand materialization, opcode lowering, or other source differences.'),
    }
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('all_observed_acc0_errors_multiples_of_256',
                                           'winning_model','exact_signedness_model_found')},indent=2))
    return 0 if report['exact_signedness_model_found'] else 3

if __name__=='__main__':
    try:raise SystemExit(main())
    except (OSError,KeyError,ValueError) as exc:
        print(f'signedness inference: {exc}',file=sys.stderr)
        raise SystemExit(2)
