from __future__ import annotations
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools/diagnostics'))
from i8_tensor_layout import SCRATCH_BYTES
from analyze_i8_numeric_bisector import byte_difference, analyze

class ByteDiffTests(unittest.TestCase):
    def test_exact_diff_and_signed(self):
        a=np.array([0,255,1,127],dtype=np.uint8)
        b=np.array([0,1,1,128],dtype=np.uint8)
        result=byte_difference(a,b,120, {'width':2,'height':1,'channels':2})
        self.assertEqual(result['different_bytes'],2)
        self.assertEqual(result['first_absolute_byte'],121)
        self.assertEqual(result['first_values_signed_i8'],[-1,1])
        self.assertEqual(result['first_coordinate'], {'x':0,'y':0,'channel':1})
    def test_all_equal(self):
        a=np.zeros(6,dtype=np.uint8)
        result=byte_difference(a,a,10)
        self.assertEqual(result['different_bytes'],0)
        self.assertIsNone(result['first_coordinate'])
    def test_wrong_dtype_rejected(self):
        with self.assertRaises(ValueError): byte_difference(np.zeros(4,dtype=np.int8),np.zeros(4,dtype=np.int8))

    def test_first_output_difference_not_early_unrelated_scratch(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)
            files={}
            # Prefill sparse scratch, do not allocate dozens of copies in memory.
            for variant, changed in (('intrinsic',False),('scalar',True)):
                path=directory/f'{variant}.bin'
                with path.open('wb') as stream: stream.truncate(SCRATCH_BYTES)
                with path.open('r+b') as stream:
                    if changed:
                        stream.seek(8_294_400 + 160)
                        stream.write(b'\xfd')
                data=path.read_bytes()
                files[variant]={'path':str(path),'size':SCRATCH_BYTES,'sha256':hashlib.sha256(data).hexdigest()}
            campaigns=[]
            for variant in ('intrinsic','scalar'):
                cases=[]
                for repeat in (1,2):
                    cases.append({'seed':'zero','pass_name':'pass_01','pass':1,'repeat':repeat,
                                  'exit_code':0,'error':None,'sequence_hash':'0'*64,
                                  'adapter':'AMD Radeon RX 5700 XT',
                                  'driver_version':'32.0.21045.1000',
                                  'input_hashes':['1'*64,'2'*64],
                                  'scratch':{'ordinary':files[variant],'instrumented':files[variant]},
                                  'frame_hashes':[]})
                campaigns.append({'schema':'f4n10.i8-numeric-campaign.v1','variant':variant,
                                  'source_commit':'same','sequence_file_sha256':'same',
                                  'trace_frame':0,'stages':['1'],'seeds':['zero'],
                                  'repeats':2,'diagnostic_modes':{
                                  'pass11_bounds_guard':True,'stable_post_math':False},
                                  'cases':cases})
            tensors={'source_sha256':'same','passes':[
                {'pass_index':1,'name':'slice_2','byte_base':8294400,'byte_count':8294400,
                 'width':960,'height':540,'channels':16,'quantization_scale':0.031}]}
            result=analyze(*campaigns,tensors)
            self.assertEqual(result['first_valid_output_pass'],1)
            self.assertEqual(result['first_valid_output_tensor_difference']['first_absolute_byte'],8294560)
            self.assertTrue(result['within_mode_repeatable'])
            self.assertTrue(result['same_inputs'])

if __name__=='__main__': unittest.main()
