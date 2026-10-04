from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "naviprism"))
from sarm_reference import match_residual_motion  # noqa: E402


class SarmReferenceTests(unittest.TestCase):
    @staticmethod
    def make_surface(width: int, height: int) -> list[list[int]]:
        return [[1 + ((x * 31 + y * 67 + x * y * 13) % 254)
                 for x in range(width)] for y in range(height)]

    def test_recovers_integer_residual_around_engine_motion(self) -> None:
        history = self.make_surface(40, 32)
        current = self.make_surface(40, 32)
        dx, dy = 2, -1
        for y in range(32):
            for x in range(40):
                sx, sy = x + dx, y + dy
                if 0 <= sx < 40 and 0 <= sy < 32:
                    current[y][x] = history[sy][sx]

        result = match_residual_motion(current, history, 15, 14,
                                       engine_x=1, engine_y=0)
        self.assertTrue(result.valid)
        self.assertAlmostEqual(result.residual_x, 1.0, places=1)
        self.assertAlmostEqual(result.residual_y, -1.0, places=1)
        self.assertLessEqual(abs(result.residual_x - 1.0), 0.5)
        self.assertLessEqual(abs(result.residual_y + 1.0), 0.5)
        self.assertAlmostEqual(result.refined_x, 2.0, places=1)
        self.assertAlmostEqual(result.refined_y, -1.0, places=1)
        self.assertGreater(result.confidence, 0.0)
        self.assertEqual(result.best_cost, 0)

    def test_repeated_texture_reduces_uniqueness_confidence(self) -> None:
        current = [[100] * 24 for _ in range(24)]
        history = [[100] * 24 for _ in range(24)]
        result = match_residual_motion(current, history, 10, 10)
        self.assertTrue(result.valid)
        self.assertEqual(result.confidence, 0.0)
        self.assertEqual(result.ambiguity, 0.0)

    def test_zero_reference_bytes_are_masked(self) -> None:
        current = self.make_surface(20, 20)
        history = [row.copy() for row in current]
        current[10][10] = 0
        current[10][11] = 0
        result = match_residual_motion(current, history, 9, 9)
        self.assertTrue(result.valid)
        self.assertEqual(result.best_cost, 0)

    def test_rejects_out_of_bounds_current_and_empty_reference_patches(self) -> None:
        surface = self.make_surface(8, 8)
        edge = match_residual_motion(surface, surface, 6, 5)
        self.assertFalse(edge.valid)
        surface[2][2] = 0
        result = match_residual_motion([[0] * 4 for _ in range(4)], surface, 1, 1)
        self.assertFalse(result.valid)

    def test_rejects_invalid_luma_values(self) -> None:
        with self.assertRaises(ValueError):
            match_residual_motion([[256] * 4 for _ in range(4)],
                                  [[1] * 4 for _ in range(4)], 0, 0)


if __name__ == "__main__":
    unittest.main()
