from __future__ import annotations
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools/teacher'))
from i8_arithmetic_pass_overlay import parse_pass_set, build_selected_wrapper


class HybridTests(unittest.TestCase):
    def test_pass_set_empty(self): self.assertEqual(parse_pass_set(''), ())
    def test_pass_set_ordered(self): self.assertEqual(parse_pass_set(' 12, 2, 1 '), (1, 2, 12))
    def test_pass_set_invalid(self):
        for bad in ('0', '13', '3,3', '1;2', '1,,3', '../1', '-1', '0x2'):
            with self.subTest(value=bad):
                with self.assertRaises(ValueError): parse_pass_set(bad)

    def test_wrapper_macro(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = build_selected_wrapper(Path(tmp), '#define dot4add_i8packed scalar_dot4')
            self.assertIn('"passes_1080.hlsl"', path.read_text())
            self.assertIn('#define dot4add_i8packed', path.read_text())

    def test_wrapper_rejects_absolute_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                build_selected_wrapper(Path(tmp), 'macro', 'C:\\user\\secret.hlsl')

if __name__ == '__main__': unittest.main()
