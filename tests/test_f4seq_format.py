from __future__ import annotations

import json
import struct
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools" / "sequence"
sys.path.insert(0, str(TOOLS_DIR))

from f4seq_format import F4SeqError, build_f4seq, validate_f4seq  # noqa: E402


class F4SeqFormatTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.metadata = {
            "sequence_id": "small-temporal-fixture",
            "seed": 17,
            "render_size": [2, 2],
            "output_size": [2, 2],
            "preset": "native",
            "source_kind": "test_fixture",
            "source_hash": "a" * 64,
            "motion_vector_convention": "current_to_previous_render_pixels_unjittered",
            "depth_convention": "forward_zero_to_one",
        }
        self.frames = []
        for index in range(2):
            arrays = {}
            planes = {
                "color": struct.pack("<16e", *([0.25 + index * 0.1] * 16)),
                "depth": struct.pack("<4f", *([0.5] * 4)),
                "motion_vectors": struct.pack("<8e", *([0.0] * 8)),
                "reactive_mask": bytes([0, 0, 255, 0]),
                "transparency_composition_mask": bytes([0, 64, 0, 0]),
            }
            for name, data in planes.items():
                relative = f"input/{index:06d}/{name}.raw"
                target = self.source / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                arrays[name] = relative
            self.frames.append({
                "frame_time_delta_ms": 16.666667,
                "jitter_current": [0.25, -0.16666667],
                "jitter_previous": [0.0, 0.16666667],
                "exposure": 1.0 + index * 0.1,
                "pre_exposure": 1.0,
                "reset": index == 0 or index == 1,
                "camera_cut": index == 1,
                "validity": {"reactive_mask": True, "transparency_composition_mask": True},
                "arrays": arrays,
            })

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_pack_is_deterministic_and_records_temporal_state(self) -> None:
        first = self.root / "first.f4seq"
        second = self.root / "second.f4seq"
        summary = build_f4seq(first, self.metadata, self.frames, self.source)
        build_f4seq(second, self.metadata, self.frames, self.source)
        self.assertEqual(first.read_bytes(), second.read_bytes())
        self.assertEqual(summary, validate_f4seq(first))
        self.assertEqual([0, 1], summary["reset_frames"])
        self.assertEqual([1], summary["camera_cuts"])
        self.assertEqual(144, summary["array_bytes"])

    def test_rejects_unsafe_input_path(self) -> None:
        self.frames[0]["arrays"]["color"] = "input/../../outside.raw"
        with self.assertRaisesRegex(F4SeqError, "unsafe"):
            build_f4seq(self.root / "bad.f4seq", self.metadata, self.frames, self.source)

    def test_rejects_non_finite_depth(self) -> None:
        depth_path = self.source / self.frames[0]["arrays"]["depth"]
        depth_path.write_bytes(struct.pack("<4f", 0.5, 0.5, float("nan"), 0.5))
        with self.assertRaisesRegex(F4SeqError, "NaN or Inf"):
            build_f4seq(self.root / "bad.f4seq", self.metadata, self.frames, self.source)

    def test_rejects_missing_valid_mask_plane(self) -> None:
        self.frames[0]["arrays"].pop("reactive_mask")
        with self.assertRaisesRegex(F4SeqError, "required arrays"):
            build_f4seq(self.root / "bad.f4seq", self.metadata, self.frames, self.source)

    def test_rejects_payload_tampering_after_packing(self) -> None:
        source = self.root / "good.f4seq"
        target = self.root / "tampered.f4seq"
        build_f4seq(source, self.metadata, self.frames, self.source)
        with zipfile.ZipFile(source) as archive:
            entries = {item.filename: archive.read(item.filename) for item in archive.infolist()}
        payload_name = "frames/000000/color.raw"
        entries[payload_name] = bytes([entries[payload_name][0] ^ 0x01]) + entries[payload_name][1:]
        with zipfile.ZipFile(target, "w") as archive:
            for name, data in entries.items():
                archive.writestr(name, data, compress_type=zipfile.ZIP_STORED)
        with self.assertRaisesRegex(F4SeqError, "SHA-256 mismatch"):
            validate_f4seq(target)

    def test_rejects_duplicate_json_keys(self) -> None:
        source = self.root / "good.f4seq"
        target = self.root / "duplicate.f4seq"
        build_f4seq(source, self.metadata, self.frames, self.source)
        with zipfile.ZipFile(source) as archive:
            entries = {item.filename: archive.read(item.filename) for item in archive.infolist()}
        parsed = json.loads(entries["sequence.json"])
        manifest = json.dumps(parsed, separators=(",", ":"), allow_nan=False).encode()
        entries["sequence.json"] = manifest[:-1] + b',"schema":"duplicate"}'
        with zipfile.ZipFile(target, "w") as archive:
            for name, data in entries.items():
                archive.writestr(name, data, compress_type=zipfile.ZIP_STORED)
        with self.assertRaisesRegex(F4SeqError, "duplicate JSON key"):
            validate_f4seq(target)


if __name__ == "__main__":
    unittest.main()
