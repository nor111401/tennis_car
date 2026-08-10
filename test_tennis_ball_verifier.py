import unittest
from pathlib import Path

import numpy as np

from tennis_ball_verifier import (
    TennisBallVerifier,
    expanded_crop,
    extract_features,
    resize_bilinear,
)


class TennisBallVerifierTests(unittest.TestCase):
    def test_resize_and_features_are_finite(self):
        image = np.zeros((20, 30, 3), dtype=np.uint8)
        image[:, :, 1] = 200
        resized = resize_bilinear(image)
        features = extract_features(image)

        self.assertEqual(resized.shape, (32, 32, 3))
        self.assertEqual(features.shape, (3092,))
        self.assertTrue(np.isfinite(features).all())

    def test_expanded_crop_stays_inside_image(self):
        image = np.zeros((40, 50, 3), dtype=np.uint8)
        crop = expanded_crop(image, (-5.0, -4.0, 12.0, 10.0))
        self.assertGreater(crop.shape[0], 0)
        self.assertGreater(crop.shape[1], 0)
        self.assertLessEqual(crop.shape[0], image.shape[0])
        self.assertLessEqual(crop.shape[1], image.shape[1])

    def test_exported_model_loads_and_scores(self):
        model_path = Path(__file__).with_name("tennis_ball_verifier.npz")
        if not model_path.exists():
            self.skipTest("Exported verifier model is not present")

        model = TennisBallVerifier(model_path)
        image = np.zeros((48, 48, 3), dtype=np.uint8)
        probability = model.predict_probability(image)

        self.assertEqual(model.weights.shape, (3092,))
        self.assertAlmostEqual(model.threshold, 0.70, places=5)
        self.assertGreaterEqual(probability, 0.0)
        self.assertLessEqual(probability, 1.0)


if __name__ == "__main__":
    unittest.main()
