import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools' / 'diagnostics'))
from audit_i8_pass11_coverage import audit_pass11


class CoverageAuditTest(unittest.TestCase):
    def fixture(self, root, width, height):
        path = root / 'passes_1080.hlsl'
        text = f'''#ifdef MLSR_PASS_11
[numthreads(64, 1, 1)]
void fsr4_model_v07_i8_pass11(uint3 id : SV_DispatchThreadID) {{
const Tensor3i8_NHWC< RWBufferStorage > input = {{
    uint3({width}, {height}, 32), // input
}};
const QuantizedTensor3i8_NHWC< RWBufferStorage > add = {{
    uint3({width*2}, {height*2}, 16),
}};
const Tensor3i8_NHWC< RWBufferStorage > slice_22 = {{
    uint3({width*2}, {height*2}, 16),
}};
FNB_CT2D_ADD<32, 1>(0);
}}
#endif // #ifdef MLSR_PASS_11
'''
        path.write_text(text)
        return path

    def test_1080_hazard(self):
        with tempfile.TemporaryDirectory() as d:
            item = audit_pass11(self.fixture(Path(d), 480, 270))
            self.assertEqual(item['non_wmma_overhang_threads_per_row'], 32)
            self.assertEqual(item['predicted_next_row_alias_pixels'], 64)
            self.assertTrue(item['requires_bounds_guard_or_corrected_dispatch'])

    def test_aligned_resolution(self):
        with tempfile.TemporaryDirectory() as d:
            item = audit_pass11(self.fixture(Path(d), 960, 540))
            self.assertEqual(item['non_wmma_overhang_threads_per_row'], 0)
            self.assertFalse(item['requires_bounds_guard_or_corrected_dispatch'])

    def test_missing_source_marker_fails(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'passes_1080.hlsl'
            p.write_text('// unrelated')
            with self.assertRaises(ValueError):
                audit_pass11(p)


if __name__ == '__main__':
    unittest.main()
