from __future__ import annotations
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools/diagnostics'))
from i8_tensor_layout import parse_contracts

LAYOUTS = [
    (960, 540, 16, 8294400), (960, 540, 16, 0),
    (480, 270, 32, 8294400), (480, 270, 32, 12441600),
    (480, 270, 32, 8294400), (240, 135, 64, 12441600),
    (240, 135, 64, 14515200), (240, 135, 64, 12441600),
    (480, 270, 32, 16588800), (480, 270, 32, 8294400),
    (960, 540, 16, 12441600), (960, 540, 16, 0),
]


def hlsl_fixture():
    parts = []
    for i, (w, h, c, base) in enumerate(LAYOUTS, 1):
        name = f'slice_{2*i}'
        typ = 'Tensor3i8_NHWC' if i == 9 else 'QuantizedTensor3i8_NHWC'
        scale = '' if i == 9 else f'const float quantizationScale_{name} = 0.03125;\n'
        desc = (f'threadGroupByteOffsetInTensor_{name} + {base}, '
                + (f'quantizationScale_{name}, ' if i != 9 else '') + f'storage_{name}')
        parts.append(f'''
#ifdef MLSR_PASS_{i}
const uint3 logicalSize_{name} = uint3({w}, {h}, {c});
const uint3 storageSize_{name} = uint3({w}, {h}, {c});
const uint3 tensorByteStrides_{name} = uint3({c}, {w*c}, 1);
const int threadGroupByteOffsetInTensor_{name} = dot(xyz, abc);
{scale}
const {typ}<RWBufferStorage> {name} = {{logicalSize_{name}, dummy, dummy, storageSize_{name}, tensorByteStrides_{name},
threadGroupByteOffsetInTensor_{name} + {base}, {desc.split(', ', 1)[1]}}};
Operator(inputs, weights, {name}, computeShaderParams);
#endif // #ifdef MLSR_PASS_{i}
''')
    return ''.join(parts)


class LayoutTests(unittest.TestCase):
    def test_known_all_twelve_passes(self):
        results = parse_contracts(hlsl_fixture())
        self.assertEqual(len(results), 12)
        self.assertEqual(results[10].byte_base, 12441600)
        self.assertEqual(results[10].byte_count, 8294400)
        self.assertEqual(results[8].dtype, 'Tensor3i8_NHWC')
        self.assertEqual(results[0].quantization_scale, 0.03125)

    def test_bad_stride_rejected(self):
        source = hlsl_fixture().replace('uint3(16, 15360, 1)', 'uint3(16, 16000, 1)', 1)
        with self.assertRaisesRegex(ValueError, 'contiguous'):
            parse_contracts(source)

    def test_missing_pass_rejected(self):
        source = hlsl_fixture().replace('#ifdef MLSR_PASS_9', '#ifdef MLSR_PASS_90')
        with self.assertRaises(ValueError):
            parse_contracts(source)

    def test_duplicate_pass_rejected(self):
        source = hlsl_fixture() + hlsl_fixture().split('#endif // #ifdef MLSR_PASS_1')[0]
        with self.assertRaises(ValueError):
            parse_contracts(source)

    def test_non_1080_pass11_contract_rejected(self):
        source = hlsl_fixture().replace('uint3(960, 540, 16)', 'uint3(960, 541, 16)')
        with self.assertRaises(ValueError):
            parse_contracts(source)


if __name__ == '__main__':
    unittest.main()
