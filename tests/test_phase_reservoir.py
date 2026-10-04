from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "naviprism"))
from phase_reservoir import PhaseHistoryReservoir  # noqa: E402


class PhaseReservoirTests(unittest.TestCase):
    def make_inputs(self, height: int = 3, width: int = 4):
        color = np.arange(height * width * 3, dtype=np.float32).reshape(height, width, 3)
        depth = np.ones((height, width), dtype=np.float32)
        valid = np.ones((height, width), dtype=bool)
        return color, depth, valid

    def test_four_phases_have_hr_history_color_capacity(self) -> None:
        reservoir = PhaseHistoryReservoir(height=3, width=4)
        color, depth, valid = self.make_inputs()
        for phase in range(4):
            reservoir.update(phase, color + phase, depth, valid)
        self.assertTrue(reservoir.color_storage_matches_hr_history)
        self.assertTrue(reservoir.valid.all())
        self.assertTrue(np.all(reservoir.age == 0))

    def test_reprojection_decays_confidence_and_increments_age(self) -> None:
        reservoir = PhaseHistoryReservoir(height=3, width=4)
        color, depth, valid = self.make_inputs()
        reservoir.update(2, color, depth, valid, np.full((3, 4), 0.8, np.float32))
        yy, xx = np.mgrid[0:3, 0:4].astype(np.float32)
        reservoir.reproject(xx, yy, depth, valid, confidence_decay=0.5)
        result = reservoir.evidence(2)
        self.assertTrue(result.valid.all())
        self.assertTrue(np.all(result.age == 1))
        self.assertTrue(np.allclose(result.confidence, 0.4))
        self.assertTrue(np.array_equal(result.color, color))

    def test_depth_disocclusion_invalid_motion_and_cut_reset(self) -> None:
        reservoir = PhaseHistoryReservoir(height=3, width=4)
        color, depth, valid = self.make_inputs()
        reservoir.update(0, color, depth, valid)
        yy, xx = np.mgrid[0:3, 0:4].astype(np.float32)
        changed_depth = depth.copy()
        changed_depth[1, 1] = 0.5
        valid[0, 0] = False
        reservoir.reproject(xx, yy, changed_depth, valid, depth_threshold=0.02)
        self.assertFalse(reservoir.valid[0, 1, 1])
        self.assertFalse(reservoir.valid[0, 0, 0])
        self.assertTrue(reservoir.valid[0, 2, 3])
        reservoir.reset()
        self.assertFalse(reservoir.valid.any())
        self.assertTrue(np.all(reservoir.confidence == 0))

    def test_phase_and_shape_validation(self) -> None:
        reservoir = PhaseHistoryReservoir(height=3, width=4)
        color, depth, valid = self.make_inputs()
        with self.assertRaisesRegex(ValueError, "phase"):
            reservoir.update(4, color, depth, valid)
        with self.assertRaisesRegex(ValueError, "match reservoir size"):
            reservoir.reproject(np.zeros((1, 1)), np.zeros((1, 1)), depth, valid)


if __name__ == "__main__":
    unittest.main()
