from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "naviprism"))
from msad4_reference import (  # noqa: E402
    MAX_DIFFERENCE_PER_MSAD4_LANE,
    SAFE_CALLS_PER_CHUNK,
    chunked_msad4_sum,
    encode_valid_bytes,
    msad4_reference,
    pack_bytes,
)


class Msad4ReferenceTests(unittest.TestCase):
    def test_documented_byte_order_and_accumulator(self) -> None:
        result = msad4_reference(
            0xA100B2C3, 0xD7B0C372, 0x4F57C2A3, (1, 2, 3, 4)
        )
        self.assertEqual(result, (153, 6, 92, 113))

    def test_zero_reference_bytes_mask_source_differences(self) -> None:
        reference = pack_bytes((0, 0, 0, 0xFF))
        result = msad4_reference(reference, 0x01020304, 0x05060708)
        self.assertEqual(result, (254, 247, 248, 249))

    def test_encoded_valid_values_reserve_zero_and_preserve_distance(self) -> None:
        encoded = encode_valid_bytes((0, 1, 127, 254))
        self.assertEqual(encoded, (1, 2, 128, 255))
        logical = (0, 1, 127, 254)
        for left in range(len(logical)):
            for right in range(len(logical)):
                self.assertEqual(abs(logical[left] - logical[right]),
                                 abs(encoded[left] - encoded[right]))

    def test_chunking_keeps_each_accumulator_below_undefined_range(self) -> None:
        maximum = (0xFFFFFFFF, 0x01010101, 0x01010101)
        samples = [maximum] * 65
        result = chunked_msad4_sum(samples)
        self.assertEqual(result, (65 * MAX_DIFFERENCE_PER_MSAD4_LANE,) * 4)
        self.assertEqual(65, SAFE_CALLS_PER_CHUNK + 17)

    def test_rejects_unsafe_chunk_size_and_invalid_encoded_byte(self) -> None:
        with self.assertRaises(ValueError):
            chunked_msad4_sum([], SAFE_CALLS_PER_CHUNK + 1)
        with self.assertRaises(ValueError):
            encode_valid_bytes((255,))


if __name__ == "__main__":
    unittest.main()
