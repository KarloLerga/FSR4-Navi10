from __future__ import annotations

import struct
import sys
import unittest
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools" / "model"
sys.path.insert(0, str(TOOLS_DIR))

from extract_fp16_weights import convert_weights, dequantize_i8, to_half  # noqa: E402


SAMPLE_HLSL = """
static const uint embedded_weight_dwords[1] = { 0x0000FE01 };
const ConstantBufferStorage<1> storage_embedded_weight = { embedded_weight_dwords };
const QuantizedTensor4i8_NHWC< ConstantBufferStorage<1> > embedded_weight = {
    uint4(1, 1, 1, 2), // logicalSize
    uint4(0, 0, 0, 0), // threadGroupSliceStart
    uint4(1, 1, 1, 2), // threadGroupSliceSize
    uint4(1, 1, 1, 2), // storageSize
    uint4(2, 2, 1, 1), // storageByteStrides
    uint4(0, 0, 0, 0), // paddingBegin
    uint4(0, 0, 0, 0), // paddingEnd
    0, // threadGroupStorageByteOffset
    0.5, storage_embedded_weight };

const BufferStorage storage_external_weight = { InitializerBuffer };
const QuantizedTensor4i8_HWCN< BufferStorage > external_weight = {
    uint4(1, 1, 1, 2), // logicalSize
    uint4(0, 0, 0, 0), // threadGroupSliceStart
    uint4(1, 1, 1, 2), // threadGroupSliceSize
    uint4(1, 1, 1, 2), // storageSize
    uint4(2, 2, 1, 1), // storageByteStrides
    uint4(0, 0, 0, 0), // paddingBegin
    uint4(0, 0, 0, 0), // paddingEnd
    0, // threadGroupStorageByteOffset
    1.0, storage_external_weight };
"""


class Fp16WeightConversionTests(unittest.TestCase):
    def test_half_scale_and_product_round_like_the_upstream_half_path(self) -> None:
        scale = 0.003944522235542536
        expected = struct.pack("<e", to_half(17 * to_half(scale)))
        self.assertEqual(dequantize_i8(17, scale), expected)

    def test_embedded_and_initializer_weights_are_unpacked_in_logical_order(self) -> None:
        initializer = struct.pack("<I", 0x0000FE01)
        pack, tensors = convert_weights(SAMPLE_HLSL, initializer)

        self.assertEqual([tensor["name"] for tensor in tensors], ["embedded_weight", "external_weight"])
        self.assertEqual([tensor["sourceStorage"] for tensor in tensors], ["embedded", "initializer"])
        self.assertEqual(pack[:4], struct.pack("<ee", 0.5, -1.0))
        self.assertEqual(pack[4:], struct.pack("<ee", 1.0, -2.0))

    def test_truncated_initializer_fails_bounds_check(self) -> None:
        with self.assertRaisesRegex(ValueError, "exceeds initializer storage size"):
            convert_weights(SAMPLE_HLSL, bytes([1]))


if __name__ == "__main__":
    unittest.main()
