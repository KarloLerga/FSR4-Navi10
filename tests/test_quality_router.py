from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "naviprism"))
from quality_router import Route, TileEvidence, classify_tile, route_tiles  # noqa: E402


class QualityRouterTests(unittest.TestCase):
    def test_easy_requires_high_confidence_and_safe_history(self) -> None:
        self.assertIs(classify_tile(TileEvidence(True, 0.9)), Route.EASY)
        self.assertIs(classify_tile(TileEvidence(True, 0.84)), Route.MEDIUM)
        self.assertIs(classify_tile(TileEvidence(True, 0.9, history_valid=False)), Route.HARD)
        self.assertIs(classify_tile(TileEvidence(True, 0.95, reactive=True)), Route.HARD)
        self.assertIs(classify_tile(TileEvidence(True, 0.95, thin_detail=True)), Route.HARD)

    def test_ambiguous_or_invalid_tiles_take_expensive_fallback(self) -> None:
        self.assertIs(classify_tile(TileEvidence(True, 0.19)), Route.VERY_HARD)
        self.assertIs(classify_tile(TileEvidence(False, 0.99)), Route.VERY_HARD)
        self.assertIs(classify_tile(TileEvidence(True, 0.8, disocclusion=0.8)), Route.VERY_HARD)
        self.assertIs(classify_tile(TileEvidence(True, 0.8, disocclusion=0.2)), Route.HARD)
        self.assertIs(classify_tile(TileEvidence(True, 0.8, disocclusion=0.1)), Route.MEDIUM)
        self.assertIs(classify_tile(TileEvidence(True, 0.0, force_reference=True)),
                      Route.REFERENCE)

    def test_sparse_lists_and_route_fractions_are_deterministic(self) -> None:
        summary = route_tiles((
            TileEvidence(True, 0.95),
            TileEvidence(True, 0.75),
            TileEvidence(True, 0.5),
            TileEvidence(False, 0.1),
            TileEvidence(True, 0.0, force_reference=True),
        ))
        self.assertEqual(summary.hard_tiles, (2,))
        self.assertEqual(summary.very_hard_tiles, (3,))
        self.assertEqual(summary.fractions, (0.2, 0.2, 0.2, 0.2, 0.2))
        self.assertEqual(summary, route_tiles((
            TileEvidence(True, 0.95), TileEvidence(True, 0.75),
            TileEvidence(True, 0.5), TileEvidence(False, 0.1),
            TileEvidence(True, 0.0, force_reference=True))))

    def test_invalid_measurements_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "confidence"):
            classify_tile(TileEvidence(True, 1.1))
        with self.assertRaisesRegex(ValueError, "disocclusion"):
            classify_tile(TileEvidence(True, 0.8, disocclusion=-0.1))


if __name__ == "__main__":
    unittest.main()
