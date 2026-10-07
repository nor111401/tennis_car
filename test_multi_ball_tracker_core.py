"""Multi-ball association tests that can run without Raspberry Pi vision libs."""

from __future__ import annotations

import sys
import types
import unittest


try:
    import cv2  # type: ignore[import-not-found]  # noqa: F401
except ModuleNotFoundError:
    sys.modules["cv2"] = types.ModuleType("cv2")

try:
    import numpy  # type: ignore[import-not-found]  # noqa: F401
except ModuleNotFoundError:
    numpy_stub = types.ModuleType("numpy")
    numpy_stub.ndarray = object
    sys.modules["numpy"] = numpy_stub


from tennis_candidate_filter import CandidateMetrics, MultiBallTracker


def tracked_item(
    source: str,
    center_x: float,
    center_y: float,
    area: float,
    size: float,
):
    box = {
        "value": 0.95,
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


class MultiBallTrackerCoreTests(unittest.TestCase):
    def test_two_tracks_retain_identity_while_moving(self) -> None:
        tracker = MultiBallTracker(smoothing_alpha=1.0)
        left = tracked_item("color", 0.25, 0.50, 0.03, 0.16)
        right = tracked_item("color", 0.75, 0.50, 0.08, 0.25)
        first = tracker.update([left, right], 1000, 1000, 1000, 1000)
        first_ids = {
            round(target.center_x, 2): target.track_id
            for target in first.visible_targets
        }

        moved_left = tracked_item("color", 0.27, 0.50, 0.03, 0.16)
        moved_right = tracked_item("color", 0.73, 0.50, 0.08, 0.25)
        second = tracker.update(
            [moved_left, moved_right], 1000, 1000, 1000, 1000
        )
        second_ids = {
            round(target.center_x, 2): target.track_id
            for target in second.visible_targets
        }

        self.assertEqual(second_ids[0.27], first_ids[0.25])
        self.assertEqual(second_ids[0.73], first_ids[0.75])
        self.assertAlmostEqual(second.primary_target.center_x, 0.73)

    def test_same_ball_color_and_glare_candidates_are_grouped(self) -> None:
        tracker = MultiBallTracker()
        color = tracked_item("color", 0.50, 0.50, 0.04, 0.20)
        glare = tracked_item("glare", 0.51, 0.50, 0.07, 0.26)

        result = tracker.update(
            [glare, color], 1000, 1000, 1000, 1000
        )

        self.assertEqual(len(result.visible_targets), 1)
        self.assertEqual(result.primary_target.source, "color")
        self.assertIs(result.primary_target.display_item[0], color[0])

    def test_missing_track_is_hidden_and_then_reacquired(self) -> None:
        tracker = MultiBallTracker(smoothing_alpha=1.0)
        left = tracked_item("color", 0.25, 0.50, 0.03, 0.16)
        right = tracked_item("color", 0.75, 0.50, 0.08, 0.25)
        first = tracker.update([left, right], 1000, 1000, 1000, 1000)
        left_id = min(
            first.visible_targets,
            key=lambda target: target.center_x,
        ).track_id

        missing = tracker.update([right], 1000, 1000, 1000, 1000)

        self.assertEqual(len(missing.visible_targets), 1)
        self.assertEqual(len(tracker.current_targets()), 2)
        moved_left = tracked_item("color", 0.27, 0.50, 0.03, 0.16)
        recovered = tracker.update(
            [moved_left, right], 1000, 1000, 1000, 1000
        )
        recovered_left = min(
            recovered.visible_targets,
            key=lambda target: target.center_x,
        )
        self.assertEqual(recovered_left.track_id, left_id)

    def test_missing_frame_never_returns_old_visible_geometry(self) -> None:
        tracker = MultiBallTracker()
        ball = tracked_item("color", 0.50, 0.50, 0.05, 0.22)
        tracker.update([ball], 1000, 1000, 1000, 1000)

        missing = tracker.update([], 1000, 1000, 1000, 1000)

        self.assertEqual(missing.visible_targets, ())
        self.assertIsNone(missing.primary_target)
        self.assertEqual(len(tracker.current_targets()), 1)

    def test_one_candidate_can_update_only_one_existing_track(self) -> None:
        tracker = MultiBallTracker(smoothing_alpha=1.0)
        left = tracked_item("color", 0.40, 0.50, 0.03, 0.16)
        right = tracked_item("color", 0.60, 0.50, 0.03, 0.16)
        tracker.update([left, right], 1000, 1000, 1000, 1000)
        middle = tracked_item("color", 0.50, 0.50, 0.03, 0.16)

        result = tracker.update([middle], 1000, 1000, 1000, 1000)

        self.assertEqual(len(result.visible_targets), 1)
        self.assertEqual(len(tracker.current_targets()), 2)

    def test_primary_switch_requires_three_nearer_frames(self) -> None:
        tracker = MultiBallTracker(
            smoothing_alpha=1.0,
            target_switch_area_ratio=1.35,
            target_switch_frames=3,
        )
        left = tracked_item("color", 0.25, 0.50, 0.05, 0.20)
        right_far = tracked_item("color", 0.75, 0.50, 0.04, 0.18)
        first = tracker.update(
            [left, right_far], 1000, 1000, 1000, 1000
        )
        first_id = first.primary_target.track_id
        right_near = tracked_item("color", 0.75, 0.50, 0.08, 0.26)

        one = tracker.update(
            [left, right_near], 1000, 1000, 1000, 1000
        )
        two = tracker.update(
            [left, right_near], 1000, 1000, 1000, 1000
        )
        three = tracker.update(
            [left, right_near], 1000, 1000, 1000, 1000
        )

        self.assertEqual(one.primary_target.track_id, first_id)
        self.assertEqual(two.primary_target.track_id, first_id)
        self.assertNotEqual(three.primary_target.track_id, first_id)
        self.assertTrue(three.primary_changed)


if __name__ == "__main__":
    unittest.main()
