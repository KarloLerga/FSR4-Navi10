from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import OpenEXR
import torch
from PIL import Image

from training.naviqsr.analytic_reconstruction import analytic_reconstruct
from training.naviqsr.blocks import ReparamBlock, fold_reparam_block
from training.naviqsr.datasets.procedural import render_sequence
from training.naviqsr.datasets.qrisp import import_manifest
from training.naviqsr.export import export_checkpoint
from training.naviqsr.model import NaviQSRNetwork
from training.naviqsr.polyphase import (depth_to_space, haar_polyphase,
                                        inverse_haar_polyphase, space_to_depth)
from tools.naviqsr.validate_model_pack import validate as validate_pack


class NaviQSRReferenceTests(unittest.TestCase):
    def test_polyphase_and_haar_are_reversible(self) -> None:
        source = torch.randn((2, 3, 18, 22), generator=torch.Generator().manual_seed(7))
        self.assertTrue(torch.equal(depth_to_space(space_to_depth(source)), source))
        haar = haar_polyphase(source)
        restored = inverse_haar_polyphase(haar)
        self.assertLess(float((restored - source).abs().max()), 4.0e-7)

    def test_reparameterization_fold_matches_at_edges_and_interior(self) -> None:
        torch.manual_seed(17)
        block = ReparamBlock(8).eval()
        folded = fold_reparam_block(block).eval()
        probe = torch.randn((2, 8, 13, 16), generator=torch.Generator().manual_seed(11))
        with torch.no_grad():
            error = (block(probe) - folded(probe)).abs().max().item()
        self.assertLess(error, 2.0e-6)

    def test_analytic_filter_is_finite_and_invalid_history_is_ignored(self) -> None:
        lr = torch.ones((1, 3, 12, 16), dtype=torch.float32) * 0.25
        controls = torch.zeros((1, 8, 6, 8), dtype=torch.float32)
        residual = torch.zeros((1, 3, 6, 8), dtype=torch.float32)
        history = torch.full((1, 3, 24, 32), 10.0)
        motion = torch.zeros((1, 2, 12, 16))
        valid = torch.zeros((1, 1, 12, 16))
        result = analytic_reconstruct(lr, controls, residual, 2, history, motion,
                                      history_valid=valid, taps=8)
        self.assertTrue(torch.isfinite(result["output"]).all())
        self.assertTrue(torch.allclose(result["spd"][:, 0], torch.ones_like(result["spd"][:, 0])))
        self.assertTrue(torch.allclose(result["spd"][:, 2], torch.ones_like(result["spd"][:, 2])))
        self.assertTrue(torch.allclose(result["output"], result["current"], atol=1.0e-6))

    def test_procedural_sequence_is_deterministic_and_contains_resets(self) -> None:
        first = render_sequence(width=20, height=16, frames=6, seed=321)
        second = render_sequence(width=20, height=16, frames=6, seed=321)
        for key in ("hr_rgb", "lr_rgb", "depth", "motion", "reactive", "jitter"):
            self.assertTrue(np.array_equal(first[key], second[key]), key)
        self.assertEqual(first["reset"].tolist(), [1, 0, 0, 1, 0, 0])
        self.assertEqual(first["hr_rgb"].shape, (6, 32, 40, 3))
        self.assertTrue(np.isfinite(first["motion"]).all())

    def test_folded_fp16_model_pack_round_trip_metadata(self) -> None:
        model = NaviQSRNetwork(input_channels=11, width=4, blocks=1,
                               hf_width=2, polyphase_mode="raw")
        checkpoint = {"format": "naviqsr-checkpoint-v1",
                      "model_config": model.config(),
                      "model_state": model.state_dict(),
                      "training": {"backend": "cpu", "updates": 0}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkpoint_path = root / "checkpoint.pt"
            pack_path = root / "model.nqsrpack"
            torch.save(checkpoint, checkpoint_path)
            report = export_checkpoint(checkpoint_path, pack_path)
            validation = validate_pack(pack_path)
            self.assertEqual(report["sha256"], validation["sha256"])
            self.assertGreater(validation["tensor_count"], 0)
            self.assertTrue(validation["valid"])

    def test_qrisp_import_requires_explicit_license_and_converts_modalities(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            output = root / "converted"
            manifest_path = root / "qrisp.json"
            manifest_path.write_text(json.dumps({"source_root": "source", "segments": []}),
                                     encoding="utf-8")
            with self.assertRaises(PermissionError):
                import_manifest(manifest_path, output, license_confirmed=False)

            frames = []
            for index in range(2):
                low = np.full((3, 4, 3), 128 + index, dtype=np.uint8)
                high = np.full((6, 8, 3), 96 + index, dtype=np.uint8)
                depth = np.zeros((3, 4, 4), dtype=np.uint8)
                depth[..., 0] = 128
                Image.fromarray(low, mode="RGB").save(source / f"low_{index}.png")
                Image.fromarray(high, mode="RGB").save(source / f"high_{index}.png")
                Image.fromarray(depth, mode="RGBA").save(source / f"depth_{index}.png")
                vertical = np.full((3, 4), 0.25, dtype=np.float32)
                horizontal = np.full((3, 4), 0.5, dtype=np.float32)
                exr_path = source / f"motion_{index}.exr"
                with OpenEXR.File({"compression": OpenEXR.NO_COMPRESSION,
                                   "type": OpenEXR.scanlineimage},
                                  {"R": vertical, "G": horizontal}) as exr:
                    exr.write(str(exr_path))
                frames.append({"lr_color": f"low_{index}.png",
                               "hr_target": f"high_{index}.png",
                               "depth_png": f"depth_{index}.png",
                               "motion_exr": f"motion_{index}.exr",
                               "jitter": [0.0, 0.0]})
            manifest_path.write_text(json.dumps({
                "source_root": "source",
                "segments": [{"name": "synthetic_qrisp", "scale": 2,
                              "motion_channels": {"vertical": "R", "horizontal": "G"},
                              "frames": frames}],
            }), encoding="utf-8")
            result = import_manifest(manifest_path, output, license_confirmed=True)
            self.assertEqual(result["frame_count"], 2)
            with np.load(output / "qrisp_0000.npz", allow_pickle=False) as archive:
                motion = archive["motion"]
                depth = archive["depth"]
                self.assertTrue(np.allclose(motion[..., 0], 2.0))
                self.assertTrue(np.allclose(motion[..., 1], -0.75))
                self.assertTrue(np.allclose(depth, 128.0 / 255.0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
