from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools/diagnostics'))
sys.path.insert(0,str(ROOT/'tools/teacher'))
from pass1_golden import (Model, Tensor, load_model, reference_at, expected_for_stage,
                           sample_coordinates, quantize, scratch_views, evaluate,
                           _descriptor_vector, _descriptor)
from pass1_stage_overlay import (valid_stage,guarded_operator,redirected_model,
                                 create_overlay, OPERATOR_REL, MODEL_REL, SENTINEL)
from summarize_pass1_golden import summarize


def fake_model()->Model:
    w0=np.zeros((16,3,3,16),dtype=np.int64)
    w1=np.zeros((32,16),dtype=np.int64)
    w2=np.zeros((16,32),dtype=np.int64)
    for f in range(16):
        w0[f,1,1,f]=1
        w1[f,f]=1
        w2[f,f]=1
    return Model('synthetic-sha',Tensor('inp',(960,540,16),(16,15360,1),0.01,0),
                 Tensor('out',(960,540,16),(16,15360,1),0.01,8294400),
                 w0,np.zeros(16),w1,np.zeros(32),w2,np.zeros(16),
                 (1.,1.,1.),(100.,.01,100.,.01))


def fixture_shader(model:Model)->str:
    data=[]
    for name,arr,typ in [
        ('w0',model.w0,'int8'),('b0',model.b0,'half'),
        ('w1',model.w1,'int8'),('b1',model.b1,'half'),
        ('w2',model.w2,'int8'),('b2',model.b2,'half')]:
        if typ=='int8':raw=arr.astype(np.int8).tobytes()
        else:raw=arr.astype('<f2').tobytes()
        words=np.frombuffer(raw,dtype='<u4')
        data.append(f'static const uint {name}_dwords[{len(words)}] = {{'+','.join(hex(int(x)) for x in words)+'};')
    def t3(name,scale,offset):
        return f'''    const QuantizedTensor3i8_NHWC< RWBufferStorage > {name} = {{
        uint3(960, 540, 16), // logicalSize
        uint3(0,0,0), // threadGroupSliceStart
        uint3(960,540,16), // threadGroupSliceSize
        uint3(960,540,16), // storageSize
        uint3(16, 15360, 1), // storageByteStrides
        uint3(0,0,0), // paddingBegin
        uint3(0,0,0), // paddingEnd
        threadGroupByteOffsetInTensor_{name} + {offset}, {scale}, storage_{name} }};'''
    def t4(name,shape,scale):
        width,height,cin,cout=shape
        n=width*height*cin*cout//4
        return f'''    const QuantizedTensor4i8_NHWC< ConstantBufferStorage<{n}> > {name} = {{
            uint4({width}, {height}, {cin}, {cout}), // logicalSize
            uint4(0,0,0,0), // threadGroupSliceStart
            uint4({width},{height},{cin},{cout}), // threadGroupSliceSize
            uint4({width},{height},{cin},{cout}), // storageSize
            uint4({cin}, {width*cin}, 1, {width*height*cin}), // storageByteStrides
            uint4(0,0,0,0), // paddingBegin
            uint4(0,0,0,0), // paddingEnd
            0, // threadGroupStorageByteOffset
            {scale}, storage_{name} }};'''
    def bias(name,count):
        return f'''    const Tensor1h< ConstantBufferStorage<{count//2}> > {name} = {{
            {count}, // logicalSize
            0, // threadGroupSliceStart
            {count}, // threadGroupSliceSize
            {count}, // storageSize
            2, // storageByteStrides
            0, // paddingBegin
            0, // paddingEnd
            0, // threadGroupStorageByteOffset
            storage_{name} }};'''
    src='\n'.join(data)
    src+='\n[numthreads(64,1,1)]\nvoid model() {\n'
    src+=t3('inp',model.input_tensor.quant_scale,0)+'\n'
    src+=t4('w0',(3,3,16,16),1.)+'\n'+bias('b0',16)+'\n'
    src+=t4('w1',(1,1,16,32),1.)+'\n'+bias('b1',32)+'\n'
    src+=t4('w2',(1,1,32,16),1.)+'\n'+bias('b2',16)+'\n'
    src+=t3('out',model.output_tensor.quant_scale,8294400)+'\n'
    src+='    ConvNextBlock(100, 0.01, 100, 0.01, inp, w0, b0, w1, b1, w2, b2, out, computeShaderParams);\n}\n'
    return '#ifdef MLSR_PASS_1\n'+src+'#endif // #ifdef MLSR_PASS_1\n'


class CPUModelTests(unittest.TestCase):
    def test_descriptor_vector_references(self):
        block='''const uint3 logical = uint3(960, 540, 16);
const uint3 strides = uint3(16, 15360, 1);'''
        body='''logical, // logicalSize
strides, // storageByteStrides'''
        self.assertEqual(_descriptor_vector(block,body,'logicalSize',3),(960,540,16))
        self.assertEqual(_descriptor_vector(block,body,'storageByteStrides',3),(16,15360,1))

    def test_named_scale_with_numeric_suffix(self):
        block='''
const uint3 logicalSize_slice_2 = uint3(960, 540, 16);
const uint3 tensorByteStrides_slice_2 = uint3(16, 15360, 1);
const float quantizationScale_slice_2 = 0.027550771832466125;
const QuantizedTensor3i8_NHWC<RWBufferStorage> slice_2 = {
logicalSize_slice_2, groupStart_slice_2, groupSize_slice_2, storageSize_slice_2,
tensorByteStrides_slice_2, paddingBegin_slice_2, paddingEnd_slice_2,
threadGroupByteOffsetInTensor_slice_2 + 8294400, quantizationScale_slice_2, storage_slice_2 };
'''
        tensor=_descriptor(block,'slice_2','QuantizedTensor3i8_NHWC')
        self.assertEqual(tensor.logical_size,(960,540,16))
        self.assertEqual(tensor.byte_strides,(16,15360,1))
        self.assertEqual(tensor.offset,8294400)
        self.assertAlmostEqual(tensor.quant_scale,0.027550771832466125)

    def test_parse_pinned_shape_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'passes_1080.hlsl'
            p.write_text(fixture_shader(fake_model()))
            parsed=load_model(p)
            self.assertEqual(parsed.w0.shape,(16,3,3,16))
            self.assertEqual(parsed.w1.shape,(32,16))
            self.assertEqual(parsed.w2.shape,(16,32))
            self.assertEqual(parsed.output_tensor.offset,8294400)

    def test_identity_center(self):
        model=fake_model()
        data=np.zeros((540,960,16),dtype=np.int8)
        data[0,0]=10
        data[10,10]=-10
        at=reference_at(model,data,0,0)
        self.assertTrue(np.all(at['acc0']==10))
        self.assertTrue(np.all(at['q0']==10))
        self.assertTrue(np.all(at['q1'][:16]==10))
        self.assertTrue(np.all(at['final']==20))
        negative=reference_at(model,data,10,10)
        self.assertTrue(np.all(negative['q0']==-10))
        self.assertTrue(np.all(negative['q1']==0))
        self.assertTrue(np.all(negative['final']==-10))

    def test_raw_accumulators_indept_of_quantization(self):
        model=fake_model()
        a=np.zeros((540,960,16),dtype=np.int8)
        a[20,20]=np.arange(16,dtype=np.int8)
        stage=reference_at(model,a,20,20)
        self.assertTrue(np.array_equal(stage['acc0'],np.arange(16)))
        self.assertTrue(np.array_equal(expected_for_stage(stage,'acc0_2'),np.arange(8,12)))
        self.assertEqual(expected_for_stage(stage,'q1hi').shape,(16,))

    def test_rounding_diagnostics(self):
        self.assertEqual(int(quantize(np.asarray([127.6]),-128,127,'float32')[0]),127)
        self.assertEqual(int(quantize(np.asarray([-199.]),-128,127,'float64')[0]),-128)

    def test_sampling_stable_and_bounds(self):
        a=sample_coordinates(64)
        self.assertEqual(len(a),64)
        self.assertEqual(a,sample_coordinates(64))
        self.assertTrue(all(0<=x<960 and 0<=y<540 for x,y in a))

    def test_pair_against_cpu(self):
        with tempfile.TemporaryDirectory() as tmp:
            model=fake_model()
            inp=np.zeros((540,960,16),dtype=np.int8)
            inp[:]=12
            # Avoid needing to allocate 4 scratch files in memory at once.
            paths=[]
            for i in range(4):
                p=Path(tmp)/f'scratch{i}.bin'
                with p.open('wb') as f:
                    f.write(inp.tobytes())
                    f.write(np.zeros(8294400,dtype=np.int8).tobytes())
                paths.append(p)
            reference=reference_at(model,inp,0,0)['final'].astype(np.int8)
            for p in paths[1::2]:
                with p.open('r+b') as f:
                    f.seek(8294400)
                    f.write(np.tile(reference,(540*960,1)).tobytes())
            report=evaluate(model,paths[0],paths[1],paths[2],paths[3],'final',18)
            self.assertEqual(report['preference'],'both_close_to_cpu_oracle')


class ShaderStageTests(unittest.TestCase):
    def test_stages(self):
        for v in ['q0','q1lo','q1hi','acc0_0','acc0_3','acc1_7','acc2_3']:
            self.assertTrue(valid_stage(v))
        for v in ['','acc0_4','acc1_8','acc2_4','x','stage0','../']:
            self.assertFalse(valid_stage(v))

    def fixture_operator(self):
        return '''template<typename SI>\nvoid ConvNextBlock(const QuantizedTensor1i32<SB0> bias0) { }\n\n'''+'''template<typename SI>\nvoid ConvNextBlock(
    const QuantizedTensor3i8_NHWC<SI> input,
    const Tensor1h<SB0> bias0, const ComputeShaderParams computeShaderParams) {
            int accumulator[16];
            int relu_output[32];
            int8_t4_packed conv_result[16/4];
            // Second Convolution + Relu
            int8_t4_packed relu_result[32/4];
            int conv3_output[16];
            // Add + store output
        }
#if WMMA_ENABLED
    OTHER_WMMA
#endif
'''

    def test_isolated_operator_probe(self):
        op=self.fixture_operator()
        for stage in ['acc0_0','q0','acc1_0','q1lo','q1hi','acc2_3']:
            edited=guarded_operator(op,stage)
            self.assertEqual(edited.count(SENTINEL),1)
            self.assertTrue(edited.startswith('template<typename SI>\nvoid ConvNextBlock(const QuantizedTensor1i32'))
            self.assertEqual(edited.split('#if WMMA_ENABLED',1)[-1],op.split('#if WMMA_ENABLED',1)[-1])

    def test_pass_only_include(self):
        model='''#ifdef MLSR_PASS_1
#include "ml2code_runtime/operators/int8_NHWC/Fused/ConvNextBlock.hlsli"
#endif // #ifdef MLSR_PASS_1
#ifdef MLSR_PASS_2
#include "ml2code_runtime/operators/int8_NHWC/Fused/ConvNextBlock.hlsli"
#endif // #ifdef MLSR_PASS_2
'''
        edited=redirected_model(model)
        self.assertEqual(edited.count('FSR4N10_CNV_PASS1_STAGE.hlsli'),1)
        self.assertEqual(edited.count('"ml2code_runtime/operators/int8_NHWC/Fused/ConvNextBlock.hlsli"'),1)

    def test_full_overlay(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'fsr4';out=Path(tmp)/'build'
            op=root/OPERATOR_REL
            op.parent.mkdir(parents=True)
            op.write_text(self.fixture_operator())
            model=root/MODEL_REL
            model.parent.mkdir(parents=True)
            model.write_text('''#ifdef MLSR_PASS_1
#include "ml2code_runtime/operators/int8_NHWC/Fused/ConvNextBlock.hlsli"
#endif // #ifdef MLSR_PASS_1
''')
            info=create_overlay(root,out,'acc0_0')
            self.assertTrue(Path(info['model_source']).is_file())
            self.assertTrue(Path(info['operator_overlay']).is_file())
            self.assertNotIn(SENTINEL,op.read_text())
            self.assertEqual(model.read_text().count('FSR4N10_CNV'),0)


class SummaryTests(unittest.TestCase):
    def report(self,stage,scalar,intrinsic):
        return {'schema':'f4n10.pass1-independent-cpu-oracle.v1',
                'source_sha256':'model-hash','stage':stage,
                'preference':'scalar_matches_independent_cpu_oracle',
                'comparisons':{
                    'scalar':{'within_one_lsb_fraction':scalar,'max_abs_error':0},
                    'intrinsic':{'within_one_lsb_fraction':intrinsic,'max_abs_error':10}}}

    def test_raw_accumulator_gap_does_not_recommend_quantization(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths=[]
            for i in range(4):
                path=Path(tmp)/f'acc0_{i}.json'
                path.write_text(json.dumps(self.report(f'acc0_{i}',1.,0.)))
                paths.append(path)
            result=summarize(paths)
            self.assertEqual(result['first_large_path_gap']['stage'],'acc0_0')
            self.assertIn('Raw pass0 accumulator divergence',result['next_action'])

    def test_quantization_is_recommended_only_after_raw_accumulators_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths=[]
            for i in range(4):
                path=Path(tmp)/f'acc0_{i}.json'
                path.write_text(json.dumps(self.report(f'acc0_{i}',1.,1.)))
                paths.append(path)
            q0=Path(tmp)/'q0.json'
            q0.write_text(json.dumps(self.report('q0',1.,0.)))
            paths.append(q0)
            result=summarize(paths)
            self.assertEqual(result['first_large_path_gap']['stage'],'q0')
            self.assertIn('quantization',result['next_action'])

if __name__=='__main__':
    unittest.main()
