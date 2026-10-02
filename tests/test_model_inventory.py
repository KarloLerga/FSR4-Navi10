from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools" / "model"
sys.path.insert(0, str(TOOLS_DIR))

from extract_manifest import InventoryError, classify_entrypoint, parse_entrypoints  # noqa: E402


class EntryPointClassificationTests(unittest.TestCase):
    def test_main_entry_points_match_provider_roles(self) -> None:
        self.assertEqual(classify_entrypoint("fsr4_model_v07_i8_pass0", 0, False), "model_pre")
        self.assertEqual(classify_entrypoint("fsr4_model_v07_i8_pass1", 1, False), "neural_pass")
        self.assertEqual(classify_entrypoint("fsr4_model_v07_i8_pass12", 12, False), "neural_pass")
        self.assertEqual(classify_entrypoint("fsr4_model_v07_i8_pass13", 13, False), "model_post")

    def test_padding_reset_entry_points_are_separate(self) -> None:
        self.assertEqual(
            classify_entrypoint("fsr4_model_v07_i8_pass0", 0, True), "padding_reset"
        )
        self.assertEqual(
            classify_entrypoint("fsr4_model_v07_i8_pass12", 12, True), "padding_reset"
        )

    def test_unknown_entry_point_fails_closed(self) -> None:
        with self.assertRaises(InventoryError):
            classify_entrypoint("fsr4_model_v07_i8_pass14", 14, False)

    def test_parser_records_lines_and_roles(self) -> None:
        source = """// pass entry points
void fsr4_model_v07_i8_pass0(
    uint3 id : SV_DispatchThreadID)
{}
void fsr4_model_v07_i8_pass1(uint3 id : SV_DispatchThreadID)
{}
void fsr4_model_v07_i8_pass0_post(uint3 id : SV_DispatchThreadID)
{}
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            shader = Path(temp_dir) / "passes.hlsl"
            shader.write_text(source, encoding="utf-8")
            entries = parse_entrypoints(shader)

        self.assertEqual(
            [(entry["index"], entry["role"], entry["line"]) for entry in entries],
            [(0, "model_pre", 2), (1, "neural_pass", 5), (0, "padding_reset", 7)],
        )


if __name__ == "__main__":
    unittest.main()
