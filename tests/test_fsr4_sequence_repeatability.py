from __future__ import annotations

import copy
import unittest

from tools.oracles.compare_fsr4_sequence_repeatability import compare_reports


def sequence_report() -> dict:
    return {
        "schema": "f4n10.fsr4-provider-sequence.v1",
        "build_commit": "a" * 40,
        "adapter": "AMD Radeon RX 5700 XT",
        "driver_version": "test-driver",
        "sequence_hash": "b" * 64,
        "sequence_id": "test-sequence",
        "source_kind": "procedural_synthetic",
        "render_size": [2, 2],
        "output_size": [2, 2],
        "frame_count": 2,
        "frames": [
            {
                "frame_index": index,
                "input_frame_sha256": str(index) * 64,
                "instrumented_output_sha256": str(index + 2) * 64,
                "reference_output_sha256": str(index + 4) * 64,
                "reset": index == 0,
                "camera_cut": False,
            }
            for index in range(2)
        ],
    }


class Fsr4SequenceRepeatabilityTests(unittest.TestCase):
    def test_identical_inputs_and_outputs_pass(self) -> None:
        report = sequence_report()
        result = compare_reports(report, copy.deepcopy(report))
        self.assertTrue(result["same_inputs"])
        self.assertTrue(result["repeatable"])

    def test_changed_gpu_output_fails_closed(self) -> None:
        first = sequence_report()
        second = copy.deepcopy(first)
        second["frames"][1]["reference_output_sha256"] = "f" * 64
        result = compare_reports(first, second)
        self.assertTrue(result["same_inputs"])
        self.assertFalse(result["ordinary_outputs_repeatable"])
        self.assertFalse(result["repeatable"])

    def test_different_input_hashes_do_not_claim_nonrepeatability(self) -> None:
        first = sequence_report()
        second = copy.deepcopy(first)
        second["frames"][1]["input_frame_sha256"] = "e" * 64
        result = compare_reports(first, second)
        self.assertFalse(result["same_inputs"])
        self.assertFalse(result["instrumented_outputs_repeatable"])
        self.assertFalse(result["ordinary_outputs_repeatable"])


if __name__ == "__main__":
    unittest.main()
