from __future__ import annotations

import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

from tennis_candidate_filter import (
    CandidateMetrics,
    CandidateFilterConfig,
    MultiBallTracker,
    TemporalTargetTracker,
    TargetConfirmation,
    build_candidate_masks,
    evaluate_candidate,
    find_color_candidate_boxes,
    resolve_verified_circle_splits,
    select_nearest_candidate,
    tennis_color_coverage,
)
from tennis_ball_rpi import (
    draw_target_center_markers,
    process_bounding_boxes,
    recover_missing_tracked_candidates,
    recover_tracked_candidate,
    should_draw_filtered_contour,
    target_center_marker_color,
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
    def _single_ball_touching_background(self):
        image = np.zeros((240, 240, 3), dtype=np.uint8)
        cv2.rectangle(image, (20, 60), (220, 90), (100, 135, 90), -1)
        cv2.circle(image, (120, 120), 30, (210, 255, 40), -1)
        # Component starts at (20,60), padding=16; local ball center=(116,76).
        circles = np.array([[[116.0, 76.0, 30.0]]], dtype=np.float32)
        with patch(
            "tennis_candidate_filter.cv2.HoughCircles",
            side_effect=[None, circles],
        ):
            boxes = find_color_candidate_boxes(image, CONFIG, 1000)
        return image, boxes

    def test_single_ball_on_color_background_gets_local_saturation_proposal(self):
        _, boxes = self._single_ball_touching_background()
        children = [box for box in boxes if box.get("background_split_candidate")]
        self.assertGreaterEqual(len(children), 1, boxes)
        self.assertFalse(children[0].get("highlight_candidate"))
        self.assertIsNotNone(children[0].get("saturation_split_min"))
        self.assertAlmostEqual(children[0]["x"] + children[0]["width"] / 2, 500, delta=3)
        self.assertTrue(any(box.get("circle_split_parent_candidate") for box in boxes))

    def test_background_split_requires_trained_verifier(self):
        image, boxes = self._single_ball_touching_background()
        child = next(box for box in boxes if box.get("background_split_candidate"))
        metrics = evaluate_candidate(image, child, 1000, 1000, CONFIG)
        self.assertFalse(metrics.accepted)
        self.assertEqual(metrics.reasons, ("requires_verifier",))

    def test_background_split_uses_ordinary_confidence_not_glare_threshold(self):
        image, boxes = self._single_ball_touching_background()
        child = next(box for box in boxes if box.get("background_split_candidate"))
        child.update(trained_verifier=True, value=0.69)
        metrics = evaluate_candidate(image, child, 1000, 1000, CONFIG)
        self.assertEqual(metrics.reasons, ("confidence",))
        child["value"] = 0.80
        self.assertTrue(evaluate_candidate(image, child, 1000, 1000, CONFIG).accepted)

    def test_verified_single_child_survives_when_background_parent_fails(self):
        image, boxes = self._single_ball_touching_background()
        for box in boxes:
            box.update(trained_verifier=True, value=0.80 if box.get("background_split_candidate") else 0.10)
        accepted = resolve_verified_circle_splits([
            (box, metrics) for box in boxes
            if (metrics := evaluate_candidate(image, box, 1000, 1000, CONFIG)).accepted
        ])
        self.assertEqual(len(accepted), 1)
        self.assertTrue(accepted[0][0].get("background_split_candidate"))
        self.assertLess(accepted[0][1].object_area_ratio, 0.06)

    def test_background_single_circle_does_not_duplicate_valid_parent(self):
        image, boxes = self._single_ball_touching_background()
        child = next(box for box in boxes if box.get("background_split_candidate"))
        child.update(trained_verifier=True, value=0.80)
        parent = next(box for box in boxes if box.get("circle_split_parent_candidate"))
        # Resolve policy receives already-accepted parents, independently of
        # this deliberately elongated test image's strict shape rejection.
        parent_metrics = evaluate_candidate(image, child, 1000, 1000, CONFIG)
        accepted = resolve_verified_circle_splits([(parent, parent_metrics), (child, parent_metrics)])
        self.assertEqual(len(accepted), 1)
        self.assertIs(accepted[0][0], parent)

    def test_saturation_alternatives_are_one_ball_after_model_validation(self):
        image, boxes = self._single_ball_touching_background()
        children = [box for box in boxes if box.get("background_split_candidate")]
        self.assertGreater(len(children), 1)
        for index, box in enumerate(children):
            box.update(trained_verifier=True, value=0.80 + index * 0.01)
        accepted = resolve_verified_circle_splits([
            (box, evaluate_candidate(image, box, 1000, 1000, CONFIG)) for box in children
        ])
        self.assertEqual(len(accepted), 1)
        self.assertIs(accepted[0][0], children[-1])

    def test_verified_color_child_replaces_inflated_background_parent(self):
        image, boxes = self._single_ball_touching_background()
        parent = next(box for box in boxes if box.get("circle_split_parent_candidate"))
        child = next(box for box in boxes if box.get("background_split_candidate"))
        child.update(trained_verifier=True, value=0.95)
        metrics = evaluate_candidate(image, child, 1000, 1000, CONFIG)
        parent_metrics = replace(metrics, object_area_ratio=metrics.object_area_ratio * 2)
        accepted = resolve_verified_circle_splits([(parent, parent_metrics), (child, metrics)])
        self.assertEqual(len(accepted), 1)
        self.assertIs(accepted[0][0], child)

    def test_near_square_irregular_background_can_also_be_split(self):
        image = np.zeros((240, 240, 3), dtype=np.uint8)
        cv2.rectangle(image, (94, 80), (155, 95), (100, 135, 90), -1)
        cv2.circle(image, (120, 120), 30, (210, 255, 40), -1)
        with patch("tennis_candidate_filter.cv2.HoughCircles", return_value=None):
            boxes = find_color_candidate_boxes(image, CONFIG, 1000)
        self.assertTrue(any(box.get("saturation_split_min") for box in boxes), boxes)

    def test_white_background_without_color_cannot_use_saturation_split(self):
        image = np.full((240, 240, 3), 220, dtype=np.uint8)
        with patch("tennis_candidate_filter.cv2.HoughCircles", return_value=None):
            boxes = find_color_candidate_boxes(image, CONFIG, 1000)
        self.assertFalse(any(box.get("background_split_candidate") for box in boxes))

    def test_confirmed_ball_keeps_bottom_exit_observation_field(self) -> None:
        image = np.zeros((200, 200, 3), dtype=np.uint8)
        cv2.circle(image, (100, 100), 48, (210, 255, 40), -1)
        result = {"result": {"bounding_boxes": [DETECTION]}}
        confirmation = TargetConfirmation(required_frames=3, max_jump=0.20)
        tracker = MultiBallTracker(smoothing_alpha=1.0)

        for frame_index in range(3):
            _, position, _, _, observation = process_bounding_boxes(
                result,
                image,
                100,
                100,
                confirmation,
                tracker,
                log_events=False,
            )
            if frame_index < 2:
                self.assertEqual(observation["vision_status"], "VERIFYING")

        self.assertEqual(position, "CENTER")
        self.assertTrue(observation["detected"])
        self.assertEqual(observation["vision_status"], "CONFIRMED")
        self.assertIs(observation["bottom_exit_loss"], False)
        self.assertIsNotNone(observation["ball_y"])
        self.assertIsNotNone(observation["ball_height"])

    def test_vision_reason_distinguishes_empty_rejected_and_too_close_without_relaxing_loss(self) -> None:
        image = np.zeros((200, 200, 3), dtype=np.uint8)
        for boxes, close, expected in (
            ([], False, "EMPTY"), ([DETECTION], False, "REJECTED:"),
            ([], True, "TOO_CLOSE"),
        ):
            with self.subTest(expected=expected), patch(
                "tennis_ball_rpi.tennis_color_coverage", return_value=0.8 if close else 0.0,
            ):
                _, position, area, _, observation = process_bounding_boxes(
                    {"result": {"bounding_boxes": boxes}}, image, 100, 100,
                    TargetConfirmation(3, 0.20), MultiBallTracker(), log_events=False,
                )
            self.assertEqual(position, "LOST")
            self.assertTrue(observation["vision_status"].startswith(expected))
            self.assertEqual(observation["bottom_exit_loss"], expected == "EMPTY")
            self.assertEqual(area, 1.0 if close else 0.0)

    def test_synthetic_circle_contour_is_hidden_from_video(self) -> None:
        self.assertFalse(should_draw_filtered_contour({
            "circle_candidate": True,
        }))

    def test_verified_split_circle_contour_is_hidden_from_video(self) -> None:
        self.assertFalse(should_draw_filtered_contour({
            "circle_candidate": True,
            "circle_split_candidate": True,
        }))

    def test_real_color_contour_is_hidden_from_video(self) -> None:
        self.assertFalse(should_draw_filtered_contour({
            "color_candidate": True,
        }))

    def test_primary_center_is_red_and_other_ball_center_is_blue(self) -> None:
        primary = SimpleNamespace(track_id=1, center_x=0.25, center_y=0.50)
        farther = SimpleNamespace(track_id=2, center_x=0.75, center_y=0.50)
        display = np.zeros((100, 100, 3), dtype=np.uint8)

        self.assertEqual(target_center_marker_color(primary, primary), (0, 0, 255))
        self.assertEqual(target_center_marker_color(farther, primary), (255, 0, 0))
        draw_target_center_markers(
            display,
            (primary, farther),
            primary,
            100,
            100,
            1.0,
            1.0,
        )

        self.assertTupleEqual(tuple(display[50, 25]), (0, 0, 255))
        self.assertTupleEqual(tuple(display[50, 75]), (255, 0, 0))

    def test_default_confidence_is_seventy_percent(self) -> None:
        self.assertEqual(CONFIG.confidence_threshold, 0.70)

    def test_default_minimum_area_rejects_pixel_noise(self) -> None:
        self.assertEqual(CONFIG.object_area_min, 0.0005)

    def test_default_saturation_excludes_pale_floor_colors(self) -> None:
        self.assertEqual(CONFIG.saturation_min, 70)

    def test_close_threshold_is_sixty_percent(self) -> None:
        self.assertEqual(CONFIG.close_color_coverage, 0.60)

    def test_nearest_candidate_uses_largest_verified_area(self) -> None:
        far_box = {"value": 0.99, "x": 100, "y": 100}
        near_box = {"value": 0.80, "x": 700, "y": 700}
        far_metrics = CandidateMetrics(
            True, 0.3, 0.9, 0.8, 0.9, 1.0, 0.03,
            (100.0, 100.0), None, (),
        )
        near_metrics = CandidateMetrics(
            True, 0.3, 0.9, 0.8, 0.9, 1.0, 0.12,
            (700.0, 700.0), None, (),
        )

        selected = select_nearest_candidate([
            (far_box, far_metrics),
            (near_box, near_metrics),
        ])

        self.assertIsNotNone(selected)
        self.assertIs(selected[0], near_box)
        self.assertIs(selected[1], near_metrics)

    def test_nearest_candidate_uses_confidence_only_for_area_ties(self) -> None:
        lower_confidence = {"value": 0.80}
        higher_confidence = {"value": 0.99}
        metrics = CandidateMetrics(
            True, 0.3, 0.9, 0.8, 0.9, 1.0, 0.08,
            (500.0, 500.0), None, (),
        )

        selected = select_nearest_candidate([
            (lower_confidence, metrics),
            (higher_confidence, metrics),
        ])

        self.assertIsNotNone(selected)
        self.assertIs(selected[0], higher_confidence)

    @staticmethod
    def _tracked_item(
        source: str,
        center_x: float,
        center_y: float,
        area: float,
        size: float,
        confidence: float = 0.95,
    ):
        box = {
            "value": confidence,
            "x": (center_x - size / 2.0) * 1000,
            "y": (center_y - size / 2.0) * 1000,
            "width": size * 1000,
            "height": size * 1000,
        }
        if source == "color":
            box["color_candidate"] = True
        else:
            box["highlight_candidate"] = True
            box["circle_candidate"] = True
        metrics = CandidateMetrics(
            True,
            0.5,
            0.8,
            0.7,
            0.9,
            1.0,
            area,
            (center_x * 1000, center_y * 1000),
            None,
            (),
        )
        return box, metrics

    def test_tracker_prefers_color_geometry_for_same_ball(self) -> None:
        tracker = TemporalTargetTracker()
        color = self._tracked_item("color", 0.50, 0.50, 0.04, 0.20)
        glare = self._tracked_item("glare", 0.51, 0.50, 0.07, 0.26)

        tracked = tracker.update([glare, color], 1000, 1000, 1000, 1000)

        self.assertEqual(tracked.source, "color")
        self.assertIs(tracked.display_item[0], color[0])

    def test_tracker_does_not_switch_on_alternating_sources(self) -> None:
        tracker = TemporalTargetTracker()
        color = self._tracked_item("color", 0.50, 0.50, 0.04, 0.20)
        glare = self._tracked_item("glare", 0.51, 0.50, 0.07, 0.26)

        first = tracker.update([color], 1000, 1000, 1000, 1000)
        second = tracker.update([glare], 1000, 1000, 1000, 1000)
        third = tracker.update([color], 1000, 1000, 1000, 1000)

        self.assertEqual(first.source, "color")
        self.assertEqual(second.source, "color")
        self.assertIs(second.display_item[0], color[0])
        self.assertEqual(third.source, "color")

    def test_tracker_uses_glare_after_two_consecutive_frames(self) -> None:
        tracker = TemporalTargetTracker()
        color = self._tracked_item("color", 0.50, 0.50, 0.04, 0.20)
        glare_one = self._tracked_item("glare", 0.51, 0.50, 0.07, 0.26)
        glare_two = self._tracked_item("glare", 0.52, 0.50, 0.07, 0.26)

        tracker.update([color], 1000, 1000, 1000, 1000)
        waiting = tracker.update([glare_one], 1000, 1000, 1000, 1000)
        fallback = tracker.update([glare_two], 1000, 1000, 1000, 1000)

        self.assertEqual(waiting.source, "color")
        self.assertEqual(fallback.source, "glare")
        self.assertIs(fallback.display_item[0], glare_two[0])

    def test_tracker_requires_three_color_frames_to_leave_glare(self) -> None:
        tracker = TemporalTargetTracker()
        glare = self._tracked_item("glare", 0.50, 0.50, 0.07, 0.26)
        colors = [
            self._tracked_item("color", 0.50, 0.50, 0.04, 0.20)
            for _ in range(3)
        ]

        tracker.update([glare], 1000, 1000, 1000, 1000)
        first = tracker.update([colors[0]], 1000, 1000, 1000, 1000)
        second = tracker.update([colors[1]], 1000, 1000, 1000, 1000)
        third = tracker.update([colors[2]], 1000, 1000, 1000, 1000)

        self.assertEqual(first.source, "glare")
        self.assertEqual(second.source, "glare")
        self.assertEqual(third.source, "color")

    def test_tracker_smooths_center_and_area(self) -> None:
        tracker = TemporalTargetTracker(smoothing_alpha=0.25)
        first = self._tracked_item("color", 0.40, 0.50, 0.04, 0.20)
        second = self._tracked_item("color", 0.50, 0.50, 0.08, 0.28)

        tracker.update([first], 1000, 1000, 1000, 1000)
        tracked = tracker.update([second], 1000, 1000, 1000, 1000)

        self.assertAlmostEqual(tracked.center_x, 0.425)
        self.assertAlmostEqual(tracked.area_ratio, 0.05)

    def test_temporal_recovery_uses_current_moved_contour(self) -> None:
        tracker = TemporalTargetTracker()
        previous = self._tracked_item(
            "color", 0.50, 0.50, 0.05, 0.25, confidence=0.99
        )
        tracker.update([previous], 1000, 1000, 1000, 1000)
        image = np.zeros((240, 240, 3), dtype=np.uint8)
        cv2.circle(image, (132, 120), 30, (210, 255, 40), -1)
        color_mask, highlight_mask = build_candidate_masks(image, CONFIG)

        recovered = recover_tracked_candidate(
            image,
            tracker,
            1000,
            1000,
            color_mask=color_mask,
            highlight_mask=highlight_mask,
        )

        self.assertIsNotNone(recovered)
        detection, metrics = recovered
        self.assertTrue(detection["temporal_recovery_candidate"])
        self.assertAlmostEqual(detection["value"], 0.99 * 0.85)
        self.assertAlmostEqual(metrics.object_center[0] / 240.0, 0.55, places=2)

    def test_temporal_recovery_never_draws_without_current_evidence(self) -> None:
        tracker = TemporalTargetTracker()
        previous = self._tracked_item(
            "color", 0.50, 0.50, 0.05, 0.25, confidence=0.99
        )
        tracker.update([previous], 1000, 1000, 1000, 1000)
        image = np.zeros((240, 240, 3), dtype=np.uint8)
        color_mask, highlight_mask = build_candidate_masks(image, CONFIG)

        recovered = recover_tracked_candidate(
            image,
            tracker,
            1000,
            1000,
            color_mask=color_mask,
            highlight_mask=highlight_mask,
        )

        self.assertIsNone(recovered)

    def test_temporal_recovery_confidence_stops_at_tracking_floor(self) -> None:
        tracker = TemporalTargetTracker()
        previous = self._tracked_item(
            "color", 0.50, 0.50, 0.05, 0.25, confidence=0.71
        )
        tracker.update([previous], 1000, 1000, 1000, 1000)
        image = np.zeros((240, 240, 3), dtype=np.uint8)
        cv2.circle(image, (120, 120), 30, (210, 255, 40), -1)
        color_mask, highlight_mask = build_candidate_masks(image, CONFIG)

        recovered = recover_tracked_candidate(
            image,
            tracker,
            1000,
            1000,
            color_mask=color_mask,
            highlight_mask=highlight_mask,
        )

        self.assertIsNotNone(recovered)
        self.assertAlmostEqual(
            recovered[0]["value"],
            CONFIG.confidence_threshold,
        )

    def test_tracker_handles_numpy_contours_when_switching_targets(self) -> None:
        tracker = TemporalTargetTracker()
        first_box, first_metrics = self._tracked_item(
            "color", 0.20, 0.50, 0.02, 0.14
        )
        second_box, second_metrics = self._tracked_item(
            "color", 0.75, 0.50, 0.08, 0.28
        )
        first_contour = np.array(
            [[[130, 430]], [[270, 430]], [[270, 570]], [[130, 570]]],
            dtype=np.int32,
        )
        second_contour = np.array(
            [[[610, 360]], [[890, 360]], [[890, 640]], [[610, 640]]],
            dtype=np.int32,
        )
        first_metrics = CandidateMetrics(
            first_metrics.accepted,
            first_metrics.color_ratio,
            first_metrics.circularity,
            first_metrics.extent,
            first_metrics.solidity,
            first_metrics.aspect,
            first_metrics.object_area_ratio,
            first_metrics.object_center,
            first_contour,
            first_metrics.reasons,
        )
        second_metrics = CandidateMetrics(
            second_metrics.accepted,
            second_metrics.color_ratio,
            second_metrics.circularity,
            second_metrics.extent,
            second_metrics.solidity,
            second_metrics.aspect,
            second_metrics.object_area_ratio,
            second_metrics.object_center,
            second_contour,
            second_metrics.reasons,
        )

        tracker.update(
            [(first_box, first_metrics)], 1000, 1000, 1000, 1000
        )
        tracked = tracker.update(
            [(first_box, first_metrics), (second_box, second_metrics)],
            1000,
            1000,
            1000,
            1000,
        )

        self.assertIs(tracked.current_item[0], second_box)

    def test_multi_recovery_recovers_each_missing_ball_from_current_frame(self) -> None:
        tracker = MultiBallTracker(smoothing_alpha=1.0)
        left = self._tracked_item(
            "color", 0.30, 0.50, 0.04, 0.20, confidence=0.99
        )
        right = self._tracked_item(
            "color", 0.70, 0.50, 0.04, 0.20, confidence=0.99
        )
        tracker.update([left, right], 1000, 1000, 1000, 1000)
        image = np.zeros((240, 240, 3), dtype=np.uint8)
        cv2.circle(image, (76, 120), 24, (210, 255, 40), -1)
        cv2.circle(image, (164, 120), 24, (210, 255, 40), -1)
        color_mask, highlight_mask = build_candidate_masks(image, CONFIG)

        recovered = recover_missing_tracked_candidates(
            image,
            tracker,
            [],
            1000,
            1000,
            color_mask=color_mask,
            highlight_mask=highlight_mask,
        )

        self.assertEqual(len(recovered), 2)
        centers = sorted(
            metrics.object_center[0] / 240.0
            for _, metrics in recovered
        )
        self.assertAlmostEqual(centers[0], 76 / 240.0, places=2)
        self.assertAlmostEqual(centers[1], 164 / 240.0, places=2)

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

    def test_overlapping_balls_keep_two_verified_circle_candidates(self) -> None:
        image = np.zeros((240, 240, 3), dtype=np.uint8)
        cv2.circle(image, (100, 120), 30, (210, 255, 40), -1)
        cv2.circle(image, (140, 120), 30, (210, 255, 40), -1)
        mocked_circles = np.array(
            [[[100.0, 120.0, 30.0], [140.0, 120.0, 30.0]]],
            dtype=np.float32,
        )

        with patch(
            "tennis_candidate_filter.cv2.HoughCircles",
            return_value=mocked_circles,
        ):
            boxes = find_color_candidate_boxes(image, CONFIG, 1000)

        self.assertEqual(len(boxes), 3, boxes)
        evaluated = [
            (box, evaluate_candidate(image, box, 1000, 1000, CONFIG))
            for box in boxes
        ]
        accepted = resolve_verified_circle_splits([
            item for item in evaluated if item[1].accepted
        ])

        self.assertEqual(len(accepted), 2, accepted)
        self.assertTrue(all(box.get("circle_candidate") for box, _ in accepted))
        tracker = MultiBallTracker(smoothing_alpha=1.0)
        tracked = tracker.update(accepted, 240, 240, 1000, 1000)
        self.assertEqual(len(tracked.visible_targets), 2)

    def test_component_hough_keeps_two_circles_from_merged_blob(self) -> None:
        image = np.zeros((240, 240, 3), dtype=np.uint8)
        cv2.circle(image, (100, 120), 30, (210, 255, 40), -1)
        cv2.circle(image, (140, 120), 30, (210, 255, 40), -1)
        roi_circles = np.array(
            [[[41.0, 41.0, 30.0], [81.0, 41.0, 30.0]]],
            dtype=np.float32,
        )

        with patch(
            "tennis_candidate_filter.cv2.HoughCircles",
            side_effect=[None, roi_circles],
        ):
            boxes = find_color_candidate_boxes(image, CONFIG, 1000)

        split_circles = [
            box for box in boxes if box.get("circle_split_candidate")
        ]
        self.assertEqual(len(split_circles), 2, boxes)
        self.assertTrue(any(
            box.get("circle_split_parent_candidate") for box in boxes
        ))

    def test_single_verified_split_circle_keeps_connected_parent(self) -> None:
        image = np.zeros((240, 240, 3), dtype=np.uint8)
        cv2.circle(image, (100, 120), 30, (210, 255, 40), -1)
        cv2.circle(image, (140, 120), 30, (210, 255, 40), -1)
        mocked_circles = np.array(
            [[[100.0, 120.0, 30.0], [140.0, 120.0, 30.0]]],
            dtype=np.float32,
        )

        with patch(
            "tennis_candidate_filter.cv2.HoughCircles",
            return_value=mocked_circles,
        ):
            boxes = find_color_candidate_boxes(image, CONFIG, 1000)

        split_circles = [
            box for box in boxes if box.get("circle_split_candidate")
        ]
        self.assertEqual(len(split_circles), 2, boxes)
        split_circles[1]["value"] = 0.10
        evaluated = [
            (box, evaluate_candidate(image, box, 1000, 1000, CONFIG))
            for box in boxes
        ]
        accepted = resolve_verified_circle_splits([
            item for item in evaluated if item[1].accepted
        ])

        self.assertEqual(len(accepted), 1, accepted)
        self.assertTrue(accepted[0][0].get("color_candidate"))

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

    def test_color_candidate_keeps_its_concave_source_contour(self) -> None:
        image = np.zeros((200, 200, 3), dtype=np.uint8)
        color = (210, 255, 40)
        cv2.rectangle(image, (40, 40), (160, 160), color, -1)
        cv2.rectangle(image, (60, 40), (140, 140), (0, 0, 0), -1)
        cv2.circle(image, (100, 100), 5, color, -1)

        boxes = find_color_candidate_boxes(image, CONFIG, 1000)
        largest = max(
            boxes,
            key=lambda box: float(box["width"]) * float(box["height"]),
        )
        metrics = evaluate_candidate(image, largest, 1000, 1000, CONFIG)

        self.assertGreater(metrics.object_area_ratio, 0.05)
        self.assertNotIn("too_small", metrics.reasons)

    def test_bright_yellow_square_is_rejected(self) -> None:
        image = np.zeros((200, 200, 3), dtype=np.uint8)
        cv2.rectangle(image, (40, 40), (159, 159), (210, 255, 40), -1)
        metrics = evaluate_candidate(image, DETECTION, 100, 100, CONFIG)
        self.assertFalse(metrics.accepted)
        self.assertIn("shape_fill", metrics.reasons)

    def test_white_glare_inside_ball_does_not_break_candidate(self) -> None:
        image = np.zeros((240, 240, 3), dtype=np.uint8)
        color = (210, 255, 40)
        cv2.circle(image, (120, 120), 55, color, -1)
        cv2.ellipse(
            image,
            (145, 100),
            (34, 30),
            0,
            0,
            360,
            (245, 245, 245),
            -1,
        )

        boxes = find_color_candidate_boxes(image, CONFIG, 1000)
        self.assertEqual(len(boxes), 1)
        metrics = evaluate_candidate(image, boxes[0], 1000, 1000, CONFIG)

        self.assertTrue(metrics.accepted, metrics)
        self.assertGreater(metrics.object_area_ratio, 0.10)

    def test_color_candidate_does_not_absorb_touching_white_object(self) -> None:
        image = np.zeros((240, 240, 3), dtype=np.uint8)
        cv2.circle(image, (120, 105), 38, (210, 255, 40), -1)
        cv2.rectangle(image, (105, 135), (210, 190), (248, 248, 248), -1)
        color_mask, highlight_mask = build_candidate_masks(image, CONFIG)

        with patch("tennis_candidate_filter.cv2.HoughCircles", return_value=None):
            boxes = find_color_candidate_boxes(
                image,
                CONFIG,
                1000,
                color_mask=color_mask,
                highlight_mask=highlight_mask,
            )

        self.assertEqual(len(boxes), 1, boxes)
        detection = {
            **boxes[0],
            "value": 0.95,
            "trained_verifier": True,
        }
        metrics = evaluate_candidate(
            image,
            detection,
            1000,
            1000,
            CONFIG,
            color_mask=color_mask,
            highlight_mask=highlight_mask,
        )
        color_contours, _ = cv2.findContours(
            color_mask,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )
        expected_area = max(cv2.contourArea(contour) for contour in color_contours)

        self.assertTrue(metrics.accepted, metrics)
        self.assertAlmostEqual(
            metrics.object_area_ratio,
            expected_area / float(image.shape[0] * image.shape[1]),
            places=6,
        )

    def test_mostly_white_ball_can_enter_as_highlight_candidate(self) -> None:
        image = np.zeros((240, 240, 3), dtype=np.uint8)
        cv2.circle(image, (120, 120), 28, (248, 248, 248), -1)
        cv2.ellipse(
            image,
            (105, 120),
            (12, 20),
            0,
            0,
            360,
            (210, 255, 40),
            -1,
        )

        boxes = find_color_candidate_boxes(image, CONFIG, 1000)
        self.assertEqual(len(boxes), 1, boxes)
        highlight_boxes = [
            box for box in boxes if box.get("highlight_candidate")
        ]
        self.assertEqual(len(highlight_boxes), 1)
        metrics = evaluate_candidate(
            image,
            {**highlight_boxes[0], "value": 0.65},
            1000,
            1000,
            CONFIG,
        )

        self.assertTrue(metrics.accepted, metrics)

    def test_highlight_candidate_still_requires_model_confidence(self) -> None:
        image = np.zeros((240, 240, 3), dtype=np.uint8)
        cv2.circle(image, (120, 120), 28, (248, 248, 248), -1)
        box = {
            "label": "tennis_ball",
            "value": 0.54,
            "x": 383,
            "y": 383,
            "width": 234,
            "height": 234,
            "highlight_candidate": True,
        }

        metrics = evaluate_candidate(image, box, 1000, 1000, CONFIG)

        self.assertFalse(metrics.accepted)
        self.assertIn("confidence", metrics.reasons)

    def test_small_color_seed_does_not_hide_full_white_ball_candidate(self) -> None:
        image = np.zeros((240, 240, 3), dtype=np.uint8)
        cv2.circle(image, (120, 120), 28, (248, 248, 248), -1)
        cv2.circle(image, (120, 120), 8, (210, 255, 40), -1)

        boxes = find_color_candidate_boxes(image, CONFIG, 1000)

        self.assertEqual(len(boxes), 1, boxes)
        self.assertTrue(
            any(box.get("highlight_candidate") for box in boxes),
            boxes,
        )

    def test_local_highlight_seed_can_create_ball_candidate_without_circle(self) -> None:
        image = np.zeros((240, 240, 3), dtype=np.uint8)
        cv2.circle(image, (120, 120), 30, (248, 248, 248), -1)
        cv2.circle(image, (100, 120), 8, (210, 255, 40), -1)
        color_mask, highlight_mask = build_candidate_masks(image, CONFIG)

        with patch("tennis_candidate_filter.cv2.HoughCircles", return_value=None):
            boxes = find_color_candidate_boxes(
                image,
                CONFIG,
                1000,
                color_mask=color_mask,
                highlight_mask=highlight_mask,
            )

        local_boxes = [
            box for box in boxes if box.get("local_highlight_candidate")
        ]
        self.assertEqual(len(boxes), 1, boxes)
        self.assertEqual(len(local_boxes), 1, boxes)
        metrics = evaluate_candidate(
            image,
            {**local_boxes[0], "value": 0.65},
            1000,
            1000,
            CONFIG,
            color_mask=color_mask,
            highlight_mask=highlight_mask,
        )
        self.assertTrue(metrics.accepted, metrics)

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

    def test_high_confidence_trained_candidate_accepts_dark_fragment(self) -> None:
        image = np.zeros((200, 200, 3), dtype=np.uint8)
        color = (210, 255, 40)
        cv2.rectangle(image, (50, 65), (150, 135), color, -1)
        for index, x in enumerate(range(55, 146, 12)):
            if index % 2 == 0:
                cv2.rectangle(image, (x, 65), (x + 8, 86), (0, 0, 0), -1)
            else:
                cv2.rectangle(image, (x, 114), (x + 8, 135), (0, 0, 0), -1)

        ordinary = evaluate_candidate(image, DETECTION, 100, 100, CONFIG)
        trained = evaluate_candidate(
            image,
            {**DETECTION, "trained_verifier": True},
            100,
            100,
            CONFIG,
        )

        self.assertLess(ordinary.circularity, CONFIG.circularity_min)
        self.assertFalse(ordinary.accepted, ordinary)
        self.assertIn("not_round", ordinary.reasons)
        self.assertTrue(trained.accepted, trained)

    def test_high_confidence_trained_candidate_relaxes_partial_fill(self) -> None:
        image = np.zeros((200, 200, 3), dtype=np.uint8)
        color = (210, 255, 40)
        cv2.ellipse(image, (100, 100), (55, 10), 45, 0, 360, color, -1)
        largest = max(
            find_color_candidate_boxes(image, CONFIG, 1000),
            key=lambda box: float(box["width"]) * float(box["height"]),
        )
        ordinary = evaluate_candidate(image, largest, 1000, 1000, CONFIG)
        trained = evaluate_candidate(
            image,
            {**largest, "value": 0.98, "trained_verifier": True},
            1000,
            1000,
            CONFIG,
        )

        self.assertFalse(ordinary.accepted, ordinary)
        self.assertIn("shape_fill", ordinary.reasons)
        self.assertTrue(trained.accepted, trained)

    def test_high_confidence_trained_candidate_relaxes_partial_solidity(self) -> None:
        image = np.zeros((200, 200, 3), dtype=np.uint8)
        color = (210, 255, 40)
        cv2.rectangle(image, (50, 50), (150, 150), color, -1)
        cv2.rectangle(image, (70, 50), (130, 125), (0, 0, 0), -1)
        largest = max(
            find_color_candidate_boxes(image, CONFIG, 1000),
            key=lambda box: float(box["width"]) * float(box["height"]),
        )
        ordinary = evaluate_candidate(image, largest, 1000, 1000, CONFIG)
        trained = evaluate_candidate(
            image,
            {**largest, "value": 0.98, "trained_verifier": True},
            1000,
            1000,
            CONFIG,
        )

        self.assertFalse(ordinary.accepted, ordinary)
        self.assertIn("irregular_shape", ordinary.reasons)
        self.assertTrue(trained.accepted, trained)

    def test_high_confidence_trained_candidate_relaxes_dark_aspect(self) -> None:
        image = np.zeros((200, 200, 3), dtype=np.uint8)
        color = (210, 255, 40)
        cv2.ellipse(image, (100, 100), (52, 23), 0, 0, 360, color, -1)
        largest = max(
            find_color_candidate_boxes(image, CONFIG, 1000),
            key=lambda box: float(box["width"]) * float(box["height"]),
        )
        ordinary = evaluate_candidate(image, largest, 1000, 1000, CONFIG)
        trained = evaluate_candidate(
            image,
            {**largest, "value": 0.98, "trained_verifier": True},
            1000,
            1000,
            CONFIG,
        )

        self.assertFalse(ordinary.accepted, ordinary)
        self.assertIn("shape_aspect", ordinary.reasons)
        self.assertTrue(trained.accepted, trained)

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
