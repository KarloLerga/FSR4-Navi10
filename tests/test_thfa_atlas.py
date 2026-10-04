from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "naviprism"))
from thfa_atlas import (  # noqa: E402
    FEATURE_COUNT,
    PHASE_BUCKETS,
    SPATIAL_BUCKETS,
    TEMPORAL_BUCKETS,
    fit_thfa_atlas,
    load_thfa_atlas,
    make_training_features,
    predict_thfa,
    prepare_thfa_capture,
    spatial_descriptor,
    temporal_descriptor,
    write_thfa_atlas,
)


class ThfaAtlasTests(unittest.TestCase):
    @staticmethod
    def dataset() -> tuple[np.ndarray, ...]:
        rng = np.random.default_rng(721)
        rows = 6144
        features = rng.normal(0.0, 0.15, size=(rows, FEATURE_COUNT))
        features[:, 0] = 1.0
        spatial = rng.integers(0, 4, size=rows)
        temporal = rng.integers(0, 4, size=rows)
        phase = rng.integers(0, PHASE_BUCKETS, size=rows)
        spatial_weights = rng.normal(0.0, 0.02, size=(4, FEATURE_COUNT))
        temporal_weights = rng.normal(0.0, 0.005, size=(4, FEATURE_COUNT))
        phase_weights = rng.normal(0.0, 0.002, size=(PHASE_BUCKETS, FEATURE_COUNT))
        residual = (np.einsum("ij,ij->i", features, spatial_weights[spatial])
                    + np.einsum("ij,ij->i", features, temporal_weights[temporal])
                    + np.einsum("ij,ij->i", features, phase_weights[phase]))
        return features, residual, spatial, temporal, phase

    def test_factorized_fit_predict_and_sparse_bucket_backoff(self) -> None:
        features, residual, spatial, temporal, phase = self.dataset()
        atlas = fit_thfa_atlas(features, residual, spatial, temporal, phase,
                               regularization=1.0e-7, minimum_samples=24,
                               teacher_id="synthetic-fit-check",
                               source_identity="deterministic test data")
        prediction = predict_thfa(atlas, features, spatial, temporal, phase)
        rmse = float(np.sqrt(np.mean((prediction - residual) ** 2)))
        self.assertLess(rmse, 0.003)
        self.assertEqual(atlas.spatial.shape, (SPATIAL_BUCKETS, FEATURE_COUNT))
        self.assertEqual(atlas.temporal.shape, (TEMPORAL_BUCKETS, FEATURE_COUNT))
        self.assertEqual(atlas.phase.shape, (PHASE_BUCKETS, FEATURE_COUNT))
        self.assertEqual(atlas.metadata["teacher_id"], "synthetic-fit-check")
        self.assertTrue(np.array_equal(atlas.spatial[400], atlas.spatial[401]))

    def test_fp16_pack_round_trip_and_hash_validation(self) -> None:
        features, residual, spatial, temporal, phase = self.dataset()
        atlas = fit_thfa_atlas(features, residual, spatial, temporal, phase,
                               regularization=1.0e-5, minimum_samples=24,
                               teacher_id="synthetic-fit-check",
                               source_identity="deterministic test data")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "demo.thfa"
            manifest = write_thfa_atlas(path, atlas)
            loaded = load_thfa_atlas(path)
            self.assertEqual(manifest["atlas_sha256"], loaded.metadata["atlas_sha256"])
            self.assertEqual(loaded.spatial.dtype, np.float32)
            quantized_prediction = predict_thfa(loaded, features, spatial, temporal, phase)
            self.assertLess(float(np.sqrt(np.mean((quantized_prediction - residual) ** 2))),
                            0.004)
            corrupted = bytearray(path.read_bytes())
            corrupted[-1] ^= 0xff
            path.write_bytes(corrupted)
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                load_thfa_atlas(path)

    def test_descriptors_and_training_feature_layout(self) -> None:
        flat = np.full((3, 3), 0.35)
        self.assertEqual(spatial_descriptor(flat), 0)
        self.assertTrue(0 <= spatial_descriptor(np.arange(9).reshape(3, 3) / 10.0)
                        < SPATIAL_BUCKETS)
        self.assertEqual(temporal_descriptor(0.5, 0.9, False, True), 13)
        self.assertEqual(temporal_descriptor(9.0, 0.1, True, False), 34)
        neighborhoods = np.arange(18, dtype=np.float64).reshape(2, 3, 3)
        baseline = np.array([4.0, 9.0])
        features = make_training_features(neighborhoods, baseline)
        self.assertEqual(features.shape, (2, FEATURE_COUNT))
        self.assertTrue(np.array_equal(features[:, 0], np.ones(2)))
        self.assertTrue(np.array_equal(features[0, 1:], neighborhoods[0].reshape(-1) - 4.0))
        rgb_neighborhoods = np.arange(54, dtype=np.float64).reshape(2, 3, 3, 3) / 100.0
        rgb_baseline = np.array([[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]])
        rgb_target = rgb_baseline + np.array([[0.01, 0.02, 0.03], [0.04, 0.05, 0.06]])
        prepared = prepare_thfa_capture({
            "current_neighborhood": rgb_neighborhoods,
            "bilinear_baseline": rgb_baseline,
            "teacher_target": rgb_target,
            "spatial_bucket": np.array([3, 7]),
            "temporal_bucket": np.array([1, 2]),
            "phase_bucket": np.array([0, 3]),
        })
        self.assertEqual(prepared["features"].shape, (6, FEATURE_COUNT))
        self.assertEqual(prepared["residual"].shape, (6,))
        self.assertTrue(np.allclose(prepared["residual"],
                                    [0.01, 0.02, 0.03, 0.04, 0.05, 0.06]))
        self.assertEqual(prepared["spatial_bucket"].tolist(), [3, 3, 3, 7, 7, 7])

    def test_spatial_orientation_axes_match_descriptor_bins(self) -> None:
        horizontal = np.tile(np.array([0.0, 0.1, 0.2]), (3, 1))
        vertical = horizontal.T
        diagonal = np.fromfunction(lambda y, x: (x + y) / 20.0, (3, 3))
        self.assertEqual(spatial_descriptor(horizontal) // 64, 0)
        self.assertEqual(spatial_descriptor(vertical) // 64, 4)
        self.assertEqual(spatial_descriptor(diagonal) // 64, 2)

    def test_invalid_training_metadata_and_bucket_indices_are_rejected(self) -> None:
        features = np.ones((8, FEATURE_COUNT), dtype=np.float64)
        residual = np.zeros(8)
        spatial = np.zeros(8, dtype=np.int64)
        temporal = np.zeros(8, dtype=np.int64)
        phase = np.zeros(8, dtype=np.int64)
        phase[0] = PHASE_BUCKETS
        with self.assertRaisesRegex(ValueError, "phase descriptor"):
            fit_thfa_atlas(features, residual, spatial, temporal, phase)
        with self.assertRaisesRegex(ValueError, "same row count"):
            spatial = np.zeros(8, dtype=np.int64)
            fit_thfa_atlas(features, residual, spatial, temporal, phase[:0])


if __name__ == "__main__":
    unittest.main()
