"""Run after installation: python -m unittest tests.test_scratch_campaign"""
from __future__ import annotations
import json
import tempfile
import unittest
from pathlib import Path
from tools.diagnostics.analyze_scratch_campaign import compare_bytes, analyze_campaign


class CampaignTests(unittest.TestCase):
    def test_byte_page_first_difference(self):
        with tempfile.TemporaryDirectory() as root:
            a = Path(root) / "a.bin"
            b = Path(root) / "b.bin"
            a.write_bytes(bytes(8192))
            v = bytearray(8192)
            v[4104] = 7
            b.write_bytes(v)
            result = compare_bytes(a, b)
            self.assertEqual(result["changed_bytes"], 1)
            self.assertEqual(result["first_changed_offset"], 4104)
            self.assertEqual(result["first_changed_pages"][0]["index"], 1)

    def test_analyze_first_changed_prefix(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            cases = []
            for p in range(3):
                for repeat in (1, 2):
                    outputs = {}
                    for context in ("instrumented", "ordinary"):
                        file = root / f"p{p}_r{repeat}_{context}.bin"
                        values = bytearray(8192)
                        if p >= 2 and repeat == 2:
                            values[21] = 1
                        file.write_bytes(values)
                        outputs[context] = {"path": str(file)}
                    cases.append({"seed": "zero", "pass_name": f"pass_{p:02d}",
                                  "repeat": repeat, "error": None,
                                  "sequence_hash": "same", "input_hashes": ["same"],
                                  "files": outputs})
            report = analyze_campaign({"cases": cases, "variant": "test"})
            self.assertEqual(report["first_by_seed"]["zero"]["first_repeat_divergent_prefix"], 2)
            self.assertIsNone(report["first_by_seed"]["zero"]["first_instrumented_vs_ordinary_divergent_prefix"])

    def test_bounded_prefixes_do_not_claim_full_scratch_agreement(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            cases = []
            for pass_name in ("pass_00", "full"):
                for repeat in (1, 2):
                    outputs = {}
                    for context in ("instrumented", "ordinary"):
                        file = root / f"{pass_name}_r{repeat}_{context}.bin"
                        value = 1 if pass_name == "full" and repeat == 2 else 0
                        file.write_bytes(bytes([value]) * 128)
                        outputs[context] = {"path": str(file)}
                    report_path = root / f"{pass_name}_r{repeat}.json"
                    changed = pass_name == "full" and repeat == 2
                    report_path.write_text(json.dumps({
                        "sequence_hash": "same-sequence",
                        "frames": [{
                            "input_frame_sha256": "same-input",
                            "frame_index": 0,
                            "instrumented_output_sha256": "changed" if changed else "stable",
                            "reference_output_sha256": "changed" if changed else "stable",
                        }],
                    }), encoding="utf-8")
                    cases.append({"seed": "zero", "pass": 0 if pass_name != "full" else None,
                                  "pass_name": pass_name, "repeat": repeat, "error": None,
                                  "sequence_hash": "same-sequence", "input_hashes": ["same-input"],
                                  "report_path": str(report_path), "files": outputs})
            report = analyze_campaign({"cases": cases, "variant": "test"})
            self.assertFalse(report["full_rgb_repeatability"]["zero"]["full_scratch_repeatable"]["ordinary"])
            self.assertTrue(any("prefixes through 0 match" in text for text in report["interpretation"]))


if __name__ == "__main__":
    unittest.main()
