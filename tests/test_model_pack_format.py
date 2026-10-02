from __future__ import annotations

import hashlib
import json
import struct
import sys
import unittest
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools" / "model"
sys.path.insert(0, str(TOOLS_DIR))

from model_pack_format import HEADER, MAGIC, TENSOR_RECORD, VERSION, build_model_pack  # noqa: E402


class ModelPackFormatTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parameter_bytes = struct.pack("<eee", 0.5, -1.0, 2.0)
        self.manifest = {
            "format": "fsr4n10-fp16-parameter-pack-v1",
            "outputBytes": len(self.parameter_bytes),
            "outputSha256": hashlib.sha256(self.parameter_bytes).hexdigest().upper(),
            "sourceSha256": "11" * 32,
            "tensorCount": 2,
            "tensors": [
                {
                    "name": "conv.weight",
                    "sourceDType": "int8",
                    "shape": [2],
                    "elementCount": 2,
                    "packOffsetBytes": 0,
                    "packSizeBytes": 4,
                    "quantizationScaleF32": 0.125,
                },
                {
                    "name": "conv.bias",
                    "sourceDType": "float16",
                    "shape": [1],
                    "elementCount": 1,
                    "packOffsetBytes": 4,
                    "packSizeBytes": 2,
                    "quantizationScaleF32": None,
                },
            ],
        }
        self.manifest_bytes = (json.dumps(self.manifest, sort_keys=True) + "\n").encode("utf-8")

    def test_header_records_alignment_and_payload_are_deterministic(self) -> None:
        pack = build_model_pack(self.manifest_bytes, self.parameter_bytes)
        self.assertEqual(pack, build_model_pack(self.manifest_bytes, self.parameter_bytes))
        header = HEADER.unpack_from(pack)
        (
            magic,
            version,
            header_bytes,
            source_hash,
            manifest_hash,
            tensor_count,
            _flags,
            tensor_table_offset,
            string_table_offset,
            data_offset,
            file_bytes,
        ) = header
        self.assertEqual(magic, MAGIC)
        self.assertEqual(version, VERSION)
        self.assertEqual(header_bytes, HEADER.size)
        self.assertEqual(source_hash, bytes.fromhex("11" * 32))
        self.assertEqual(manifest_hash, hashlib.sha256(self.manifest_bytes).digest())
        self.assertEqual(tensor_count, 2)
        self.assertEqual(tensor_table_offset, HEADER.size)
        self.assertGreaterEqual(string_table_offset, tensor_table_offset + 2 * TENSOR_RECORD.size)
        self.assertEqual(file_bytes, len(pack))

        first = TENSOR_RECORD.unpack_from(pack, tensor_table_offset)
        second = TENSOR_RECORD.unpack_from(pack, tensor_table_offset + TENSOR_RECORD.size)
        self.assertEqual(first[4], 1)
        self.assertEqual(first[5:9], (2, 0, 0, 0))
        self.assertEqual(first[9], 16)
        self.assertEqual(first[11] % 16, 0)
        self.assertEqual(first[12], 4)
        self.assertEqual(first[13], 0.125)
        self.assertEqual(second[11] % 16, 0)
        self.assertGreaterEqual(second[11], first[11] + first[12])
        self.assertEqual(pack[first[11] : first[11] + first[12]], self.parameter_bytes[:4])
        self.assertEqual(pack[second[11] : second[11] + second[12]], self.parameter_bytes[4:])
        self.assertEqual(data_offset % 16, 0)

    def test_wrong_parameter_hash_is_rejected(self) -> None:
        self.manifest["outputSha256"] = "00" * 32
        with self.assertRaisesRegex(ValueError, "hash disagrees"):
            build_model_pack(json.dumps(self.manifest).encode("utf-8"), self.parameter_bytes)

    def test_tensor_ranges_outside_parameter_blob_are_rejected(self) -> None:
        self.manifest["tensors"][1]["packOffsetBytes"] = len(self.parameter_bytes)
        with self.assertRaisesRegex(ValueError, "exceeds the raw blob"):
            build_model_pack(json.dumps(self.manifest).encode("utf-8"), self.parameter_bytes)


if __name__ == "__main__":
    unittest.main()
