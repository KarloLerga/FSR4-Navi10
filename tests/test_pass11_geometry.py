import sys
import tempfile
import unittest
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools' / 'diagnostics'))
from analyze_pass11_alias import (INPUT_WIDTH, THREADS_X, DISPATCH_GROUPS_X,
    OUTPUT_WIDTH, OUTPUT_HEIGHT, OUTPUT_STRIDE, OUTPUT_BASE, OUTPUT_END,
    OVERFLOW_OUTPUT_PIXELS, SCRATCH_BYTES, aliases_at_output_row, label_offsets, compare_scratch)


class Pass11GeometryTest(unittest.TestCase):
    def test_launch_overhang(self):
        self.assertEqual(INPUT_WIDTH, 480)
        self.assertEqual(THREADS_X * DISPATCH_GROUPS_X, 512)
        self.assertEqual(OVERFLOW_OUTPUT_PIXELS, 64)
        self.assertEqual(OUTPUT_WIDTH, 960)
        self.assertEqual(OUTPUT_HEIGHT, 540)
        self.assertEqual(OUTPUT_STRIDE, 15360)
        self.assertEqual(OUTPUT_END, 20736000)

    def test_exact_13240320_witness(self):
        witness = aliases_at_output_row(52)
        self.assertEqual(witness['scratch_byte_offset'], 13240320)
        self.assertEqual(witness['invalid_writer']['dispatch_thread_xy'], [480, 25])
        self.assertEqual(witness['invalid_writer']['local_xy'], [0, 1])
        self.assertEqual(witness['invalid_writer']['semantic_output_xy'], [960, 51])
        self.assertEqual(witness['valid_writer']['dispatch_thread_xy'], [0, 26])
        self.assertEqual(witness['valid_writer']['semantic_output_xy'], [0, 52])

    def test_alias_for_many_rows(self):
        for row in range(1, OUTPUT_HEIGHT):
            writer = aliases_at_output_row(row)
            spill = writer['invalid_writer']
            valid = writer['valid_writer']
            # The raw linear address is the same despite different semantic xy.
            spill_addr = OUTPUT_BASE + ((spill['semantic_output_xy'][1] * OUTPUT_WIDTH + spill['semantic_output_xy'][0]) * 16)
            valid_addr = OUTPUT_BASE + ((valid['semantic_output_xy'][1] * OUTPUT_WIDTH + valid['semantic_output_xy'][0]) * 16)
            self.assertEqual(spill_addr, valid_addr)
            self.assertEqual(spill_addr, writer['scratch_byte_offset'])

    def test_changed_bytes_alias_classifier(self):
        inside = OUTPUT_BASE + 52 * OUTPUT_STRIDE
        changed = [inside, inside + 16 * 63 + 15, inside + 16 * 64, OUTPUT_BASE - 1, OUTPUT_END]
        result = label_offsets(changed)
        self.assertEqual(result['candidate_alias_zone_bytes'], 2)
        self.assertEqual(result['inside_pass11_output'], 3)
        self.assertEqual(result['outside_pass11_output'], 2)
        self.assertEqual(result['top_alias_rows'][0]['row'], 52)

    def test_binary_scratch_reader_maps_real_offset(self):
        with tempfile.TemporaryDirectory() as d:
            a, b = Path(d) / 'a.bin', Path(d) / 'b.bin'
            aa = np.memmap(a, dtype=np.uint8, mode='w+', shape=(SCRATCH_BYTES,))
            bb = np.memmap(b, dtype=np.uint8, mode='w+', shape=(SCRATCH_BYTES,))
            aa[:] = 0
            bb[:] = 0
            bb[13_240_320] = 12
            bb[13_240_321] = 34
            aa.flush()
            bb.flush()
            del aa, bb
            summary = compare_scratch(a, b)
            self.assertEqual(summary['changed_bytes'], 2)
            self.assertEqual(summary['first_changed_offset'], 13_240_320)
            self.assertEqual(summary['candidate_alias_zone_bytes'], 2)

    def test_bad_rows(self):
        for row in (-1, 0, OUTPUT_HEIGHT):
            with self.assertRaises(ValueError):
                aliases_at_output_row(row)


if __name__ == '__main__':
    unittest.main()
