import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools' / 'teacher'))
from fnb_bounds_overlay import (BEFORE_INPUT, BEFORE_OUTPUT, SENTINEL,
                                guarded_operator, create_overlay, OPERATOR_REL)


class ShaderOverlayTest(unittest.TestCase):
    def setUp(self):
        self.upstream = ('// untouched <64,2> operator\n'
                         '_Static_assert(numFeatures == 64, "NumFeatures must be 64");\n'
                         '// a diagnostic independent overload\n'
                         '_Static_assert(numFeatures == 32, "NumFeatures must be 32");\n'
                         + BEFORE_INPUT + '\n'
                         '// other original code\n'
                         + BEFORE_OUTPUT + '\n'
                         'output.storage.Store4(output.OffsetOf(int3(poBase2D,z-16)),words);\n'
                         '}\n#if WMMA_ENABLED\n'
                         '_Static_assert(numFeatures == 32, "NumFeatures must be 32");\n'
                         '// separate WMMA <32,1> overload\n'
                         'AmdWaveMatrixMultiply(weightMatrix, inputMatrix, accumulatorMatrix);\n'
                         '#endif // #if WMMA_ENABLED\n')

    def test_guards_exact_overload(self):
        out = guarded_operator(self.upstream)
        self.assertIn(SENTINEL, out)
        self.assertIn('if (any(computeShaderParams.dispatchThreadID.xy >= input.logicalSize.xy))', out)
        self.assertIn('if (any(poBase2D >= output.logicalSize.xy))', out)
        self.assertEqual(out[:out.index('_Static_assert(numFeatures == 32')],
                         self.upstream[:self.upstream.index('_Static_assert(numFeatures == 32')])
        self.assertEqual(out[out.index('#if WMMA_ENABLED'):], self.upstream[self.upstream.index('#if WMMA_ENABLED'):])
        self.assertEqual(out.count(SENTINEL), 1)

    def test_double_apply_fails(self):
        with self.assertRaises(ValueError):
            guarded_operator(guarded_operator(self.upstream))

    def test_changed_upstream_fails_closed(self):
        with self.assertRaises(ValueError):
            guarded_operator(self.upstream.replace('uint4 storeDwords =', 'uint4 storageValue ='))
        with self.assertRaises(ValueError):
            guarded_operator(self.upstream.replace(BEFORE_INPUT, 'const float foo = 0;'))

    def test_generated_overlay_uses_build_tree(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            original = root / 'pinned/dx12' / OPERATOR_REL
            original.parent.mkdir(parents=True)
            original.write_text(self.upstream)
            model = root / 'pinned/internal/shaders/fsr4_model_v07_i8_native/passes_1080.hlsl'
            model.parent.mkdir(parents=True)
            model.write_text('#ifdef MLSR_PASS_11\n[numthreads(64, 1, 1)]\n'
                             '#include "ml2code_runtime/operators/int8_NHWC/Fused/FNB_CT2D_ADD.hlsli"\n'
                             'uint3(480, 270, 32)\nuint3(960, 540, 16)\n'
                             'threadGroupByteOffsetInTensor_slice_22 + 12441600\n'
                             'FNB_CT2D_ADD<32, 1>(\n#endif // #ifdef MLSR_PASS_11\n')
            result = create_overlay(root / 'pinned', root / 'build')
            dest = Path(result['overlay'])
            self.assertIn('capture_shader_overrides', str(dest))
            self.assertEqual(original.read_text(), self.upstream)
            self.assertEqual(dest.read_text(), guarded_operator(self.upstream))
            self.assertNotEqual(result['source_sha256'], result['overlay_sha256'])
            model_overlay = Path(result['model_overlay'])
            expected_model = model.read_text().replace(
                '#include "ml2code_runtime/operators/int8_NHWC/Fused/FNB_CT2D_ADD.hlsli"',
                f'#include "{dest.name}"')
            self.assertEqual(model_overlay.read_text(), expected_model)
            self.assertEqual(result['model_overlay_sha256'], __import__('hashlib').sha256(model_overlay.read_bytes()).hexdigest())
            self.assertEqual(model.read_text().count('FNB_CT2D_ADD.hlsli'), 1)

if __name__ == '__main__':
    unittest.main()
