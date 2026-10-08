#!/usr/bin/env python3
"""Independent CPU oracle for the pinned FSR4 v07 I8 Native/1080 Pass 1.

It reads ORIGINAL AMD Pass 1 constants and actual Pass 0 GPU scratch. It does
not call either the intrinsic or scalar shader for its expected values.

Reference is deliberately limited to the second (FP16 bias) ConvNextBlock
specialization used by Pass 1; fail closed if the source contract changes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

PASS1_BEGIN = '#ifdef MLSR_PASS_1'
PASS1_END = '#endif // #ifdef MLSR_PASS_1'
PASS1_DIMS = (960, 540, 16)


@dataclass(frozen=True)
class Tensor:
    name: str
    logical_size: tuple[int, ...]
    byte_strides: tuple[int, ...]
    quant_scale: float | None
    offset: int


@dataclass
class Model:
    source_sha256: str
    input_tensor: Tensor
    output_tensor: Tensor
    w0: np.ndarray
    b0: np.ndarray
    w1: np.ndarray
    b1: np.ndarray
    w2: np.ndarray
    b2: np.ndarray
    weight_scales: tuple[float, float, float]
    transform_scales: tuple[float, float, float, float]


def _strip_comments(s: str) -> str:
    return re.sub(r'/\*.*?\*/|//[^\n]*', '', s, flags=re.S)


def section_for_pass1(source: str) -> str:
    matches = list(re.finditer(r'(?m)^\s*#ifdef MLSR_PASS_1\s*$', source))
    if len(matches) != 1:
        raise ValueError('Expected exactly one MLSR_PASS_1 section')
    end = source.find(PASS1_END, matches[0].end())
    if end < 0:
        raise ValueError('Pass 1 section closing marker missing')
    part = source[matches[0].end():end]
    if len(re.findall(r'(?m)^\s*ConvNextBlock\(', part)) != 1:
        raise ValueError('Pass 1 no longer contains exactly one ConvNextBlock invocation')
    return part


def _call_args(block: str) -> list[str]:
    call = re.search(r'(?m)^\s*ConvNextBlock\(([^;]+)\);', block)
    if not call:
        raise ValueError('Pass 1 call missing')
    args = [arg.strip() for arg in call.group(1).split(',')]
    if len(args) != 13:
        raise ValueError(f'ConvNextBlock call changed: expected 13 arguments, got {len(args)}')
    if args[-1] != 'computeShaderParams':
        raise ValueError('Unexpected compute shader parameter at final call argument')
    return args


def _integer_vector(values: str, dim: int, name: str) -> tuple[int, ...]:
    fields = [value.strip() for value in values.split(',')]
    if len(fields) != dim or any(not re.fullmatch(r'[+-]?\d+', value) for value in fields):
        raise ValueError(f'{name}: expected {dim} literal integer components')
    return tuple(int(value) for value in fields)


def _initializer_fields(body: str) -> list[str]:
    text = _strip_comments(body)
    fields = []
    start = 0
    depth = 0
    for index, char in enumerate(text):
        if char == '(':
            depth += 1
        elif char == ')':
            depth -= 1
            if depth < 0:
                raise ValueError('unbalanced tensor initializer')
        elif char == ',' and depth == 0:
            fields.append(text[start:index].strip())
            start = index + 1
    if depth != 0:
        raise ValueError('unbalanced tensor initializer')
    fields.append(text[start:].strip())
    return fields


def _vector_expression(block: str, expression: str, dim: int, name: str) -> tuple[int, ...]:
    literal = re.fullmatch(r'(?:u?int)' + str(dim) + r'\s*\(([^)]*)\)', expression.strip())
    if literal:
        return _integer_vector(literal.group(1), dim, name)
    reference = re.fullmatch(r'[A-Za-z_]\w*', expression.strip())
    if not reference:
        raise ValueError(f'{name}: unsupported vector expression {expression!r}')
    identifier = reference.group(0)
    declarations = re.findall(
        r'\bconst\s+(?:u?int)' + str(dim) + r'\s+' + re.escape(identifier) +
        r'\s*=\s*(?:u?int)' + str(dim) + r'\s*\(([^)]*)\)\s*;', block)
    if len(declarations) != 1:
        raise ValueError(f'{name}: expected one literal vector declaration for {identifier}')
    return _integer_vector(declarations[0], dim, identifier)


def _descriptor_vector(block: str, body: str, field: str, dim: int) -> tuple[int, ...]:
    comment = r'\s*,\s*//\s*' + re.escape(field) + r'\b'
    literal = re.search(r'\b(?:u?int)' + str(dim) + r'\s*\(([^)]*)\)' + comment, body)
    if literal:
        return _integer_vector(literal.group(1), dim, field)

    reference = re.search(r'\b([A-Za-z_]\w*)\s*' + comment, body)
    if reference:
        return _vector_expression(block, reference.group(1), dim, field)

    # Pinned generated model outputs may initialize all descriptor members in
    # one comma-separated expression without per-member comments.
    fields = _initializer_fields(body)
    field_index = {'logicalSize': 0, 'storageByteStrides': 4}.get(field)
    if field_index is None or field_index >= len(fields):
        raise ValueError(f'{field}: descriptor field missing')
    return _vector_expression(block, fields[field_index], dim, field)


def _descriptor(block: str, name: str, kind: str) -> Tensor:
    regex = (r'\bconst\s+' + re.escape(kind) + r'\s*<[^;=]+>\s+' +
             re.escape(name) + r'\s*=\s*\{(?P<body>.*?)\};')
    m = re.search(regex, block, flags=re.S)
    if not m:
        raise ValueError(f'Pass 1 tensor declaration missing: {kind} {name}')
    body = m.group('body')
    dim = 4 if 'Tensor4' in kind else 3 if 'Tensor3' in kind else 1
    if dim > 1:
        logical_size = _descriptor_vector(block, body, 'logicalSize', dim)
        byte_strides = _descriptor_vector(block, body, 'storageByteStrides', dim)
    else:
        logical_size = (int(re.search(r'^\s*(\d+),\s*// logicalSize', body, re.M).group(1)),)
        byte_strides = (int(re.search(r'^\s*(\d+),\s*// storageByteStrides', body, re.M).group(1)),)
    offset_m = re.search(r'(?:\+\s*)?(\d+),\s*// threadGroupStorageByteOffset', body)
    offset = int(offset_m.group(1)) if offset_m else 0
    if re.search(r'threadGroupByteOffsetInTensor_\w+\s*\+\s*(\d+)', body):
        offset = int(re.search(r'threadGroupByteOffsetInTensor_\w+\s*\+\s*(\d+)', body).group(1))
    quant_scale = None
    if kind.startswith('Quantized'):
        # Use the descriptor field, rather than a trailing-number regex that
        # could mistake quantizationScale_slice_2 for the value 2.
        fields = _initializer_fields(body)
        if len(fields) <= 8:
            raise ValueError(f'{name}: quantization scale field is missing')
        scale_expr = fields[8]
        if re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?', scale_expr):
            quant_scale = float(scale_expr)
        else:
            named_m = re.fullmatch(r'[A-Za-z_]\w*', scale_expr)
            if not named_m:
                raise ValueError(f'{name}: unknown quantization scale format')
            n = named_m.group(0)
            declared = re.search(r'\bconst float\s+'+re.escape(n)+r'\s*=\s*([^;]+);', block)
            if not declared:
                raise ValueError(f'{name}: missing quantization scale {n}')
            quant_scale = float(declared.group(1).strip())
    return Tensor(name, logical_size, byte_strides, quant_scale, offset)


def _dwords(block: str, name: str) -> np.ndarray:
    pattern = r'\bstatic\s+const\s+uint\s+' + re.escape(name) + r'_dwords\[(\d+)\]\s*=\s*\{(.*?)\};'
    m = re.search(pattern, block, flags=re.S)
    if not m:
        raise ValueError(f'missing embedded model constants for {name}')
    n = int(m.group(1))
    tokens = re.findall(r'\b(?:0[xX][0-9a-fA-F]+|\d+)\b', _strip_comments(m.group(2)))
    if len(tokens) != n:
        raise ValueError(f'{name}: {len(tokens)} constants, expected {n}')
    return np.asarray([int(token,0) for token in tokens], dtype='<u4')


def load_model(path: Path) -> Model:
    contents = path.read_bytes()
    block = section_for_pass1(contents.decode('utf-8-sig').replace('\r\n','\n'))
    args = _call_args(block)
    scales = tuple(float(x) for x in args[:4])
    in_t = _descriptor(block, args[4], 'QuantizedTensor3i8_NHWC')
    out_t = _descriptor(block, args[11], 'QuantizedTensor3i8_NHWC')
    wnames = [args[5], args[7], args[9]]
    bnames = [args[6], args[8], args[10]]
    weights = []
    biases = []
    wscale = []
    for wname, bname in zip(wnames, bnames):
        wt = _descriptor(block,wname,'QuantizedTensor4i8_NHWC')
        bt = _descriptor(block,bname,'Tensor1h')
        raww = _dwords(block,wname).tobytes()
        rawb = _dwords(block,bname).tobytes()
        width, height, cin, cout = wt.logical_size
        if width*height*cin*cout > len(raww):
            raise ValueError(f'{wname} too little weight data')
        if tuple(wt.byte_strides) != (cin, width*cin, 1, width*height*cin):
            raise ValueError(f'{wname} weight strides not recognized: {wt.byte_strides}')
        arr = np.frombuffer(raww, dtype=np.int8,count=width*height*cin*cout)
        weights.append(arr.reshape(cout,height,width,cin).astype(np.int64))
        if bt.logical_size != (cout,) or bt.byte_strides != (2,):
            raise ValueError(f'{bname} unsupported half bias contract')
        biases.append(np.frombuffer(rawb,dtype='<f2',count=cout).astype(np.float64))
        wscale.append(float(wt.quant_scale))
    if (in_t.logical_size != PASS1_DIMS or out_t.logical_size != PASS1_DIMS or
        in_t.byte_strides != (16,15360,1) or out_t.byte_strides != (16,15360,1) or
        in_t.offset != 0 or out_t.offset != 8294400):
        raise ValueError(f'Native/1080 Pass 1 tensor geometry changed: {in_t} -> {out_t}')
    if [x.shape for x in weights] != [(16,3,3,16),(32,1,1,16),(16,1,1,32)]:
        raise ValueError(f'ConvNextBlock model topology changed: {[x.shape for x in weights]}')
    if out_t.quant_scale is None or in_t.quant_scale is None:
        raise ValueError('input/output quantization scale missing')
    return Model(hashlib.sha256(contents).hexdigest(),in_t,out_t,
                 weights[0],biases[0],weights[1][:,0,0,:],biases[1],
                 weights[2][:,0,0,:],biases[2],tuple(wscale),scales)


def quantize(v: np.ndarray, low: int, high: int, floating: str) -> np.ndarray:
    if floating == 'float32':
        x = np.asarray(v,dtype=np.float32)
    elif floating == 'float64':
        x = np.asarray(v,dtype=np.float64)
    else:
        raise ValueError(f'unknown floating mode {floating}')
    # HLSL round: near ties are a compiler/ISA question, therefore report both
    # exact and within-one-LSB agreement; raw INT32 stages are authoritative.
    return np.clip(np.rint(x),low,high).astype(np.int64)


def reference_at(model: Model, input_tensor: np.ndarray, x: int, y: int,
                 *, floating: str = 'float64') -> dict[str,np.ndarray]:
    width,height,channels = model.input_tensor.logical_size
    if x < 0 or y < 0 or x >= width or y >= height:
        raise ValueError(f'pixel ({x},{y}) out of range')
    t = np.float32 if floating == 'float32' else np.float64
    input_scale = t(model.input_tensor.quant_scale)
    output_rcp = t(1.0)/t(model.output_tensor.quant_scale)
    s0,s1,s2,s3 = (t(v) for v in model.transform_scales)
    ws0,ws1,ws2 = (t(v) for v in model.weight_scales)
    acc0=np.zeros((16,),dtype=np.int64)
    for ky in range(3):
        sy=y+ky-1
        if not (0 <= sy < height):
            continue
        for kx in range(3):
            sx=x+kx-1
            if not (0 <= sx < width):
                continue
            acc0 += model.w0[:,ky,kx,:] @ input_tensor[sy,sx,:].astype(np.int64)
    # Preserve the expression grouping of AMD's FP16-bias overload.
    conv0_quant = quantize(
        (acc0.astype(t) * (input_scale*ws0) + model.b0.astype(t)) * s0,
        -128,127,floating)
    acc1 = model.w1 @ conv0_quant
    conv1_quant = quantize(
        (acc1.astype(t) * (s1*ws1) + model.b1.astype(t)) * s2,
        0,127,floating)
    acc2=model.w2 @ conv1_quant
    final = quantize(
        (acc2.astype(t) * (ws2*s3) + model.b2.astype(t) +
         input_tensor[y,x,:].astype(t)*input_scale)*output_rcp,
         -128,127,floating)
    return {'acc0':acc0,'q0':conv0_quant,'acc1':acc1,'q1':conv1_quant,
            'acc2':acc2,'final':final}


def expected_for_stage(stages: dict[str,np.ndarray],stage: str) -> np.ndarray:
    if stage in {'q0','final'}:
        return stages[stage].astype(np.int8)
    if stage in {'q1lo','q1hi'}:
        return stages['q1'][(0 if stage=='q1lo' else 16):(16 if stage=='q1lo' else 32)].astype(np.int8)
    m=re.fullmatch(r'acc([012])_([0-7])',stage)
    if m:
        key='acc'+m.group(1)
        k=int(m.group(2))
        if k>=len(stages[key])//4:
            raise ValueError(f'out-of-range stage {stage}')
        return stages[key][k*4:k*4+4].astype('<i4')
    raise ValueError(f'unsupported stage {stage}')


def scratch_views(path: Path, model: Model, stage: str) -> tuple[np.memmap,np.memmap]:
    if not path.is_file() or path.stat().st_size < model.output_tensor.offset + 8294400:
        raise ValueError(f'scratch snapshot is missing/too short: {path}')
    inp=np.memmap(path,dtype=np.int8,mode='r',offset=model.input_tensor.offset,shape=(540,960,16))
    if stage.startswith('acc'):
        out=np.memmap(path,dtype='<i4',mode='r',offset=model.output_tensor.offset,shape=(540,960,4))
    else:
        out=np.memmap(path,dtype=np.int8,mode='r',offset=model.output_tensor.offset,shape=(540,960,16))
    return inp,out


def sample_coordinates(count: int,seed: int=20261008)->list[tuple[int,int]]:
    edge=[(0,0),(1,0),(2,0),(0,1),(1,1),(2,2),(16,16),(32,32),
          (100,100),(240,135),(480,270),(958,538),(959,539),(959,0),(0,539),
          (479,269),(719,539),(64,64)]
    seen=set(edge)
    rng=random.Random(seed)
    while len(edge)<count:
        xy=(rng.randrange(960),rng.randrange(540))
        if xy not in seen:
            seen.add(xy)
            edge.append(xy)
    return edge


def evaluate(model: Model, source_scalar: Path, output_scalar: Path,
             source_intrinsic: Path, output_intrinsic: Path,
             stage: str, sample_count: int) -> dict[str,Any]:
    si,_=scratch_views(source_scalar,model,'final')
    ni,_=scratch_views(source_intrinsic,model,'final')
    _,so=scratch_views(output_scalar,model,stage)
    _,no=scratch_views(output_intrinsic,model,stage)
    coords=sample_coordinates(sample_count)
    if not np.array_equal(si,ni):
        raise ValueError('Scalar/intrinsic Pass 0 input tensors differ; abort CPU comparison')
    outcomes={name:{'exact_lanes':0,'near_lanes':0,'total':0,'max_abs_error':0,
                    'bad_pixels':0} for name in ('scalar','intrinsic')}
    variants={name:[] for name in ('float32','float64')}
    examples=[]
    for x,y in coords:
        target32=expected_for_stage(reference_at(model,si,x,y,floating='float32'),stage)
        target64=expected_for_stage(reference_at(model,si,x,y,floating='float64'),stage)
        variants['float32'].append(target32.tolist())
        variants['float64'].append(target64.tolist())
        for name,gpu in [('scalar',so),('intrinsic',no)]:
            actual=np.asarray(gpu[y,x],dtype=np.int64)
            expected=np.asarray(target64,dtype=np.int64)
            delta=np.abs(actual-expected)
            k=outcomes[name]
            k['exact_lanes']+=int(np.count_nonzero(delta==0))
            k['near_lanes']+=int(np.count_nonzero(delta<=1))
            k['total']+=int(delta.size)
            k['max_abs_error']=max(k['max_abs_error'],int(delta.max(initial=0)))
            if np.any(delta>1):k['bad_pixels']+=1
        if len(examples)<12:
            examples.append({'x':x,'y':y,'cpu_float64':target64.tolist(),
                             'cpu_float32':target32.tolist(),
                             'scalar':np.asarray(so[y,x]).tolist(),
                             'intrinsic':np.asarray(no[y,x]).tolist()})
    for k in outcomes.values():
        k['exact_fraction']=k['exact_lanes']/max(1,k['total'])
        k['within_one_lsb_fraction']=k['near_lanes']/max(1,k['total'])
    s,n=outcomes['scalar'],outcomes['intrinsic']
    preference='undetermined'
    if (s['within_one_lsb_fraction']>=0.99 and
        n['within_one_lsb_fraction']<0.95):
        preference='scalar_matches_independent_cpu_oracle'
    elif (n['within_one_lsb_fraction']>=0.99 and
          s['within_one_lsb_fraction']<0.95):
        preference='intrinsic_matches_independent_cpu_oracle'
    elif s['within_one_lsb_fraction']>=0.99 and n['within_one_lsb_fraction']>=0.99:
        preference='both_close_to_cpu_oracle'
    return {
        'schema':'f4n10.pass1-independent-cpu-oracle.v1',
        'source_sha256':model.source_sha256,
        'pass1_input_quant_scale':model.input_tensor.quant_scale,
        'pass1_output_quant_scale':model.output_tensor.quant_scale,
        'stage':stage,'sample_count':len(coords),'pass0_inputs_equal':True,
        'comparisons':outcomes,'preference':preference,
        'examples':examples,
        'note':('CPU INT32 accumulators are mathematically exact. The float '
                'quantization path can differ by one LSB near rounding ties. '
                'This does NOT establish visual quality or production readiness.')
    }


def snapshot_from_campaign(path:Path,stage:int,seed='zero',repeat=1,context='ordinary')->Path:
    doc=json.loads(path.read_text(encoding='utf-8'))
    matches=[c for c in doc['cases'] if c.get('seed')==seed and c.get('pass')==stage and
             c.get('repeat')==repeat and c.get('error') is None]
    if len(matches)!=1:
        raise ValueError(f'{path}: expected one seed={seed} pass={stage} repeat={repeat}, got {len(matches)}')
    snapshots=matches[0].get('scratch') or matches[0].get('files')
    if not snapshots or context not in snapshots:
        raise ValueError(f'{path}: no {context} scratch snapshot for pass {stage}')
    return Path(snapshots[context]['path'])


def main()->int:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source',type=Path,required=True,help='Pinned passes_1080.hlsl')
    ap.add_argument('--scalar-campaign',type=Path,required=True)
    ap.add_argument('--intrinsic-campaign',type=Path,required=True)
    ap.add_argument('--stage',required=True,help='final,q0,q1lo,q1hi,acc0_0..3,acc1_0..7,acc2_0..3')
    ap.add_argument('--seed',default='zero')
    ap.add_argument('--repeat',type=int,default=1)
    ap.add_argument('--samples',type=int,default=128)
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    if args.samples<18 or args.samples>16384:
        ap.error('--samples must be 18..16384')
    model=load_model(args.source)
    sc0=snapshot_from_campaign(args.scalar_campaign,0,args.seed,args.repeat)
    sc1=snapshot_from_campaign(args.scalar_campaign,1,args.seed,args.repeat)
    in0=snapshot_from_campaign(args.intrinsic_campaign,0,args.seed,args.repeat)
    in1=snapshot_from_campaign(args.intrinsic_campaign,1,args.seed,args.repeat)
    doc=evaluate(model,sc0,sc1,in0,in1,args.stage,args.samples)
    doc['input_paths']={'scalar_pass0':str(sc0),'scalar_pass1':str(sc1),
                        'intrinsic_pass0':str(in0),'intrinsic_pass1':str(in1)}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(doc,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:doc[k] for k in ('stage','sample_count','comparisons','preference')},indent=2))
    return 0 if doc['preference']!='undetermined' else 2

if __name__=='__main__':
    try:raise SystemExit(main())
    except (ValueError,KeyError,OSError) as ex:
        print(f'pass1 CPU oracle: {ex}',file=sys.stderr)
        raise SystemExit(3)
