from __future__ import annotations

import unittest

import cv2
import numpy as np

from tennis_candidate_filter import (
    CandidateFilterConfig,
    TargetConfirmation,
    evaluate_candidate,
    find_color_candidate_boxes,
    tennis_color_coverage,
)


CONFIG = CandidateFilterConfig()
DETECTION = {
    "x": 20,
    "y": 20,
    "width": 60,
    "height": 60,
    "value": 0.98,
    "label": "tennis_ball",
}


class CandidateFilterTests(unittest.TestCase):
    def test_default_confidence_is_seventy_percent(self) -> None:
        self.assertEqual(CONFIG.confidence_threshold, 0.70)

    def test_default_minimum_area_rejects_pixel_noise(self) -> None:
        self.assertEqual(CONFIG.object_area_min, 0.0005)

    def test_default_saturation_excludes_pale_floor_colors(self) -> None:
        self.assertEqual(CONFIG.saturation_min, 70)

    def test_close_threshold_is_sixty_percent(self) -> None:
        self.assertEqual(CONFIG.close_color_coverage, 0.60)

    def test_yellow_green_circle_is_accepted(self) -> None:
        image = np.zeros((200, 200, 3), dtype=np.uint8)
        cv2.circle(image, (100, 100), 48, (210, 255, 40), -1)
        metrics = evaluate_candidate(image, DETECTION, 100, 100, CONFIG)
        self.assertTrue(metrics.accepted, metrics)
        self.assertGreater(metrics.object_area_ratio, 0.10)

    def test_red_circle_is_rejected(self) -> None:
        image = np.zeros((200, 200, 3), dtype=np.uint8)
        cv2.circle(image, (100, 100), 48, (255, 30, 30), -1)
        metrics = evaluate_candidate(image, DETECTION, 100, 100, CONFIG)
        self.assertFalse(metrics.accepted)
        self.assertIn("tennis_color", metrics.reasons)

    def test_tiny_yellow_green_dot_is_rejected(self) -> None:
        image = np.zeros((1000, 1000, 3), dtype=np.uint8)
        cv2.circle(image, (500, 500), 10, (210, 255, 40), -1)
        metrics = evaluate_candidate(image, DETECTION, 100, 100, CONFIG)
        self.assertFalse(metrics.accepted)
        self.assertIn("too_small", metrics.reasons)

    def test_color_only_fallback_finds_yellow_green_circle(self) -> None:
        image = np.zeros((200, 200, 3), dtype=np.uint8)
        cv2.circle(image, (100, 100), 48, (210, 255, 40), -1)
        boxes = find_color_candidate_boxes(image, CONFIG, 1000)
        self.assertEqual(len(boxes), 1)
        self.assertEqual(boxes[0]["label"], "tennis_ball")
        self.assertEqual(boxes[0]["value"], 1.0)

    def test_color_only_fallback_ignores_red_circle(self) -> None:
        image = np.zeros((200, 200, 3), dtype=np.uint8)
        cv2.circle(image, (100, 100), 48, (255, 30, 30), -1)
        boxes = find_color_candidate_boxes(image, CONFIG, 1000)
        self.assertEqual(boxes, [])

    def test_color_only_fallback_ignores_orange_ball(self) -> None:
        image = np.zeros((200, 200, 3), dtype=np.uint8)
        cv2.circle(image, (100, 100), 48, (235, 145, 30), -1)
        boxes = find_color_candidate_boxes(image, CONFIG, 1000)
        self.assertEqual(boxes, [])

    def test_bright_yellow_square_is_rejected(self) -> None:
        image = np.zeros((200, 200, 3), dtype=np.uint8)
        cv2.rectangle(image, (40, 40), (159, 159), (210, 255, 40), -1)
        metrics = evaluate_candidate(image, DETECTION, 100, 100, CONFIG)
        self.assertFalse(metrics.accepted)
        self.assertIn("shape_fill", metrics.reasons)

    def test_trained_high_confidence_can_relax_ground_reflection_roundness(self) -> None:
        image = np.zeros((200, 200, 3), dtype=np.uint8)
        color = (210, 255, 40)
        cv2.circle(image, (100, 65), 35, color, -1)
        cv2.rectangle(image, (95, 85), (105, 180), color, -1)
        ground_config = CandidateFilterConfig(
            extent_min=0.10,
            extent_max=0.99,
            solidity_min=0.30,
            aspect_max=3.0,
        )
        ordinary_detection = {**DETECTION, "value": 0.90}
        trained_detection = {
            **ordinary_detection,
            "trained_verifier": True,
        }

        ordinary = evaluate_candidate(
            image, ordinary_detection, 100, 100, ground_config
        )
        trained = evaluate_candidate(
            image, trained_detection, 100, 100, ground_config
        )

        self.assertFalse(ordinary.accepted, ordinary)
        self.assertIn("not_round", ordinary.reasons)
        self.assertTrue(trained.accepted, trained)

    def test_low_confidence_trained_candidate_keeps_normal_roundness(self) -> None:
        image = np.zeros((200, 200, 3), dtype=np.uint8)
        color = (210, 255, 40)
        cv2.circle(image, (100, 65), 35, color, -1)
        cv2.rectangle(image, (95, 85), (105, 180), color, -1)
        ground_config = CandidateFilterConfig(
            confidence_threshold=0.70,
            extent_min=0.10,
            extent_max=0.99,
            solidity_min=0.30,
            aspect_max=3.0,
        )
        detection = {
            **DETECTION,
            "value": 0.75,
            "trained_verifier": True,
        }

        metrics = evaluate_candidate(image, detection, 100, 100, ground_config)

        self.assertFalse(metrics.accepted, metrics)
        self.assertIn("not_round", metrics.reasons)

    def test_target_requires_three_consistent_frames(self) -> None:
        tracker = TargetConfirmation(required_frames=3, max_jump=0.20)
        self.assertFalse(tracker.update(0.50, 0.50))
        self.assertFalse(tracker.update(0.51, 0.50))
        self.assertTrue(tracker.update(0.52, 0.51))
        tracker.reset()
        self.assertEqual(tracker.count, 0)

    def test_large_tennis_color_coverage_means_too_close(self) -> None:
        image = np.zeros((200, 200, 3), dtype=np.uint8)
        cv2.circle(image, (100, 100), 90, (210, 255, 40), -1)
        coverage = tennis_color_coverage(image, CONFIG)
        self.assertGreaterEqual(coverage, CONFIG.close_color_coverage)


if __name__ == "__main__":
    unittest.main()
