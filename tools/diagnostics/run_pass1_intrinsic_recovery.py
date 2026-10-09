#!/usr/bin/env python3
"""Automated Windows/Navi10 Pass1 native-DP4A recovery matrix.

Requires VS C++ environment already initialized (PowerShell launcher does it).
All CMake settings for this experiment are opt-in and build-local.
No branch creation, Git mutation, production rollout, or quality claims.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import traceback
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/'third_party/fidelityfx-fsr4-source/Kits/FidelityFX/upscalers/fsr4/internal/shaders/fsr4_model_v07_i8_native/passes_1080.hlsl'
VARIANTS=('native','native_zero','native_swap','native_swap_zero','unpack_dot','unpack_scalar','unsigned_bias_3dot')
CODES={'scalar':'s','native':'n','native_zero':'z','native_swap':'w',
       'native_swap_zero':'x','unpack_dot':'u','unpack_scalar':'e','unsigned_bias_3dot':'b'}
STAGE_CODES={'dot0':'d','acc0_0':'a','final':'f','full':'p'}


def sha(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for part in iter(lambda:f.read(1024*1024), b''):
            h.update(part)
    return h.hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8-sig'))


def command(cmd: list[str],log_dir:Path, name:str, cwd:Path, env:dict|None=None, timeout:int=3600)->dict:
    log_dir.mkdir(parents=True,exist_ok=True)
    print(f'[{name}] '+ ' '.join(cmd),flush=True)
    result={'name':name,'command':cmd,'passed':False}
    try:
        p=subprocess.run(cmd,cwd=cwd,env=env,text=True,capture_output=True,
                         errors='replace',timeout=timeout,check=False)
        (log_dir/f'{name}.stdout.txt').write_text(p.stdout,encoding='utf-8')
        (log_dir/f'{name}.stderr.txt').write_text(p.stderr,encoding='utf-8')
        result.update({'exit_code':p.returncode,'passed':p.returncode==0,
                       'stdout':str(log_dir/f'{name}.stdout.txt'),
                       'stderr':str(log_dir/f'{name}.stderr.txt')})
    except (subprocess.TimeoutExpired,OSError) as exc:
        result['error']=str(exc)
    return result


def build_variant(repo:Path, output:Path, mode:str, stage:str,python:str)->tuple[Path,list[dict]]:
    code=CODES[mode]+STAGE_CODES[stage]
    build=output/code
    env=os.environ.copy()
    for key in ('MLSR-WMMA','MLSR-WATERMARK'):
        env.pop(key,None)
    experiment=mode if mode not in ('scalar','native') else ''
    flags=[
        f'-DPython3_EXECUTABLE:FILEPATH={python}',
        '-DCMAKE_BUILD_TYPE=Release',
        '-DFSR4N10_PASS11_BOUNDS_GUARD=ON',
        '-DFSR4N10_FORCE_GLOBAL_UAV_BARRIER=OFF',
        '-DFSR4N10_ENABLE_PASS_PREFIX_DIAGNOSTIC='+('OFF' if stage=='full' else 'ON'),
        '-DFSR4N10_STABLE_POST_MATH=OFF',
        '-DFSR4N10_FORCE_SCALAR_DOT4='+('ON' if mode=='scalar' else 'OFF'),
        '-DFSR4N10_SCALAR_DOT4_PASS_SET=',
        '-DFSR4N10_PASS1_DOT4_EXPERIMENT='+experiment,
        '-DFSR4N10_PASS1_PROBE_STAGE='+('' if stage in ('final','full') else stage),
    ]
    logs=output/'logs'
    c=command(['cmake','-S',str(repo),'-B',str(build),'-G','Ninja',*flags],logs,f'cfg{code}',repo,env)
    if not c['passed']:
        raise RuntimeError(f'CMake configure failed for {mode}/{stage}: {c}')
    b=command(['cmake','--build',str(build),'--config','Release','--target','fsr4n10_harness'],
              logs,f'bld{code}',repo,env,timeout=3600)
    if not b['passed']:
        raise RuntimeError(f'Build failed for {mode}/{stage}: {b}')
    exe=build/'fsr4n10_harness.exe'
    if not exe.is_file():
        raise RuntimeError(f'missing D3D12 harness: {exe}')
    manifest=build/'teacher/provider_i8_native_1080/manifest.json'
    modes=read(manifest)['diagnostic_modes']
    if (modes.get('pass1_dot4_experiment','')!=experiment or
        modes.get('pass1_probe_stage','')!=('' if stage in ('final','full') else stage) or
        modes.get('pass11_bounds_guard') is not True or
        modes.get('scalar_dot4') is not (mode=='scalar')):
        raise RuntimeError(f'provider manifest mismatch: {mode}/{stage}: {modes}')
    return exe,[c,b]


def run_prefix(repo:Path,sequence:Path,output:Path,mode:str,stage:str,
               python:str,frame:int,repeats:int)->tuple[Path,list[dict]]:
    exe,steps=build_variant(repo,output,mode,stage,python)
    code=CODES[mode]+STAGE_CODES[stage]
    campaign=output/('c'+code)
    cmd=[python,str(repo/'tools/diagnostics/run_i8_numeric_bisector.py'),
         '--harness',str(exe),'--sequence',str(sequence),'--output',str(campaign),
         '--variant',f'{mode}-{stage}',
         '--arithmetic','scalar' if mode=='scalar' else 'intrinsic',
         '--stages','0','1','--seeds','zero','--repeats',str(repeats),
         '--trace-frame',str(frame)]
    done=command(cmd,output/'logs',f'camp{code}',repo,timeout=1800)
    steps.append(done)
    if not done['passed'] or not (campaign/'campaign.json').is_file():
        raise RuntimeError(f'GPU prefix campaign failed: {mode}/{stage}: {done}')
    return campaign/'campaign.json',steps


def strict_gold(report:dict,stage:str)->bool:
    if report.get('stage')!=stage or not report.get('pass0_inputs_equal'):
        return False
    truth=report.get('comparisons',{}).get('scalar',{})
    candidate=report.get('comparisons',{}).get('intrinsic',{})
    if truth.get('exact_lanes')!=truth.get('total') or not truth.get('total'):
        return False
    if stage in ('acc0_0','final'):
        return candidate.get('exact_lanes')==candidate.get('total') and bool(candidate.get('total'))
    return False


def run_experiment(repo:Path,sequence:Path,output:Path,variants:tuple[str,...],
                   python:str,frame:int,repeats:int,samples:int)->dict:
    report={'schema':'f4n10.pass1-native-lowering-campaign.v1',
            'baseline_commit':'3ed1c9a53b779382d466f6b95ef26d9d14536965',
            'repository':str(repo),'sequence':str(sequence),'sequence_sha256':sha(sequence),
            'variants':{},'production_approved':False,'notes':[]}
    output.mkdir(parents=True,exist_ok=True)
    # Ground the likely 256-step error signature in the actual Pass0 data and
    # original model weights before evaluating codegen workarounds.
    oracle_dir=repo/'artifacts/results/pass1-golden'
    sign_report=output/'signedness_inference.json'
    signedness=command([
        python,str(repo/'tools/diagnostics/infer_pass1_signedness.py'),
        '--oracles',str(oracle_dir),'--source',str(SOURCE),
        '--samples',str(samples),'--output',str(sign_report)],
        output/'logs','signedness',repo)
    report['signedness_inference']={'execution':signedness,
        'report':str(sign_report),
        'result':read(sign_report) if sign_report.is_file() else None}
    def checkpoint():
        (output/'summary.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    # Reference captures are shared across candidate tests, preventing
    # accidental acceptance based on moving or variant-specific baselines.
    refs={}
    for stage in ('dot0','acc0_0','final'):
        try:
            refs[stage],steps=run_prefix(repo,sequence,output,'scalar',stage,python,frame,repeats)
            report['variants'][f'scalar:{stage}']={'campaign':str(refs[stage]),'steps':steps,'passed':True}
        except Exception as exc:
            report['variants'][f'scalar:{stage}']={'passed':False,'error':str(exc)}
            checkpoint()
            raise
        checkpoint()
    survivors=[]
    for mode in variants:
        item={'variant':mode,'stages':{},'o0':None,'eligible_for_full_o0':False}
        report['variants'][mode]=item
        for stage in ('dot0','acc0_0','final'):
            try:
                campaign,steps=run_prefix(repo,sequence,output,mode,stage,python,frame,repeats)
                oracle_path=output/f'{mode}_{stage}_oracle.json'
                if stage=='dot0':
                    verify=[python,str(repo/'tools/diagnostics/compare_pass1_dot0.py'),
                            '--scalar-campaign',str(refs[stage]),
                            '--candidate-campaign',str(campaign),
                            '--source',str(SOURCE),'--samples',str(samples),
                            '--output',str(oracle_path)]
                else:
                    verify=[python,str(repo/'tools/diagnostics/pass1_golden.py'),
                            '--source',str(SOURCE),
                            '--scalar-campaign',str(refs[stage]),
                            '--intrinsic-campaign',str(campaign),
                            '--stage',stage,'--samples',str(samples),
                            '--output',str(oracle_path)]
                ostep=command(verify,output/'logs',f'cmp{CODES[mode]}{STAGE_CODES[stage]}',repo)
                doc=read(oracle_path) if oracle_path.exists() else {}
                passed=(bool(doc.get('candidate_matched')) if stage=='dot0'
                        else strict_gold(doc,stage))
                item['stages'][stage]={'passed':passed,'oracle':str(oracle_path),
                                       'compared':doc.get('checked_pixels',doc.get('sample_count',0)),
                                       'steps':steps+[ostep]}
                checkpoint()
                if not passed:
                    break
            except Exception as exc:
                item['stages'][stage]={'passed':False,'error':str(exc)}
                checkpoint()
                break
        eligible=all(item['stages'].get(s,{}).get('passed') for s in ('dot0','acc0_0','final'))
        item['eligible_for_full_o0']=eligible
        if not eligible:
            continue
        # Full O0 (8-frame replay) is executed only after three independent
        # probe stages match the scalar+CPU arithmetic, not before.
        try:
            exe,steps=build_variant(repo,output,mode,'full',python)
            cmd=[python,str(repo/'tools/diagnostics/run_guarded_o0.py'),
                 '--repo',str(repo),'--harness',str(exe),'--sequence',str(sequence),
                 '--output',str(output/f'o0_{mode}'),'--arithmetic','intrinsic']
            gate=command(cmd,output/'logs',f'o0{CODES[mode]}',repo,timeout=7200)
            gate_path=output/f'o0_{mode}'/'summary.json'
            gate_doc=read(gate_path) if gate_path.exists() else {}
            item['o0']={'passed':gate['passed'] and gate_doc.get('required_steps_all_passed') is True,
                        'summary':str(gate_path),'steps':steps+[gate]}
            if item['o0']['passed']:
                survivors.append(mode)
        except Exception as exc:
            item['o0']={'passed':False,'error':str(exc)}
        checkpoint()
    report['o0_passing_experiments']=survivors
    report['notes'].append('Synthetic O0 is not proof of AMD reference, visual quality or game readiness.')
    report['notes'].append('ISA/disassembly and performance must be checked before any candidate can replace default DOT4.')
    checkpoint()
    return report


def main()->int:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--repo',type=Path,default=ROOT)
    ap.add_argument('--sequence',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--variants',nargs='+',choices=VARIANTS,default=list(VARIANTS))
    ap.add_argument('--frame',type=int,default=0)
    ap.add_argument('--repeats',type=int,default=2)
    ap.add_argument('--samples',type=int,default=128)
    args=ap.parse_args()
    if args.samples<18 or args.repeats<2 or args.frame<0:
        ap.error('samples>=18, repeats>=2, frame>=0 required')
    repo,sequence,output=(x.resolve() for x in (args.repo,args.sequence,args.output))
    if repo!=ROOT or not sequence.is_file():
        ap.error('repository must be this installed project and sequence must exist')
    doc=run_experiment(repo,sequence,output,tuple(args.variants),sys.executable,
                       args.frame,args.repeats,args.samples)
    print('Native-Pass1 candidates passing existing synthetic O0:',doc['o0_passing_experiments'])
    return 0 if doc['o0_passing_experiments'] else 3

if __name__=='__main__':
    try:
        raise SystemExit(main())
    except (OSError,ValueError,RuntimeError) as err:
        print('Pass1 native lowering campaign failed:',err,file=sys.stderr)
        raise SystemExit(2)
