import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image

try:
    from train_tennis_verifier import (
        LIGHTING_CONDITIONS,
        build_annotated_positive_samples,
        simulate_lighting,
        split_session_files,
    )
except ModuleNotFoundError:
    build_annotated_positive_samples = None
    LIGHTING_CONDITIONS = ()
    simulate_lighting = None
    split_session_files = None


@unittest.skipIf(
    build_annotated_positive_samples is None,
    "optional model-training dependencies are not installed",
)
class AnnotatedTrainingDataTests(unittest.TestCase):
    def test_explicit_background_is_negative_without_expanding_into_ball(self):
        from tennis_ball_verifier import extract_features
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            image = np.zeros((60, 80, 3), dtype=np.uint8)
            image[10:30, 20:40] = (210, 255, 40)
            image[30:50, 20:40] = (100, 120, 100)
            Image.fromarray(image).save(root / "scene.png")
            (root / "scene.json").write_text(json.dumps({
                "image": "scene.png", "width": 80, "height": 60,
                "objects": [{"label": "background", "bbox": {"x": 20, "y": 30, "width": 20, "height": 20}}],
            }), encoding="utf-8")
            features, labels, counts = build_annotated_positive_samples(
                root, augment=False, include_background=True,
            )
            self.assertEqual(labels, [0])
            self.assertEqual(counts["background_objects"], 1)
            np.testing.assert_array_equal(features[0], extract_features(image[30:50, 20:40]))
            self.assertEqual(build_annotated_positive_samples(root, augment=False)[1], [])

    def test_each_annotated_ball_becomes_a_positive_sample(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            scene = root / "two_balls"
            scene.mkdir()
            image = np.zeros((80, 120, 3), dtype=np.uint8)
            image[20:60, 15:55] = (210, 255, 40)
            image[25:65, 65:105] = (210, 255, 40)
            Image.fromarray(image).save(scene / "frame.jpg")
            (scene / "frame.json").write_text(json.dumps({
                "version": 1,
                "image": "frame.jpg",
                "width": 120,
                "height": 80,
                "object_count": 2,
                "objects": [
                    {
                        "label": "tennis_ball",
                        "bbox": {"x": 15, "y": 20, "width": 40, "height": 40},
                    },
                    {
                        "label": "tennis_ball",
                        "bbox": {"x": 65, "y": 25, "width": 40, "height": 40},
                    },
                ],
            }), encoding="utf-8")

            features, labels, counts = build_annotated_positive_samples(
                root,
                augment=False,
            )

        self.assertEqual(labels, [1, 1])
        self.assertEqual(len(features), 2)
        self.assertEqual(features[0].shape, (3092,))
        self.assertEqual(counts, {
            "frames": 1,
            "objects": 2,
            "positive_patches": 2,
        })

    def test_validation_split_holds_out_complete_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for session_name in ("session_1", "session_2", "session_3"):
                session = root / session_name
                session.mkdir()
                for frame_index in range(2):
                    Image.new("RGB", (8, 8)).save(
                        session / f"frame_{frame_index}.jpg"
                    )

            train, validation = split_session_files(root, 0.25)

        self.assertEqual({path.parent.name for path in train}, {"session_1", "session_2"})
        self.assertEqual({path.parent.name for path in validation}, {"session_3"})
        self.assertFalse(set(train) & set(validation))

    def test_lighting_augmentation_covers_dark_bright_and_color_temperature(self) -> None:
        patch = np.full((24, 24, 3), 128, dtype=np.uint8)
        dark = simulate_lighting(
            patch,
            "low_light",
            np.random.default_rng(1),
        )
        bright = simulate_lighting(
            patch,
            "overexposed",
            np.random.default_rng(1),
        )
        warm = simulate_lighting(
            patch,
            "warm_light",
            np.random.default_rng(1),
        )
        cool = simulate_lighting(
            patch,
            "cool_light",
            np.random.default_rng(1),
        )

        self.assertEqual(LIGHTING_CONDITIONS[0], "original")
        self.assertLess(float(dark.mean()), float(patch.mean()) * 0.7)
        self.assertGreater(float(bright.mean()), float(patch.mean()) * 1.15)
        self.assertGreater(float(warm[..., 0].mean()), float(warm[..., 2].mean()))
        self.assertGreater(float(cool[..., 2].mean()), float(cool[..., 0].mean()))


if __name__ == "__main__":
    unittest.main()
