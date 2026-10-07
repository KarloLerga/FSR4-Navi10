from __future__ import annotations

import struct
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools" / "teacher"
sys.path.insert(0, str(TOOLS_DIR))

from capture_format import CaptureFormatError, package_capture, validate_capture  # noqa: E402


class TeacherCaptureFormatTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.array_root = self.root / "source_arrays"
        self.array_root.mkdir()
        self.manifest = {
            "schema": "f4n10.teacher.capture.v1",
            "metadata": {
                "sequence_id": "synthetic-validation-only",
                "frame_index": 0,
                "preset": "native",
                "render_width": 2,
                "render_height": 2,
                "output_width": 2,
                "output_height": 2,
                "jitter_current": [0.0, 0.0],
                "jitter_previous": [0.0, 0.0],
                "exposure": 1.0,
                "pre_exposure": 1.0,
                "reset": True,
                "motion_convention": "render-pixel displacement, previous-to-current",
                "source_commit": "1" * 40,
                "source_hash": "a" * 64,
                "sequence_hash": "d" * 64,
                "shader_hashes": {"pre.dxil": "b" * 64, "post.dxil": "c" * 64},
                "build_commit": "2" * 40,
                "build_mode": "Release",
                "capture_origin": "gpu_teacher_capture",
                "gpu_name": "AMD Radeon RX 5700 XT",
                "driver_version": "test-only",
            },
            "validity": {
                "input_color": True,
                "depth": True,
                "motion_vectors": True,
                "reactive_mask": False,
                "transparency_composition_mask": False,
            },
            "arrays": {},
        }
        shapes = {
            "input_color": [2, 2, 3],
            "depth": [2, 2, 1],
            "motion_vectors": [2, 2, 2],
            "current_reconstruction_source": [2, 2, 3],
            "reprojected_history": [2, 2, 3],
            "model_input_semantic_channels": [2, 2, 7],
            "raw_model_parameters": [2, 2, 4],
            "physical_controls": [2, 2, 4],
            "recurrent_state": [2, 2, 4],
            "final_rgb": [2, 2, 3],
        }
        for name, shape in shapes.items():
            count = 1
            for axis in shape:
                count *= axis
            filename = f"arrays/{name}.raw"
            file_path = self.array_root / filename
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_bytes(struct.pack("<f", 0.25) * count)
            self.manifest["arrays"][name] = {"file": filename, "dtype": "<f4", "shape": shape}

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_package_is_repeatable_and_validates_all_required_arrays(self) -> None:
        first = self.root / "first.f4cap"
        second = self.root / "second.f4cap"
        result = package_capture(self.manifest, self.array_root, first)
        package_capture(self.manifest, self.array_root, second)

        self.assertEqual(first.read_bytes(), second.read_bytes())
        self.assertEqual(10, result["array_count"])
        self.assertEqual(136 * 4, result["array_bytes"])
        self.assertEqual(result, validate_capture(first))
        self.assertEqual("synthetic-validation-only", result["sequence_id"])
        self.assertIn("self-reported", result["validation_note"])

    def test_reference_rgb_is_optional_and_shape_checked(self) -> None:
        legacy = self.root / "legacy.f4cap"
        package_capture(self.manifest, self.array_root, legacy)
        self.assertEqual(10, validate_capture(legacy)["array_count"])

        filename = "arrays/reference_rgb.raw"
        (self.array_root / filename).write_bytes(struct.pack("<f", 0.5) * (2 * 2 * 3))
        self.manifest["arrays"]["reference_rgb"] = {
            "file": filename,
            "dtype": "<f4",
            "shape": [2, 2, 3],
        }
        current = self.root / "current.f4cap"
        package_capture(self.manifest, self.array_root, current)
        self.assertEqual(11, validate_capture(current)["array_count"])

        self.manifest["arrays"]["reference_rgb"]["shape"] = [2, 2, 4]
        with self.assertRaisesRegex(CaptureFormatError, "does not match"):
            package_capture(self.manifest, self.array_root, self.root / "bad.f4cap")

    def test_optional_mask_requires_both_data_and_validity(self) -> None:
        self.manifest["validity"]["reactive_mask"] = True
        with self.assertRaisesRegex(CaptureFormatError, "presence must match"):
            package_capture(self.manifest, self.array_root, self.root / "bad.f4cap")

    def test_rejects_invalid_sequence_hash(self) -> None:
        self.manifest["metadata"]["sequence_hash"] = "not-a-hash"
        with self.assertRaisesRegex(CaptureFormatError, "sequence_hash must be a SHA-256"):
            package_capture(self.manifest, self.array_root, self.root / "bad.f4cap")

    def test_rejects_unsafe_source_path(self) -> None:
        self.manifest["arrays"]["input_color"]["file"] = "arrays/../input.raw"
        with self.assertRaisesRegex(CaptureFormatError, "unsafe"):
            package_capture(self.manifest, self.array_root, self.root / "bad.f4cap")

    def test_rejects_shape_mismatch_before_writing(self) -> None:
        self.manifest["arrays"]["raw_model_parameters"]["shape"] = [2, 2, 3]
        with self.assertRaisesRegex(CaptureFormatError, "does not match"):
            package_capture(self.manifest, self.array_root, self.root / "bad.f4cap")

    def test_rejects_non_finite_values(self) -> None:
        file_path = self.array_root / self.manifest["arrays"]["final_rgb"]["file"]
        file_path.write_bytes(struct.pack("<f", float("nan")) * (2 * 2 * 3))
        with self.assertRaisesRegex(CaptureFormatError, "NaN or Inf"):
            package_capture(self.manifest, self.array_root, self.root / "bad.f4cap")

    def test_rejects_unexpected_archive_entries(self) -> None:
        capture = self.root / "capture.f4cap"
        package_capture(self.manifest, self.array_root, capture)
        tampered = self.root / "tampered.f4cap"
        with zipfile.ZipFile(capture, "r") as source, zipfile.ZipFile(tampered, "w") as target:
            for item in source.infolist():
                target.writestr(item, source.read(item.filename))
            target.writestr("unexpected.txt", b"not part of the schema")
        with self.assertRaisesRegex(CaptureFormatError, "unexpected ZIP entries"):
            validate_capture(tampered)

    def test_rejects_duplicate_manifest_keys(self) -> None:
        capture = self.root / "duplicate.f4cap"
        with zipfile.ZipFile(capture, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.writestr("capture.json", b'{"schema":"x","schema":"y"}')
        with self.assertRaisesRegex(CaptureFormatError, "duplicate JSON key"):
            validate_capture(capture)


if __name__ == "__main__":
    unittest.main()
