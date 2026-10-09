"""Pure CPU and patch-safety regressions for Pass1 native lowering probes."""
from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path

import numpy as np

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'tools/teacher'))
sys.path.insert(0,str(REPO/'tools/diagnostics'))

# A self-contained ZIP can execute these pure tests before installation; in
# the actual repo the real pass1_golden module must be used for GPU reports.
try:
    import pass1_golden  # noqa: F401
except ImportError:
    stub=types.ModuleType('pass1_golden')
    stub.load_model=lambda x: None
    stub.sample_coordinates=lambda x: []
    sys.modules['pass1_golden']=stub

from pass1_dot4_variants import VARIANTS,HELPERS,make_wrapper
from compare_pass1_dot0 import dot_signed,signed_bytes,first_valid_kernel,pack_bytes
from infer_pass1_signedness import correction_features,evaluate_masks
from run_pass1_intrinsic_recovery import strict_gold

class Pass1RecoveryTests(unittest.TestCase):
    def test_signed_unpack(self):
        self.assertEqual(signed_bytes(0x7f80ff00),[0,-1,-128,127])
        self.assertEqual(dot_signed(0x7f80ff00,0x01010101,7),5)

    def test_pack_roundtrip(self):
        self.assertEqual(pack_bytes(np.array([0,-1,-128,127],dtype=np.int8)),0x7f80ff00)

    def test_first_valid_kernel(self):
        self.assertEqual(first_valid_kernel(0,0),(1,1,0,0))
        self.assertEqual(first_valid_kernel(4,4),(0,0,3,3))
        self.assertEqual(first_valid_kernel(959,539),(0,0,538,958))

    def test_supported_variants(self):
        self.assertEqual(len(VARIANTS),6)
        for name in VARIANTS:
            with tempfile.TemporaryDirectory() as tmp:
                p=make_wrapper(Path(tmp),name)
                content=p.read_text(encoding='utf-8')
                self.assertIn('#define dot4add_i8packed fsr4n10_experimental_dot4',content)
                self.assertIn('int fsr4n10_experimental_dot4(uint a, uint b, int acc)',content)
                self.assertIn('#include "passes_1080.hlsl"',content)

    def test_variant_rejects_path_injection(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                make_wrapper(Path(tmp),'native_zero','../../evil.hlsl')
            with self.assertRaises(ValueError):
                make_wrapper(Path(tmp),'unknown')

    def test_all_scalar_numeric_shapes(self):
        w=np.zeros((16,3,3,16),dtype=np.int64)
        x=np.zeros((540,960,16),dtype=np.int8)
        w[:,1,1,:]=-1
        x[10,10,:]=-2
        base,ic,wc,cc=correction_features(w,x,[(10,10),(0,0)])
        self.assertEqual(base.shape,(2,16))
        self.assertEqual(ic.shape,(2,16,4))
        self.assertTrue(np.all(base[0]==32))
        self.assertTrue(np.all(ic[0]==-1024))
        self.assertTrue(np.all(wc[0]==-2048))
        self.assertTrue(np.all(cc[0]==262144))

    def test_lane_mask_solver(self):
        rng=np.random.default_rng(42)
        shape=(7,16)
        base=rng.integers(-500,500,size=shape,dtype=np.int64)
        ic=rng.integers(-20,20,size=shape+(4,),dtype=np.int64)*256
        wc=rng.integers(-20,20,size=shape+(4,),dtype=np.int64)*256
        cc=rng.integers(0,3,size=shape+(4,),dtype=np.int64)*65536
        imask,wmask=0b0101,0b1010
        iu=np.array([(imask>>i)&1 for i in range(4)],dtype=np.int64)
        wu=np.array([(wmask>>i)&1 for i in range(4)],dtype=np.int64)
        observed=base+ic@iu+wc@wu+cc@(iu*wu)
        ranks=evaluate_masks(base,ic,wc,cc,observed)
        self.assertEqual((ranks[0]['input_unsigned_lane_mask'],ranks[0]['weight_unsigned_lane_mask']),(imask,wmask))
        self.assertEqual(ranks[0]['exact_lanes'],7*16)

    def test_unsigned_biased_dot4_identity(self):
        rng=np.random.default_rng(444)
        for _ in range(3000):
            a=int(rng.integers(0,1<<32,dtype=np.uint64))
            b=int(rng.integers(0,1<<32,dtype=np.uint64))
            def u8dot(x,y):
                return sum(((x>>(8*i))&255)*((y>>(8*i))&255) for i in range(4))
            ax=a^0x80808080; bx=b^0x80808080
            transformed=u8dot(ax,bx)-128*(u8dot(ax,0x01010101)+u8dot(bx,0x01010101))+65536
            self.assertEqual(transformed,dot_signed(a,b,0))

    def test_strict_accumulator_gate(self):
        d={'stage':'acc0_0','pass0_inputs_equal':True,'comparisons':{
           'scalar':{'exact_lanes':512,'total':512},'intrinsic':{'exact_lanes':512,'total':512}}}
        self.assertTrue(strict_gold(d,'acc0_0'))
        d['comparisons']['intrinsic']['exact_lanes']=511
        self.assertFalse(strict_gold(d,'acc0_0'))

    def test_strict_final_gate(self):
        d={'stage':'final','pass0_inputs_equal':True,'comparisons':{
           'scalar':{'exact_lanes':2048,'total':2048},'intrinsic':{'exact_lanes':2048,'total':2048}}}
        self.assertTrue(strict_gold(d,'final'))
        d['pass0_inputs_equal']=False
        self.assertFalse(strict_gold(d,'final'))

if __name__=='__main__':
    unittest.main()
