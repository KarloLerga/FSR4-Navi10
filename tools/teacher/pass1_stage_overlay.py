#!/usr/bin/env python3
"""Build-local GPU stage taps for Native/1080 I8 Pass 1 ConvNextBlock.

Each stage writes EXACTLY the normal 16-byte/pixel Pass-1 output slice and
returns from that pixel's ConvNextBlock loop. No new UAV, no AMD vendor edits.
For INT32 stages the 16 bytes are four raw signed 32-bit accumulator values;
for quantized stages they are sixteen signed I8 values.

IMPORTANT: These shaders are NOT an image upscaler. Use only with
FSR4N10_LAST_MODEL_PASS=1 and scratch snapshot; POST RGB is meaningless.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

OPERATOR_REL = Path('dx12/ml2code_runtime/operators/int8_NHWC/Fused/ConvNextBlock.hlsli')
MODEL_REL = Path('internal/shaders/fsr4_model_v07_i8_native/passes_1080.hlsl')
OPERATOR_SHADOW = 'FSR4N10_CNV_PASS1_STAGE.hlsli'
MODEL_SHADOW = 'passes_1080.hlsl'
SENTINEL = 'FSR4N10_PASS1_STAGE_PROBE_V1'


def valid_stage(value: str) -> bool:
    if value in {'q0','q1lo','q1hi','dot0'}:
        return True
    m=re.fullmatch(r'acc([012])_([0-7])',value)
    if not m:
        return False
    step,index=int(m.group(1)),int(m.group(2))
    return index < (8 if step==1 else 4)


def _injection(stage: str) -> tuple[str,str]:
    if not valid_stage(stage):
        raise ValueError(f'invalid Pass1 diagnostic stage {stage}')
    if stage == 'dot0':
        # Stop at the first actually evaluated signed DOT4 in Pass1 ConvNextBlock.
        # Record input word, weight word, initial accumulator, and computed result.
        # The FP16-bias overload has a zero-initialized acc0. Output is NOT RGB.
        anchor='const uint4 weightsDwords = weights0.storage.Load4(weightsOffset);'
        snippet=f'''if (f == 0 && c == 0)
                            {{
                                const uint probeA = uint(vs[inputIndex]);
                                const uint probeB = weightsDwords.x;
                                const int probeAcc = accumulator[f];
                                const int probeResult = dot4add_i8packed(vs[inputIndex], weightsDwords.x, probeAcc);
                                output.storage.Store4(output.OffsetOf(poBase),
                                    uint4(probeA, probeB, asuint(probeAcc), asuint(probeResult)));
                                return;
                            }}'''
        return anchor, snippet
    if stage == 'q0':
        anchor='            // Second Convolution + Relu'
        values='uint4(conv_result[0], conv_result[1], conv_result[2], conv_result[3])'
        label='quantized convolution 0'
    elif stage in ('q1lo','q1hi'):
        anchor='            int conv3_output[16];'
        start=0 if stage=='q1lo' else 4
        values='uint4(' + ', '.join(f'relu_result[{j}]' for j in range(start,start+4)) + ')'
        label='quantized convolution 1'
    elif stage.startswith('acc0'):
        anchor='            int8_t4_packed conv_result[16/4];'
        i=int(stage.split('_')[1])*4
        values='asuint(int4(' + ', '.join(f'accumulator[{j}]' for j in range(i,i+4)) + '))'
        label='raw INT32 convolution 0 accumulator'
    elif stage.startswith('acc1'):
        anchor='            int8_t4_packed relu_result[32/4];'
        i=int(stage.split('_')[1])*4
        values='asuint(int4(' + ', '.join(f'relu_output[{j}]' for j in range(i,i+4)) + '))'
        label='raw INT32 convolution 1 accumulator'
    elif stage.startswith('acc2'):
        anchor='            // Add + store output'
        i=int(stage.split('_')[1])*4
        values='asuint(int4(' + ', '.join(f'conv3_output[{j}]' for j in range(i,i+4)) + '))'
        label='raw INT32 convolution 2 accumulator'
    else:
        raise AssertionError(stage)
    snippet = f'''            // {SENTINEL} {stage}: {label}.
            // Write 16B/pixel into the EXISTING pass-1 output tensor.
            {{
                const uint4 pass1Probe = {values};
                output.storage.Store4(output.OffsetOf(poBase), pass1Probe);
            }}
            continue;

'''
    return anchor,snippet


def guarded_operator(source: str,stage: str) -> str:
    if SENTINEL in source:
        raise ValueError('already instrumented Pass1 operator')
    marker='const Tensor1h<SB0> bias0,'
    matches=[m.start() for m in re.finditer(re.escape(marker),source)]
    if len(matches)!=1:
        raise ValueError(f'expected one FP16-bias ConvNextBlock overload, got {len(matches)}')
    start=source.rfind('template<typename SI',0,matches[0])
    stop=source.find('#if WMMA_ENABLED',matches[0])
    if start<0 or stop<0 or stop<=start:
        raise ValueError('cannot isolate non-WMMA FP16-bias ConvNextBlock overload')
    part=source[start:stop]
    if 'const QuantizedTensor3i8_NHWC<SI> input' not in part or 'int conv3_output[16]' not in part:
        raise ValueError('pass1 convolution source contract changed')
    anchor,insertion=_injection(stage)
    if part.count(anchor)!=1:
        raise ValueError(f'probe location changed for {stage}; count={part.count(anchor)}')
    part=part.replace(anchor,anchor+'\n                            '+insertion if stage == 'dot0' else insertion+anchor,1)
    return source[:start]+part+source[stop:]


def redirected_model(model: str) -> str:
    m=list(re.finditer(r'(?m)^\s*#ifdef MLSR_PASS_1\s*$',model))
    if len(m)!=1:
        raise ValueError('expected one Pass1 model section')
    stop=model.find('#endif // #ifdef MLSR_PASS_1',m[0].end())
    if stop<0:
        raise ValueError('missing Pass1 end directive')
    old='#include "ml2code_runtime/operators/int8_NHWC/Fused/ConvNextBlock.hlsli"'
    part=model[m[0].end():stop]
    if part.count(old)!=1:
        raise ValueError('unexpected Pass1 ConvNextBlock include count')
    part=part.replace(old,f'#include "{OPERATOR_SHADOW}"',1)
    return model[:m[0].end()]+part+model[stop:]


def create_overlay(fsr4_root:Path,output_dir:Path,stage:str,base_model:Path|None=None)->dict:
    if not valid_stage(stage):
        raise ValueError(f'unknown probe stage: {stage}')
    source=fsr4_root/OPERATOR_REL
    original_model=base_model if base_model is not None else fsr4_root/MODEL_REL
    if not source.is_file() or not original_model.is_file():
        raise FileNotFoundError('pinned Pass1 operator or model shadow missing')
    optext=source.read_text(encoding='utf-8-sig').replace('\r\n','\n')
    modeltext=original_model.read_text(encoding='utf-8-sig').replace('\r\n','\n')
    new_op=guarded_operator(optext,stage)
    new_model=redirected_model(modeltext)
    dest=output_dir/'capture_shader_overrides'
    dest.mkdir(parents=True,exist_ok=True)
    op_path=dest/OPERATOR_SHADOW
    model_path=dest/MODEL_SHADOW
    op_path.write_text(new_op,encoding='utf-8')
    model_path.write_text(new_model,encoding='utf-8')
    return {'stage':stage,'model_source':str(model_path),
            'operator_overlay':str(op_path),
            'operator_sha256':hashlib.sha256(new_op.encode('utf-8')).hexdigest(),
            'model_sha256':hashlib.sha256(new_model.encode('utf-8')).hexdigest(),
            'source_not_mutated':True}
