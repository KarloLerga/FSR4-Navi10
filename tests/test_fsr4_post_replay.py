import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.oracles.replay_fsr4_post import replay_arrays


class Fsr4PostReplayTests(unittest.TestCase):
    def test_uniform_linear_input_round_trips_through_post(self):
        color = np.full((2, 2, 3), 0.25, dtype=np.float32)
        history = np.full((2, 2, 3), 0.1174 * np.log(1.0 + 150.0 * 0.25), dtype=np.float32)
        arrays = {
            "current_reconstruction_source": color,
            "reprojected_history": history,
            "raw_model_parameters": np.zeros((2, 2, 4), dtype=np.float32),
        }
        metadata = {
            "output_width": 2,
            "output_height": 2,
            "render_width": 2,
            "render_height": 2,
            "jitter_current": [0.0, 0.0],
            "exposure": 1.0,
            "pre_exposure": 1.0,
        }

        result, details = replay_arrays(metadata, arrays)

        self.assertEqual(result.shape, color.shape)
        self.assertTrue(np.isfinite(result).all())
        self.assertTrue(np.allclose(result.astype(np.float32), color, atol=1e-5, rtol=0.0))
        self.assertEqual(details["nonfinite_replayed_model_pixels"], 0)


if __name__ == "__main__":
    unittest.main()
