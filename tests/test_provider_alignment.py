from __future__ import annotations

import sys
import unittest
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools" / "sequence"
sys.path.insert(0, str(TOOLS_DIR))

from compare_provider_runs import AlignmentError, compare_reports  # noqa: E402


def reports() -> tuple[dict, dict]:
    input_hash = "a" * 64
    output_hash = "b" * 64
    fsr4 = {
        "schema": "f4n10.fsr4-provider-sequence.v1",
        "sequence_id": "paired-fixture",
        "source_kind": "synthetic",
        "sequence_hash": "c" * 64,
        "render_size": [1920, 1080],
        "output_size": [1920, 1080],
        "frame_count": 1,
        "adapter": "RX 5700 XT",
        "upstream_commit": "d" * 40,
        "instrumentation_matches_reference": True,
        "gpu_timing_recorded": True,
        "gpu_timing": {
            "steady_state_mean_us": 1000.0,
            "steady_state_p50_us": 1000.0,
            "steady_state_p95_us": 1000.0,
        },
        "frames": [{
            "frame_index": 0,
            "reset": True,
            "camera_cut": False,
            "input_frame_sha256": input_hash,
            "reference_output_sha256": output_hash,
            "reference_gpu_dispatch_us": 1000.0,
            "output_identical": True,
            "capture_manifest": "frame_0/manifest.json",
        }],
    }
    fsr3 = {
        "schema": "f4n10.fsr3-reference-sequence.v1",
        "provider": "FidelityFX FSR3.1.5",
        "sdk_commit": "e" * 40,
        "gpu_name": "RX 5700 XT",
        "sequence": {
            "id": "paired-fixture",
            "source_kind": "synthetic",
            "sequence_hash": "c" * 64,
            "render_size": [1920, 1080],
            "output_size": [1920, 1080],
            "frame_count": 1,
        },
        "validation": {
            "instrumented_reference_outputs_match": True,
            "gpu_timing_recorded": True,
        },
        "gpu_timing": {
            "steady_state_mean_us": 500.0,
            "steady_state_p50_us": 500.0,
            "steady_state_p95_us": 500.0,
        },
        "frames": [{
            "frame_index": 0,
            "reset": True,
            "camera_cut": False,
            "input_frame_sha256": input_hash,
            "reference_output_sha256": output_hash,
            "reference_gpu_dispatch_us": 500.0,
            "instrumented_reference_match": True,
            "capture_manifest": "frame_0/manifest.json",
        }],
    }
    return fsr4, fsr3


class ProviderAlignmentTests(unittest.TestCase):
    def test_pairs_identical_frame_inputs_and_keeps_timings_separate(self) -> None:
        fsr4, fsr3 = reports()
        result = compare_reports(fsr4, fsr3)
        self.assertTrue(result["input_frames_aligned_by_sha256"])
        self.assertFalse(result["cross_provider_output_equality_claimed"])
        self.assertEqual(result["audit_capture_frames"], [0])
        self.assertEqual(result["timing_us"]["fsr4_steady_state_mean"], 1000.0)
        self.assertEqual(result["timing_us"]["fsr3_steady_state_mean"], 500.0)

    def test_rejects_mismatched_frame_input_hash(self) -> None:
        fsr4, fsr3 = reports()
        fsr3["frames"][0]["input_frame_sha256"] = "f" * 64
        with self.assertRaisesRegex(AlignmentError, "input frame SHA-256 differs"):
            compare_reports(fsr4, fsr3)

    def test_rejects_capture_audit_frame_mismatch(self) -> None:
        fsr4, fsr3 = reports()
        fsr3["frames"][0].pop("capture_manifest")
        with self.assertRaisesRegex(AlignmentError, "captured different audit frames"):
            compare_reports(fsr4, fsr3)


if __name__ == "__main__":
    unittest.main()
