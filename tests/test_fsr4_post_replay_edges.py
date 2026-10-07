import unittest
import numpy as np
from tools.oracles.replay_fsr4_post import _post_sample_coordinates, replay_arrays


class TestFsr4PostEdgeSemantics(unittest.TestCase):
    def test_unsigned_distance_coordinate_and_signed_clamped_lookup(self):
        center = np.array([[0, 1]], dtype=np.int32)
        distance_coordinate, load_coordinate = _post_sample_coordinates(center, 0, 2)

        np.testing.assert_array_equal(
            distance_coordinate,
            np.array([[4294967296.0, 0.0]], dtype=np.float32),
        )
        np.testing.assert_array_equal(load_coordinate, np.array([[0, 0]], dtype=np.int32))

    def test_edge_replay_stays_finite(self):
        meta = {
            "output_height": 2,
            "output_width": 2,
            "render_height": 2,
            "render_width": 2,
            "jitter_current": [-0.49, -0.49],
            "exposure": 1.0,
            "pre_exposure": 1.0,
        }
        src = np.array([
            [[0.1, 0.2, 0.3], [0.8, 0.7, 0.6]],
            [[0.2, 0.3, 0.4], [0.9, 0.8, 0.7]],
        ], dtype=np.float32)
        hist = np.zeros((2, 2, 3), dtype=np.float32)
        params = np.zeros((2, 2, 4), dtype=np.float32)
        out, details = replay_arrays(meta, {
            "current_reconstruction_source": src,
            "reprojected_history": hist,
            "raw_model_parameters": params,
        })
        self.assertTrue(np.isfinite(out).all())
        self.assertEqual(details["nonfinite_replayed_model_pixels"], 0)


if __name__ == "__main__":
    unittest.main()
