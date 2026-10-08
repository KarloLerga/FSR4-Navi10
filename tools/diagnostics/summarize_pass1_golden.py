#!/usr/bin/env python3
"""Summarize an independent Pass1 CPU-oracle sweep; never changes O0 gates."""
from __future__ import annotations
import argparse,json
from pathlib import Path

STAGE_ORDER=['acc0_0','acc0_1','acc0_2','acc0_3','q0',
             'acc1_0','acc1_1','acc1_2','acc1_3','acc1_4','acc1_5','acc1_6','acc1_7',
             'q1lo','q1hi','acc2_0','acc2_1','acc2_2','acc2_3','final']


def summarize(paths:list[Path])->dict:
    rows=[]
    for path in paths:
        d=json.loads(path.read_text(encoding='utf-8'))
        if d.get('schema')!='f4n10.pass1-independent-cpu-oracle.v1':
            raise ValueError(f'unexpected report schema at {path}')
        cmp=d['comparisons']
        rows.append({'stage':d['stage'],
                     'preference':d['preference'],
                     'scalar_within_one':cmp['scalar']['within_one_lsb_fraction'],
                     'intrinsic_within_one':cmp['intrinsic']['within_one_lsb_fraction'],
                     'scalar_max_error':cmp['scalar']['max_abs_error'],
                     'intrinsic_max_error':cmp['intrinsic']['max_abs_error'],
                     'source_sha256':d['source_sha256']})
    stage_seen=[r['stage'] for r in rows]
    if len(stage_seen)!=len(set(stage_seen)):
        raise ValueError('duplicate stage reports')
    if len({r['source_sha256'] for r in rows})!=1:
        raise ValueError('models differ between stage reports')
    rows.sort(key=lambda x:STAGE_ORDER.index(x['stage']))
    earliest=next((r for r in rows if abs(r['scalar_within_one']-r['intrinsic_within_one'])>0.1),None)
    conclusion='not_determined'
    if earliest:
        conclusion='arithmetic_path_diff_at_or_before_'+earliest['stage']
    acc0_complete=all('acc0_'+str(i) in stage_seen for i in range(4))
    if earliest and earliest['stage'].startswith('acc0_'):
        if acc0_complete:
            follow=('Raw pass0 accumulator divergence is already present. Inspect fused intrinsic operand packing, '
                    'register mapping, and generated ISA; standalone dot4 conformance does not isolate this context.')
        else:
            follow='Measure acc0_1..3 for full 16-channel convolution-zero accumulator coverage.'
    elif earliest and earliest['stage']=='q0' and acc0_complete:
        follow='All raw acc0 chunks match; inspect pass0 FP16 quantization and pack_clamp_s8 lowering.'
    elif earliest and earliest['stage'].startswith('acc1_'):
        follow='Pass0 matched through q0; inspect fused intrinsic operand packing and generated ISA at the first divergent acc1 chunk.'
    elif earliest and earliest['stage'].startswith('acc2_'):
        follow='Earlier stages matched; inspect fused intrinsic operand packing and generated ISA at the first divergent acc2 chunk.'
    elif earliest and earliest['stage'] in ('q1lo','q1hi'):
        follow='Raw acc1 chunks matched; inspect pass1 FP16 quantization and pack_clamp_s8 lowering.'
    elif earliest and earliest['stage']=='final':
        follow='Intermediate stages matched; inspect the final output transform and quantization path.'
    elif 'acc0_0' in stage_seen and not acc0_complete:
        follow='Measure acc0_1..3 for full 16-channel convolution-zero accumulator coverage.'
    elif 'q0' in stage_seen and acc0_complete:
        follow='Raw accumulator matches; inspect quantization/pack_clamp_s8 and floating-point lowering.'
    else:
        follow='Probe all INT32 stage chunks and quantized boundaries; verify against native hardware before concluding.'
    return {'schema':'f4n10.pass1-golden-summary.v1','source_sha256':rows[0]['source_sha256'],
            'rows':rows,'first_large_path_gap':earliest,'tentative_conclusion':conclusion,
            'next_action':follow,
            'quality_proven':False,'o0_production_approved':False,
            'caveat':'Model weights and math are independent, but shader rounding/FP16 lowering still requires corroboration.'}


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--reports',type=Path,nargs='+',required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    d=summarize(a.reports)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(d,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'conclusion':d['tentative_conclusion'],'next_action':d['next_action']},indent=2))
    return 0

if __name__=='__main__':raise SystemExit(main())
