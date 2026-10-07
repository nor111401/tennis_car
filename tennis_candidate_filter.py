"""Conservative post-filtering for tennis-ball detector candidates."""

from __future__ import annotations

from dataclasses import dataclass
import math
import os

import cv2
import numpy as np


def _env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    return default if value is None else float(value)


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    return default if value is None else int(value)


@dataclass(frozen=True)
class CandidateFilterConfig:
    confidence_threshold: float = 0.70
    hue_min: int = 28
    hue_max: int = 60
    saturation_min: int = 70
    value_min: int = 45
    color_ratio_min: float = 0.08
    circularity_min: float = 0.42
    trained_confidence_relax: float = 0.90
    trained_circularity_min: float = 0.0
    extent_min: float = 0.30
    extent_max: float = 0.92
    trained_extent_min: float = 0.25
    trained_extent_max: float = 0.98
    solidity_min: float = 0.72
    trained_solidity_min: float = 0.45
    aspect_max: float = 1.85
    trained_aspect_max: float = 2.50
    object_area_min: float = 0.0005
    crop_expansion: float = 2.50
    glare_value_min: int = 180
    glare_saturation_max: int = 75
    glare_search_ratio: float = 0.45
    glare_confidence_threshold: float = 0.55
    glare_coverage_min: float = 0.35
    glare_circle_max_side: int = 240
    close_color_coverage: float = 0.60
    confirm_frames: int = 3
    confirm_max_jump: float = 0.20

    @classmethod
    def from_environment(cls) -> "CandidateFilterConfig":
        config = cls(
            confidence_threshold=_env_float(
                "TENNIS_CONFIDENCE_THRESHOLD",
                0.70,
            ),
            hue_min=_env_int("TENNIS_HUE_MIN", 28),
            hue_max=_env_int("TENNIS_HUE_MAX", 60),
            saturation_min=_env_int("TENNIS_SATURATION_MIN", 70),
            value_min=_env_int("TENNIS_VALUE_MIN", 45),
            color_ratio_min=_env_float(
                "TENNIS_COLOR_RATIO_MIN",
                0.08,
            ),
            circularity_min=_env_float(
                "TENNIS_CIRCULARITY_MIN",
                0.42,
            ),
            trained_confidence_relax=_env_float(
                "TENNIS_TRAINED_CONFIDENCE_RELAX",
                0.90,
            ),
            trained_circularity_min=_env_float(
                "TENNIS_TRAINED_CIRCULARITY_MIN",
                0.0,
            ),
            extent_min=_env_float("TENNIS_EXTENT_MIN", 0.30),
            extent_max=_env_float("TENNIS_EXTENT_MAX", 0.92),
            trained_extent_min=_env_float(
                "TENNIS_TRAINED_EXTENT_MIN",
                0.25,
            ),
            trained_extent_max=_env_float(
                "TENNIS_TRAINED_EXTENT_MAX",
                0.98,
            ),
            solidity_min=_env_float("TENNIS_SOLIDITY_MIN", 0.72),
            trained_solidity_min=_env_float(
                "TENNIS_TRAINED_SOLIDITY_MIN",
                0.45,
            ),
            aspect_max=_env_float("TENNIS_ASPECT_MAX", 1.85),
            trained_aspect_max=_env_float(
                "TENNIS_TRAINED_ASPECT_MAX",
                2.50,
            ),
            object_area_min=_env_float(
                "TENNIS_OBJECT_AREA_MIN",
                0.0005,
            ),
            crop_expansion=_env_float("TENNIS_CROP_EXPANSION", 2.50),
            glare_value_min=_env_int("TENNIS_GLARE_VALUE_MIN", 180),
            glare_saturation_max=_env_int(
                "TENNIS_GLARE_SATURATION_MAX",
                75,
            ),
            glare_search_ratio=_env_float(
                "TENNIS_GLARE_SEARCH_RATIO",
                0.45,
            ),
            glare_confidence_threshold=_env_float(
                "TENNIS_GLARE_CONFIDENCE_THRESHOLD",
                0.55,
            ),
            glare_coverage_min=_env_float(
                "TENNIS_GLARE_COVERAGE_MIN",
                0.35,
            ),
            glare_circle_max_side=_env_int(
                "TENNIS_GLARE_CIRCLE_MAX_SIDE",
                240,
            ),
            close_color_coverage=_env_float(
                "TENNIS_CLOSE_COLOR_COVERAGE",
                0.60,
            ),
            confirm_frames=_env_int("TENNIS_CONFIRM_FRAMES", 3),
            confirm_max_jump=_env_float(
                "TENNIS_CONFIRM_MAX_JUMP",
                0.20,
            ),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if not 0 < self.confidence_threshold <= 1:
            raise ValueError("confidence_threshold must be in (0, 1]")
        if not 0 <= self.hue_min <= self.hue_max <= 179:
            raise ValueError("HSV hue range must be between 0 and 179")
        if not 0 <= self.saturation_min <= 255:
            raise ValueError("saturation_min must be between 0 and 255")
        if not 0 <= self.value_min <= 255:
            raise ValueError("value_min must be between 0 and 255")
        if not 0 <= self.color_ratio_min <= 1:
            raise ValueError("color_ratio_min must be between 0 and 1")
        if not 0 <= self.circularity_min <= 1:
            raise ValueError("circularity_min must be between 0 and 1")
        if not 0 < self.trained_confidence_relax <= 1:
            raise ValueError("trained_confidence_relax must be in (0, 1]")
        if not 0 <= self.trained_circularity_min <= self.circularity_min:
            raise ValueError(
                "trained_circularity_min must be between 0 and circularity_min"
            )
        if not 0 <= self.extent_min < self.extent_max <= 1:
            raise ValueError("extent range must be within [0, 1]")
        if not 0 <= self.trained_extent_min <= self.extent_min:
            raise ValueError(
                "trained_extent_min must be between 0 and extent_min"
            )
        if not self.extent_max <= self.trained_extent_max <= 1:
            raise ValueError(
                "trained_extent_max must be between extent_max and 1"
            )
        if not 0 <= self.solidity_min <= 1:
            raise ValueError("solidity_min must be between 0 and 1")
        if not 0 <= self.trained_solidity_min <= self.solidity_min:
            raise ValueError(
                "trained_solidity_min must be between 0 and solidity_min"
            )
        if self.aspect_max < 1:
            raise ValueError("aspect_max must be at least 1")
        if self.trained_aspect_max < self.aspect_max:
            raise ValueError(
                "trained_aspect_max must be at least aspect_max"
            )
        if not 0 <= self.object_area_min < 1:
            raise ValueError("object_area_min must be within [0, 1)")
        if self.crop_expansion < 1:
            raise ValueError("crop_expansion must be at least 1")
        if not 0 <= self.glare_value_min <= 255:
            raise ValueError("glare_value_min must be between 0 and 255")
        if not 0 <= self.glare_saturation_max <= 255:
            raise ValueError(
                "glare_saturation_max must be between 0 and 255"
            )
        if not 0 < self.glare_search_ratio <= 2:
            raise ValueError("glare_search_ratio must be within (0, 2]")
        if not 0 < self.glare_confidence_threshold <= 1:
            raise ValueError(
                "glare_confidence_threshold must be in (0, 1]"
            )
        if not 0 < self.glare_coverage_min <= 1:
            raise ValueError("glare_coverage_min must be in (0, 1]")
        if self.glare_circle_max_side < 64:
            raise ValueError("glare_circle_max_side must be at least 64")
        if not 0 < self.close_color_coverage <= 1:
            raise ValueError("close_color_coverage must be in (0, 1]")
        if self.confirm_frames < 1:
            raise ValueError("confirm_frames must be at least 1")
        if not 0 < self.confirm_max_jump <= 1:
            raise ValueError("confirm_max_jump must be in (0, 1]")


@dataclass(frozen=True)
class CandidateMetrics:
    accepted: bool
    color_ratio: float
    circularity: float
    extent: float
    solidity: float
    aspect: float
    object_area_ratio: float
    object_center: tuple[float, float] | None
    object_contour: np.ndarray | None
    reasons: tuple[str, ...]


def resolve_verified_circle_splits(
    candidates: list[tuple[dict, CandidateMetrics]],
) -> list[tuple[dict, CandidateMetrics]]:
    """Prefer verified child circles only when at least two survived.

    Circle proposals are created before the trained verifier runs. Keeping
    the original connected component until this point prevents two weak or
    false Hough responses from deleting an otherwise valid color candidate.
    """
    parents = {
        box.get("circle_split_parent_id")
        for box, _ in candidates
        if box.get("circle_split_parent_candidate")
    }
    parents.discard(None)

    children_by_parent: dict[object, list[tuple[dict, CandidateMetrics]]] = {}
    for item in candidates:
        box, _ = item
        for parent_id in box.get("circle_split_parent_ids", ()):
            children_by_parent.setdefault(parent_id, []).append(item)

    verified_splits = {
        parent_id
        for parent_id, children in children_by_parent.items()
        if len(children) >= 2
    }
    resolved = []
    for item in candidates:
        box, _ = item
        parent_id = box.get("circle_split_parent_id")
        child_parents = set(box.get("circle_split_parent_ids", ()))
        if box.get("circle_split_parent_candidate"):
            if parent_id in verified_splits:
                continue
        elif child_parents:
            if child_parents & verified_splits:
                pass
            elif child_parents & parents:
                continue
        resolved.append(item)
    return resolved


def select_nearest_candidate(candidates: list[tuple[dict, CandidateMetrics]]):
    """Choose the candidate with the largest apparent object area.

    With a fixed camera and the same class of object, a larger verified contour
    is the closest available target. Confidence is only a tie-breaker so a
    smaller, more confident ball cannot displace a visibly nearer ball.
    """
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda item: (
            item[1].object_area_ratio,
            float(item[0].get("value", 0.0)),
        ),
    )


@dataclass(frozen=True)
class TrackedTarget:
    current_item: tuple[dict, CandidateMetrics]
    display_item: tuple[dict, CandidateMetrics]
    related_box_ids: frozenset[int]
    center_x: float
    center_y: float
    width: float
    height: float
    area_ratio: float
    source: str
    track_id: int = 0


@dataclass(frozen=True)
class _CandidateView:
    item: tuple[dict, CandidateMetrics]
    source: str
    center_x: float
    center_y: float
    width: float
    height: float
    area_ratio: float


class TemporalTargetTracker:
    """Keep one physical ball stable across color/glare proposal changes."""

    def __init__(
        self,
        glare_fallback_frames: int = 2,
        color_recovery_frames: int = 3,
        smoothing_alpha: float = 0.35,
        max_match_distance: float = 0.15,
        target_switch_area_ratio: float = 1.35,
    ) -> None:
        if glare_fallback_frames < 1:
            raise ValueError("glare_fallback_frames must be at least 1")
        if color_recovery_frames < 1:
            raise ValueError("color_recovery_frames must be at least 1")
        if not 0 < smoothing_alpha <= 1:
            raise ValueError("smoothing_alpha must be within (0, 1]")
        if not 0 < max_match_distance <= 1:
            raise ValueError("max_match_distance must be within (0, 1]")
        if target_switch_area_ratio < 1:
            raise ValueError("target_switch_area_ratio must be at least 1")

        self.glare_fallback_frames = glare_fallback_frames
        self.color_recovery_frames = color_recovery_frames
        self.smoothing_alpha = smoothing_alpha
        self.max_match_distance = max_match_distance
        self.target_switch_area_ratio = target_switch_area_ratio
        self.reset()

    def reset(self) -> None:
        self._source: str | None = None
        self._center_x: float | None = None
        self._center_y: float | None = None
        self._width: float | None = None
        self._height: float | None = None
        self._area_ratio: float | None = None
        self._current_item: tuple[dict, CandidateMetrics] | None = None
        self._display_item: tuple[dict, CandidateMetrics] | None = None
        self._glare_count = 0
        self._color_count = 0
        self._missing_count = 0

    @staticmethod
    def _source_for(box: dict) -> str:
        if box.get("color_candidate") and not box.get("highlight_candidate"):
            return "color"
        return "glare"

    @staticmethod
    def _view(
        item: tuple[dict, CandidateMetrics],
        image_width: int,
        image_height: int,
        model_width: int,
        model_height: int,
    ) -> _CandidateView:
        box, metrics = item
        if metrics.object_center is None:
            center_x = (float(box["x"]) + float(box["width"]) / 2.0) / model_width
            center_y = (float(box["y"]) + float(box["height"]) / 2.0) / model_height
        else:
            center_x = float(metrics.object_center[0]) / image_width
            center_y = float(metrics.object_center[1]) / image_height

        if metrics.object_contour is None:
            width = float(box["width"]) / model_width
            height = float(box["height"]) / model_height
        else:
            _, _, contour_width, contour_height = cv2.boundingRect(
                metrics.object_contour
            )
            width = float(contour_width) / image_width
            height = float(contour_height) / image_height

        return _CandidateView(
            item=item,
            source=TemporalTargetTracker._source_for(box),
            center_x=center_x,
            center_y=center_y,
            width=width,
            height=height,
            area_ratio=float(metrics.object_area_ratio),
        )

    def _match_distance(self, view: _CandidateView) -> float:
        tracked_size = max(self._width or 0.0, self._height or 0.0)
        candidate_size = max(view.width, view.height)
        return max(
            0.035,
            min(
                self.max_match_distance,
                0.75 * (tracked_size + candidate_size) / 2.0,
            ),
        )

    def _matches(self, view: _CandidateView) -> bool:
        if self._center_x is None or self._center_y is None:
            return False
        return math.hypot(
            view.center_x - self._center_x,
            view.center_y - self._center_y,
        ) <= self._match_distance(view)

    def _same_object(self, left: _CandidateView, right: _CandidateView) -> bool:
        allowed_distance = max(
            0.035,
            min(
                self.max_match_distance,
                0.75 * (
                    max(left.width, left.height)
                    + max(right.width, right.height)
                ) / 2.0,
            ),
        )
        return math.hypot(
            left.center_x - right.center_x,
            left.center_y - right.center_y,
        ) <= allowed_distance

    @staticmethod
    def _best(views: list[_CandidateView]) -> _CandidateView | None:
        if not views:
            return None
        return max(
            views,
            key=lambda view: (
                view.area_ratio,
                float(view.item[0].get("value", 0.0)),
            ),
        )

    def _start_track(self, view: _CandidateView) -> None:
        self._source = view.source
        self._center_x = view.center_x
        self._center_y = view.center_y
        self._width = view.width
        self._height = view.height
        self._area_ratio = view.area_ratio
        self._current_item = view.item
        self._display_item = view.item
        self._glare_count = 0
        self._color_count = 0

    def _smooth(self, view: _CandidateView) -> None:
        if self._center_x is None:
            self._start_track(view)
            return
        alpha = self.smoothing_alpha
        self._center_x += alpha * (view.center_x - self._center_x)
        self._center_y += alpha * (view.center_y - self._center_y)
        self._width += alpha * (view.width - self._width)
        self._height += alpha * (view.height - self._height)
        self._area_ratio += alpha * (view.area_ratio - self._area_ratio)

    def current_target(self) -> TrackedTarget | None:
        if (
            self._current_item is None
            or self._display_item is None
            or self._center_x is None
            or self._center_y is None
            or self._width is None
            or self._height is None
            or self._area_ratio is None
            or self._source is None
        ):
            return None
        return TrackedTarget(
            current_item=self._current_item,
            display_item=self._display_item,
            related_box_ids=frozenset(),
            center_x=float(self._center_x),
            center_y=float(self._center_y),
            width=float(self._width),
            height=float(self._height),
            area_ratio=float(self._area_ratio),
            source=self._source,
        )

    def update(
        self,
        candidates: list[tuple[dict, CandidateMetrics]],
        image_width: int,
        image_height: int,
        model_width: int,
        model_height: int,
    ) -> TrackedTarget | None:
        if not candidates:
            self._missing_count += 1
            if self._missing_count >= self.color_recovery_frames:
                self.reset()
            return None
        self._missing_count = 0

        views = [
            self._view(
                item,
                image_width,
                image_height,
                model_width,
                model_height,
            )
            for item in candidates
        ]
        global_best = self._best(views)
        if global_best is None:
            return None

        new_track = self._center_x is None
        if new_track:
            pool = [
                view for view in views
                if self._same_object(view, global_best)
            ]
        else:
            matched = [view for view in views if self._matches(view)]
            tracked_best = self._best(matched)
            global_is_matched = any(
                view is global_best for view in matched
            )
            switch_target = (
                tracked_best is None
                or (
                    not global_is_matched
                    and global_best.area_ratio
                    >= tracked_best.area_ratio * self.target_switch_area_ratio
                )
            )
            if switch_target:
                self.reset()
                new_track = True
                pool = [
                    view for view in views
                    if self._same_object(view, global_best)
                ]
            else:
                pool = matched

        color_best = self._best([
            view for view in pool if view.source == "color"
        ])
        glare_best = self._best([
            view for view in pool if view.source == "glare"
        ])

        hold_geometry = False
        if new_track:
            selected = color_best or glare_best or global_best
            self._start_track(selected)
        elif self._source == "color":
            if color_best is not None:
                selected = color_best
                self._glare_count = 0
                self._color_count = 0
            else:
                selected = glare_best or global_best
                self._glare_count += 1
                if self._glare_count < self.glare_fallback_frames:
                    hold_geometry = True
                else:
                    self._source = "glare"
                    self._glare_count = 0
                    self._color_count = 0
        else:
            if color_best is not None:
                self._color_count += 1
                if self._color_count >= self.color_recovery_frames:
                    selected = color_best
                    self._source = "color"
                    self._color_count = 0
                    self._glare_count = 0
                elif glare_best is not None:
                    selected = glare_best
                else:
                    selected = color_best
                    hold_geometry = True
            else:
                selected = glare_best or global_best
                self._color_count = 0

        if not hold_geometry:
            self._smooth(selected)
            self._display_item = selected.item

        if self._display_item is None:
            self._display_item = selected.item
        self._current_item = selected.item

        return TrackedTarget(
            current_item=self._current_item,
            display_item=self._display_item,
            related_box_ids=frozenset(id(view.item[0]) for view in pool),
            center_x=float(self._center_x),
            center_y=float(self._center_y),
            width=float(self._width),
            height=float(self._height),
            area_ratio=float(self._area_ratio),
            source=str(self._source),
        )


@dataclass(frozen=True)
class MultiBallTrackingResult:
    """Visible ball tracks plus the single track used for vehicle control."""

    visible_targets: tuple[TrackedTarget, ...]
    primary_target: TrackedTarget | None
    primary_changed: bool


@dataclass
class _BallTrack:
    track_id: int
    source: str
    center_x: float
    center_y: float
    width: float
    height: float
    area_ratio: float
    current_item: tuple[dict, CandidateMetrics]
    display_item: tuple[dict, CandidateMetrics]
    related_box_ids: frozenset[int]
    missing_count: int = 0
    glare_count: int = 0
    color_count: int = 0


@dataclass(frozen=True)
class _BallProposal:
    selected: _CandidateView
    related_box_ids: frozenset[int]


class MultiBallTracker:
    """Track every visible ball independently and select one control target.

    Tracks survive a short detection gap only as hidden state for re-acquisition.
    Every returned target is backed by current-frame evidence, so an old contour
    can never remain painted at a position the ball has already left.
    """

    def __init__(
        self,
        glare_fallback_frames: int = 2,
        color_recovery_frames: int = 3,
        smoothing_alpha: float = 0.35,
        max_match_distance: float = 0.15,
        max_missing_frames: int = 3,
        target_switch_area_ratio: float = 1.35,
        target_switch_frames: int = 3,
    ) -> None:
        if glare_fallback_frames < 1:
            raise ValueError("glare_fallback_frames must be at least 1")
        if color_recovery_frames < 1:
            raise ValueError("color_recovery_frames must be at least 1")
        if not 0 < smoothing_alpha <= 1:
            raise ValueError("smoothing_alpha must be within (0, 1]")
        if not 0 < max_match_distance <= 1:
            raise ValueError("max_match_distance must be within (0, 1]")
        if max_missing_frames < 1:
            raise ValueError("max_missing_frames must be at least 1")
        if target_switch_area_ratio < 1:
            raise ValueError("target_switch_area_ratio must be at least 1")
        if target_switch_frames < 1:
            raise ValueError("target_switch_frames must be at least 1")

        self.glare_fallback_frames = glare_fallback_frames
        self.color_recovery_frames = color_recovery_frames
        self.smoothing_alpha = smoothing_alpha
        self.max_match_distance = max_match_distance
        self.max_missing_frames = max_missing_frames
        self.target_switch_area_ratio = target_switch_area_ratio
        self.target_switch_frames = target_switch_frames
        self.reset()

    def reset(self) -> None:
        self._tracks: list[_BallTrack] = []
        self._next_track_id = 1
        self._primary_track_id: int | None = None
        self._challenger_track_id: int | None = None
        self._challenger_count = 0

    @staticmethod
    def _best(views: list[_CandidateView]) -> _CandidateView | None:
        if not views:
            return None
        return max(
            views,
            key=lambda view: (
                view.area_ratio,
                float(view.item[0].get("value", 0.0)),
            ),
        )

    def _same_object(
        self,
        left: _CandidateView,
        right: _CandidateView,
    ) -> bool:
        left_parents = set(
            left.item[0].get("circle_split_parent_ids", ())
        )
        right_parents = set(
            right.item[0].get("circle_split_parent_ids", ())
        )
        if left_parents & right_parents:
            # Distinct Hough peaks from one connected color component are the
            # split instances themselves, not color/glare duplicates.
            return False
        allowed_distance = max(
            0.035,
            min(
                self.max_match_distance,
                0.75 * (
                    max(left.width, left.height)
                    + max(right.width, right.height)
                ) / 2.0,
            ),
        )
        return math.hypot(
            left.center_x - right.center_x,
            left.center_y - right.center_y,
        ) <= allowed_distance

    def _build_proposals(
        self,
        candidates: list[tuple[dict, CandidateMetrics]],
        image_width: int,
        image_height: int,
        model_width: int,
        model_height: int,
    ) -> list[_BallProposal]:
        views = [
            TemporalTargetTracker._view(
                item,
                image_width,
                image_height,
                model_width,
                model_height,
            )
            for item in candidates
        ]
        groups: list[list[_CandidateView]] = []
        for view in sorted(
            views,
            key=lambda candidate: candidate.area_ratio,
            reverse=True,
        ):
            matching_group = next(
                (
                    group for group in groups
                    if any(self._same_object(view, member) for member in group)
                ),
                None,
            )
            if matching_group is None:
                groups.append([view])
            else:
                matching_group.append(view)

        proposals = []
        for group in groups:
            color_best = self._best([
                view for view in group if view.source == "color"
            ])
            selected = color_best or self._best(group)
            if selected is None:
                continue
            proposals.append(_BallProposal(
                selected=selected,
                related_box_ids=frozenset(id(view.item[0]) for view in group),
            ))
        return proposals

    def _match_limit(self, track: _BallTrack, view: _CandidateView) -> float:
        tracked_size = max(track.width, track.height)
        candidate_size = max(view.width, view.height)
        return max(
            0.035,
            min(
                self.max_match_distance,
                0.85 * (tracked_size + candidate_size) / 2.0,
            ),
        )

    def _association_cost(
        self,
        track: _BallTrack,
        proposal: _BallProposal,
    ) -> float | None:
        view = proposal.selected
        distance = math.hypot(
            view.center_x - track.center_x,
            view.center_y - track.center_y,
        )
        limit = self._match_limit(track, view)
        if distance > limit:
            return None
        area_cost = abs(math.log(
            max(view.area_ratio, 1e-6) / max(track.area_ratio, 1e-6)
        ))
        return distance / limit + min(area_cost, 2.0) * 0.10

    def _update_source(self, track: _BallTrack, view: _CandidateView) -> None:
        if track.source == "color":
            if view.source == "color":
                track.glare_count = 0
            else:
                track.glare_count += 1
                if track.glare_count >= self.glare_fallback_frames:
                    track.source = "glare"
                    track.glare_count = 0
                    track.color_count = 0
        elif view.source == "color":
            track.color_count += 1
            if track.color_count >= self.color_recovery_frames:
                track.source = "color"
                track.color_count = 0
                track.glare_count = 0
        else:
            track.color_count = 0

    def _update_track(
        self,
        track: _BallTrack,
        proposal: _BallProposal,
    ) -> None:
        view = proposal.selected
        self._update_source(track, view)
        alpha = self.smoothing_alpha
        track.center_x += alpha * (view.center_x - track.center_x)
        track.center_y += alpha * (view.center_y - track.center_y)
        track.width += alpha * (view.width - track.width)
        track.height += alpha * (view.height - track.height)
        track.area_ratio += alpha * (view.area_ratio - track.area_ratio)
        track.current_item = view.item
        # Geometry always comes from this frame; source hysteresis never paints
        # an old contour while a ball or camera is moving.
        track.display_item = view.item
        track.related_box_ids = proposal.related_box_ids
        track.missing_count = 0

    def _new_track(self, proposal: _BallProposal) -> _BallTrack:
        view = proposal.selected
        track = _BallTrack(
            track_id=self._next_track_id,
            source=view.source,
            center_x=view.center_x,
            center_y=view.center_y,
            width=view.width,
            height=view.height,
            area_ratio=view.area_ratio,
            current_item=view.item,
            display_item=view.item,
            related_box_ids=proposal.related_box_ids,
        )
        self._next_track_id += 1
        self._tracks.append(track)
        return track

    @staticmethod
    def _snapshot(track: _BallTrack) -> TrackedTarget:
        return TrackedTarget(
            current_item=track.current_item,
            display_item=track.display_item,
            related_box_ids=track.related_box_ids,
            center_x=track.center_x,
            center_y=track.center_y,
            width=track.width,
            height=track.height,
            area_ratio=track.area_ratio,
            source=track.source,
            track_id=track.track_id,
        )

    def current_targets(self) -> tuple[TrackedTarget, ...]:
        """Return all live track states, including temporarily hidden tracks."""
        return tuple(self._snapshot(track) for track in self._tracks)

    def current_target(self) -> TrackedTarget | None:
        """Compatibility accessor for the internally selected control track."""
        track = next(
            (
                item for item in self._tracks
                if item.track_id == self._primary_track_id
            ),
            None,
        )
        return self._snapshot(track) if track is not None else None

    def _select_primary(
        self,
        visible_tracks: list[_BallTrack],
    ) -> tuple[_BallTrack | None, bool]:
        old_primary_id = self._primary_track_id
        if not visible_tracks:
            self._challenger_track_id = None
            self._challenger_count = 0
            return None, False

        primary = next(
            (
                track for track in visible_tracks
                if track.track_id == self._primary_track_id
            ),
            None,
        )
        nearest = max(visible_tracks, key=lambda track: track.area_ratio)
        if primary is None:
            self._primary_track_id = nearest.track_id
            self._challenger_track_id = None
            self._challenger_count = 0
            return nearest, old_primary_id != nearest.track_id

        if (
            nearest.track_id != primary.track_id
            and nearest.area_ratio
            >= primary.area_ratio * self.target_switch_area_ratio
        ):
            if self._challenger_track_id == nearest.track_id:
                self._challenger_count += 1
            else:
                self._challenger_track_id = nearest.track_id
                self._challenger_count = 1
            if self._challenger_count >= self.target_switch_frames:
                primary = nearest
                self._primary_track_id = nearest.track_id
                self._challenger_track_id = None
                self._challenger_count = 0
        else:
            self._challenger_track_id = None
            self._challenger_count = 0
        return primary, old_primary_id != self._primary_track_id

    def update(
        self,
        candidates: list[tuple[dict, CandidateMetrics]],
        image_width: int,
        image_height: int,
        model_width: int,
        model_height: int,
    ) -> MultiBallTrackingResult:
        proposals = self._build_proposals(
            candidates,
            image_width,
            image_height,
            model_width,
            model_height,
        )

        edges: list[tuple[float, int, int]] = []
        for track_index, track in enumerate(self._tracks):
            for proposal_index, proposal in enumerate(proposals):
                cost = self._association_cost(track, proposal)
                if cost is not None:
                    edges.append((cost, track_index, proposal_index))
        edges.sort(key=lambda edge: edge[0])

        matched_tracks: set[int] = set()
        matched_proposals: set[int] = set()
        visible_tracks: list[_BallTrack] = []
        for _, track_index, proposal_index in edges:
            if (
                track_index in matched_tracks
                or proposal_index in matched_proposals
            ):
                continue
            track = self._tracks[track_index]
            self._update_track(track, proposals[proposal_index])
            matched_tracks.add(track_index)
            matched_proposals.add(proposal_index)
            visible_tracks.append(track)

        for track_index, track in enumerate(self._tracks):
            if track_index not in matched_tracks:
                track.missing_count += 1

        for proposal_index, proposal in enumerate(proposals):
            if proposal_index not in matched_proposals:
                visible_tracks.append(self._new_track(proposal))

        self._tracks = [
            track for track in self._tracks
            if track.missing_count <= self.max_missing_frames
        ]
        if not any(
            track.track_id == self._primary_track_id for track in self._tracks
        ):
            self._primary_track_id = None

        visible_tracks.sort(key=lambda track: track.track_id)
        primary, primary_changed = self._select_primary(visible_tracks)
        return MultiBallTrackingResult(
            visible_targets=tuple(
                self._snapshot(track) for track in visible_tracks
            ),
            primary_target=(
                self._snapshot(primary) if primary is not None else None
            ),
            primary_changed=primary_changed,
        )


def _rejected(*reasons: str) -> CandidateMetrics:
    return CandidateMetrics(
        accepted=False,
        color_ratio=0.0,
        circularity=0.0,
        extent=0.0,
        solidity=0.0,
        aspect=math.inf,
        object_area_ratio=0.0,
        object_center=None,
        object_contour=None,
        reasons=tuple(reasons),
    )


def tennis_color_coverage(
    preview_rgb: np.ndarray,
    config: CandidateFilterConfig,
    color_mask: np.ndarray | None = None,
) -> float:
    mask = (
        color_mask
        if color_mask is not None
        else _tennis_color_mask(preview_rgb, config, clean=False)
    )
    return float(cv2.countNonZero(mask)) / float(mask.size)


def _tennis_color_mask(
    preview_rgb: np.ndarray,
    config: CandidateFilterConfig,
    clean: bool = True,
    hsv: np.ndarray | None = None,
) -> np.ndarray:
    if hsv is None:
        hsv = cv2.cvtColor(preview_rgb, cv2.COLOR_RGB2HSV)
    mask = cv2.inRange(
        hsv,
        (
            config.hue_min,
            config.saturation_min,
            config.value_min,
        ),
        (config.hue_max, 255, 255),
    )
    if clean:
        kernel = np.ones((5, 5), dtype=np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    return mask


def _highlight_mask(
    preview_rgb: np.ndarray,
    config: CandidateFilterConfig,
    hsv: np.ndarray | None = None,
) -> np.ndarray:
    if hsv is None:
        hsv = cv2.cvtColor(preview_rgb, cv2.COLOR_RGB2HSV)
    mask = cv2.inRange(
        hsv,
        (0, 0, config.glare_value_min),
        (179, config.glare_saturation_max, 255),
    )
    kernel = np.ones((5, 5), dtype=np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)


def build_candidate_masks(
    preview_rgb: np.ndarray,
    config: CandidateFilterConfig,
) -> tuple[np.ndarray, np.ndarray]:
    """Build the reusable color and glare masks for one preview frame."""
    hsv = cv2.cvtColor(preview_rgb, cv2.COLOR_RGB2HSV)
    return (
        _tennis_color_mask(preview_rgb, config, hsv=hsv),
        _highlight_mask(preview_rgb, config, hsv=hsv),
    )


def _add_local_highlight_pixels(
    preview_rgb: np.ndarray,
    color_mask: np.ndarray,
    detection: dict,
    model_width: int,
    model_height: int,
    config: CandidateFilterConfig,
    highlight_mask: np.ndarray | None = None,
) -> np.ndarray:
    """Restore bright, low-saturation pixels close to a color seed.

    A strong reflection can turn part of a yellow-green ball white. The white
    pixels are only admitted inside an expanded candidate region and next to
    an existing tennis-color mask, so bright floor or wall pixels do not become
    global ball candidates.
    """
    image_height, image_width = preview_rgb.shape[:2]
    box_x = float(detection["x"]) * image_width / model_width
    box_y = float(detection["y"]) * image_height / model_height
    box_width = float(detection["width"]) * image_width / model_width
    box_height = float(detection["height"]) * image_height / model_height
    padding = max(box_width, box_height) * config.glare_search_ratio
    x0 = max(0, int(math.floor(box_x - padding)))
    y0 = max(0, int(math.floor(box_y - padding)))
    x1 = min(image_width, int(math.ceil(box_x + box_width + padding)))
    y1 = min(image_height, int(math.ceil(box_y + box_height + padding)))
    if x1 <= x0 or y1 <= y0:
        return color_mask

    if highlight_mask is None:
        highlight_mask = _highlight_mask(preview_rgb, config)
    highlight_roi = highlight_mask[y0:y1, x0:x1]
    if cv2.countNonZero(highlight_roi) == 0:
        return color_mask
    bridge_size = max(
        3,
        int(round(max(box_width, box_height) * 0.20)),
    )
    if bridge_size % 2 == 0:
        bridge_size += 1
    bridge_radius = (bridge_size - 1) / 2.0
    color_roi = color_mask[y0:y1, x0:x1]
    distance_to_color = cv2.distanceTransform(
        cv2.bitwise_not(color_roi),
        cv2.DIST_L2,
        cv2.DIST_MASK_PRECISE,
    )
    near_color = np.where(
        distance_to_color <= bridge_radius,
        255,
        0,
    ).astype(np.uint8)
    local_highlights = cv2.bitwise_and(highlight_roi, near_color)
    if cv2.countNonZero(local_highlights) == 0:
        return color_mask
    mask = color_mask.copy()
    mask[y0:y1, x0:x1] = cv2.bitwise_or(
        color_roi,
        local_highlights,
    )
    return mask


def _append_component_circle_candidates(
    preview_rgb: np.ndarray,
    config: CandidateFilterConfig,
    coordinate_size: int,
    boxes: list[dict],
    color_mask: np.ndarray,
    highlight_mask: np.ndarray,
) -> None:
    """Find individual circles inside an elongated connected color blob."""
    image_height, image_width = preview_rgb.shape[:2]
    image_area = float(image_width * image_height)
    evidence = cv2.bitwise_or(color_mask, highlight_mask)
    gray = cv2.GaussianBlur(
        cv2.cvtColor(preview_rgb, cv2.COLOR_RGB2GRAY),
        (7, 7),
        1.2,
    )

    for parent in list(boxes):
        if not parent.get("color_candidate"):
            continue
        parent_x = float(parent["x"]) * image_width / coordinate_size
        parent_y = float(parent["y"]) * image_height / coordinate_size
        parent_width = float(parent["width"]) * image_width / coordinate_size
        parent_height = float(parent["height"]) * image_height / coordinate_size
        short_side = min(parent_width, parent_height)
        long_side = max(parent_width, parent_height)
        if short_side < 20 or long_side / max(short_side, 1.0) < 1.25:
            continue

        padding = max(6, int(round(short_side * 0.18)))
        x0 = max(0, int(math.floor(parent_x - padding)))
        y0 = max(0, int(math.floor(parent_y - padding)))
        x1 = min(image_width, int(math.ceil(parent_x + parent_width + padding)))
        y1 = min(image_height, int(math.ceil(parent_y + parent_height + padding)))
        roi = gray[y0:y1, x0:x1]
        if roi.size == 0:
            continue

        circles = cv2.HoughCircles(
            roi,
            cv2.HOUGH_GRADIENT,
            dp=1.2,
            minDist=max(12, int(round(short_side * 0.30))),
            param1=100,
            param2=max(14, min(30, int(round(short_side * 0.15)))),
            minRadius=max(4, int(round(short_side * 0.18))),
            maxRadius=max(8, int(round(short_side * 0.55))),
        )
        if circles is None:
            continue

        proposals: list[tuple[int, int, int]] = []
        for circle in np.round(circles[0][:8]).astype(int):
            center_x = int(circle[0] + x0)
            center_y = int(circle[1] + y0)
            radius = int(circle[2])
            if not (
                parent_x <= center_x <= parent_x + parent_width
                and parent_y <= center_y <= parent_y + parent_height
            ):
                continue
            circle_area = math.pi * radius * radius
            if not config.object_area_min * 0.5 <= circle_area / image_area <= 0.20:
                continue
            disk_x0 = max(0, center_x - radius)
            disk_y0 = max(0, center_y - radius)
            disk_x1 = min(image_width, center_x + radius + 1)
            disk_y1 = min(image_height, center_y + radius + 1)
            disk = np.zeros(
                (disk_y1 - disk_y0, disk_x1 - disk_x0),
                dtype=np.uint8,
            )
            cv2.circle(
                disk,
                (center_x - disk_x0, center_y - disk_y0),
                radius,
                255,
                -1,
            )
            evidence_ratio = (
                float(cv2.countNonZero(cv2.bitwise_and(
                    evidence[disk_y0:disk_y1, disk_x0:disk_x1],
                    disk,
                )))
                / float(max(cv2.countNonZero(disk), 1))
            )
            if evidence_ratio < config.glare_coverage_min:
                continue
            if any(
                math.hypot(center_x - other_x, center_y - other_y)
                <= 0.75 * max(radius, other_radius)
                for other_x, other_y, other_radius in proposals
            ):
                continue
            proposals.append((center_x, center_y, radius))

        if len(proposals) < 2:
            continue
        parent_id = parent.setdefault("circle_split_parent_id", id(parent))
        parent["circle_split_parent_candidate"] = True
        for center_x, center_y, radius in proposals[:4]:
            boxes.append({
                "label": "tennis_ball",
                "value": 1.0,
                "x": (center_x - radius) * coordinate_size / image_width,
                "y": (center_y - radius) * coordinate_size / image_height,
                "width": 2 * radius * coordinate_size / image_width,
                "height": 2 * radius * coordinate_size / image_height,
                "highlight_candidate": True,
                "circle_candidate": True,
                "circle_split_candidate": True,
                "circle_split_parent_ids": (parent_id,),
            })


def _append_bright_circle_candidates(
    preview_rgb: np.ndarray,
    config: CandidateFilterConfig,
    coordinate_size: int,
    boxes: list[dict],
    color_mask: np.ndarray | None = None,
    highlight_mask: np.ndarray | None = None,
) -> None:
    """Add white-ball proposals using circular edges plus bright evidence."""
    image_height, image_width = preview_rgb.shape[:2]
    max_side = max(image_height, image_width)
    scale = min(1.0, config.glare_circle_max_side / max_side)
    if scale < 1.0:
        small = cv2.resize(
            preview_rgb,
            (int(round(image_width * scale)), int(round(image_height * scale))),
            interpolation=cv2.INTER_AREA,
        )
    else:
        small = preview_rgb
    gray = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    min_dimension = min(small.shape[:2])
    circles = cv2.HoughCircles(
        gray,
        cv2.HOUGH_GRADIENT,
        dp=1.2,
        minDist=max(12, int(round(min_dimension * 0.08))),
        param1=80,
        param2=14,
        minRadius=max(4, int(round(min_dimension * 0.015))),
        maxRadius=max(8, int(round(min_dimension * 0.18))),
    )
    if circles is None:
        return

    if highlight_mask is None:
        highlight_mask = _highlight_mask(preview_rgb, config)
    if color_mask is None:
        color_mask = _tennis_color_mask(preview_rgb, config)
    image_area = float(image_width * image_height)
    evidence = cv2.bitwise_or(color_mask, highlight_mask)
    for circle in np.round(circles[0][:6]).astype(int):
        center_x = int(round(circle[0] / scale))
        center_y = int(round(circle[1] / scale))
        radius = int(round(circle[2] / scale))
        circle_area = math.pi * radius * radius
        if circle_area / image_area < config.object_area_min * 0.5:
            continue
        if circle_area / image_area > 0.20:
            continue
        x0 = max(0, center_x - radius)
        y0 = max(0, center_y - radius)
        x1 = min(image_width, center_x + radius + 1)
        y1 = min(image_height, center_y + radius + 1)
        if x1 <= x0 or y1 <= y0:
            continue
        disk = np.zeros((y1 - y0, x1 - x0), dtype=np.uint8)
        cv2.circle(
            disk,
            (center_x - x0, center_y - y0),
            radius,
            255,
            -1,
        )
        evidence_roi = evidence[y0:y1, x0:x1]
        evidence_ratio = (
            float(cv2.countNonZero(cv2.bitwise_and(evidence_roi, disk)))
            / float(max(cv2.countNonZero(disk), 1))
        )
        if evidence_ratio < config.glare_coverage_min:
            continue

        duplicate = False
        remove_indexes: list[int] = []
        split_parent_ids: list[object] = []
        for index, box in enumerate(boxes):
            box_x = float(box["x"]) * image_width / coordinate_size
            box_y = float(box["y"]) * image_height / coordinate_size
            box_width = float(box["width"]) * image_width / coordinate_size
            box_height = float(box["height"]) * image_height / coordinate_size
            if box.get("circle_candidate"):
                existing_center_x = box_x + box_width / 2.0
                existing_center_y = box_y + box_height / 2.0
                center_distance = math.hypot(
                    existing_center_x - center_x,
                    existing_center_y - center_y,
                )
                if center_distance <= 0.75 * max(
                    radius,
                    box_width / 2.0,
                    box_height / 2.0,
                ):
                    if box_width * box_height >= circle_area:
                        duplicate = True
                        break
                    remove_indexes.append(index)
                continue

            center_inside = (
                box_x <= center_x <= box_x + box_width
                and box_y <= center_y <= box_y + box_height
            )
            if center_inside:
                box_area = box_width * box_height
                box_aspect = max(
                    box_width / max(box_height, 1.0),
                    box_height / max(box_width, 1.0),
                )
                oversized_color_component = (
                    box.get("color_candidate")
                    and box_aspect >= 1.25
                    and box_area > circle_area * 1.15
                )
                if oversized_color_component:
                    parent_id = box.setdefault(
                        "circle_split_parent_id",
                        id(box),
                    )
                    box["circle_split_parent_candidate"] = True
                    split_parent_ids.append(parent_id)
                    continue
                if box_area >= circle_area * 0.50:
                    duplicate = True
                    break
                if box.get("color_candidate"):
                    remove_indexes.append(index)
        if duplicate:
            continue
        for index in reversed(remove_indexes):
            del boxes[index]
        circle_box = {
            "label": "tennis_ball",
            "value": 1.0,
            "x": (center_x - radius) * coordinate_size / image_width,
            "y": (center_y - radius) * coordinate_size / image_height,
            "width": 2 * radius * coordinate_size / image_width,
            "height": 2 * radius * coordinate_size / image_height,
            "highlight_candidate": True,
            "circle_candidate": True,
        }
        if split_parent_ids:
            circle_box["circle_split_candidate"] = True
            circle_box["circle_split_parent_ids"] = tuple(split_parent_ids)
        boxes.append(circle_box)

    split_counts: dict[object, int] = {}
    for box in boxes:
        for parent_id in box.get("circle_split_parent_ids", ()):
            split_counts[parent_id] = split_counts.get(parent_id, 0) + 1
    multi_circle_parent_ids = {
        parent_id
        for parent_id, count in split_counts.items()
        if count >= 2
    }

    retained_boxes = []
    for box in boxes:
        parent_id = box.get("circle_split_parent_id")
        if (
            box.get("circle_split_parent_candidate")
            and parent_id not in multi_circle_parent_ids
        ):
            box.pop("circle_split_parent_id", None)
            box.pop("circle_split_parent_candidate", None)

        child_parent_ids = tuple(
            parent_id
            for parent_id in box.get("circle_split_parent_ids", ())
            if parent_id in multi_circle_parent_ids
        )
        if box.get("circle_split_candidate") and not child_parent_ids:
            continue
        if child_parent_ids:
            box["circle_split_parent_ids"] = child_parent_ids
        retained_boxes.append(box)
    boxes[:] = retained_boxes


def _append_local_highlight_candidates(
    preview_rgb: np.ndarray,
    config: CandidateFilterConfig,
    coordinate_size: int,
    boxes: list[dict],
    color_mask: np.ndarray,
    highlight_mask: np.ndarray,
) -> None:
    """Grow a small color seed into a nearby bright-ball proposal.

    Hough circles can miss a ball when the outer edge is washed out. If a
    small tennis-color fragment is next to a compact bright component, use
    their union as a local proposal. Large bright regions are ignored so
    windows, walls and floor reflections do not become global candidates.
    """
    image_height, image_width = preview_rgb.shape[:2]
    image_area = float(image_width * image_height)
    bright_contours, _ = cv2.findContours(
        highlight_mask,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )
    bright_regions: list[tuple[float, int, int, int, int, float, float]] = []
    for contour in bright_contours:
        contour_area = float(cv2.contourArea(contour))
        x, y, width, height = cv2.boundingRect(contour)
        if contour_area / image_area < config.object_area_min * 0.5:
            continue
        if contour_area / image_area > 0.08:
            continue
        if max(width, height) > min(image_width, image_height) * 0.35:
            continue
        moments = cv2.moments(contour)
        if moments["m00"] <= 0:
            continue
        center_x = moments["m10"] / moments["m00"]
        center_y = moments["m01"] / moments["m00"]
        bright_regions.append(
            (contour_area, x, y, width, height, center_x, center_y)
        )

    existing = list(boxes)
    for box in existing:
        if not box.get("color_candidate"):
            continue
        seed_x = float(box["x"]) * image_width / coordinate_size
        seed_y = float(box["y"]) * image_height / coordinate_size
        seed_width = float(box["width"]) * image_width / coordinate_size
        seed_height = float(box["height"]) * image_height / coordinate_size
        seed_area = seed_width * seed_height
        if seed_area / image_area > 0.04:
            continue
        seed_center_x = seed_x + seed_width / 2.0
        seed_center_y = seed_y + seed_height / 2.0
        nearest = None
        for region in bright_regions:
            _, bright_x, bright_y, bright_width, bright_height, bright_center_x, bright_center_y = region
            search_distance = (
                max(seed_width, seed_height) * 2.0
                + max(bright_width, bright_height) * 0.75
            )
            distance = math.hypot(
                bright_center_x - seed_center_x,
                bright_center_y - seed_center_y,
            )
            if distance > search_distance:
                continue
            candidate = (distance, region)
            if nearest is None or candidate[0] < nearest[0]:
                nearest = candidate
        if nearest is None:
            continue

        _, (_, bright_x, bright_y, bright_width, bright_height, _, _) = nearest
        union_x0 = min(seed_x, float(bright_x))
        union_y0 = min(seed_y, float(bright_y))
        union_x1 = max(seed_x + seed_width, float(bright_x + bright_width))
        union_y1 = max(seed_y + seed_height, float(bright_y + bright_height))
        union_width = union_x1 - union_x0
        union_height = union_y1 - union_y0
        if union_width <= 0 or union_height <= 0:
            continue
        aspect = max(
            union_width / union_height,
            union_height / union_width,
        )
        if aspect > 2.5:
            continue
        if union_width * union_height <= seed_area * 1.8:
            continue

        duplicate = False
        union_area = union_width * union_height
        for existing_box in boxes:
            if not existing_box.get("circle_candidate"):
                continue
            existing_x = float(existing_box["x"]) * image_width / coordinate_size
            existing_y = float(existing_box["y"]) * image_height / coordinate_size
            existing_width = float(existing_box["width"]) * image_width / coordinate_size
            existing_height = float(existing_box["height"]) * image_height / coordinate_size
            existing_center_x = existing_x + existing_width / 2.0
            existing_center_y = existing_y + existing_height / 2.0
            if (
                union_x0 <= existing_center_x <= union_x1
                and union_y0 <= existing_center_y <= union_y1
                and existing_width * existing_height >= union_area * 0.50
            ):
                duplicate = True
                break
        if duplicate:
            boxes[:] = [item for item in boxes if item is not box]
            continue

        replacement = {
            "label": "tennis_ball",
            "value": 1.0,
            "x": union_x0 * coordinate_size / image_width,
            "y": union_y0 * coordinate_size / image_height,
            "width": union_width * coordinate_size / image_width,
            "height": union_height * coordinate_size / image_height,
            "highlight_candidate": True,
            "local_highlight_candidate": True,
        }
        boxes[:] = [item for item in boxes if item is not box]
        boxes.append(replacement)


def find_color_candidate_boxes(
    preview_rgb: np.ndarray,
    config: CandidateFilterConfig,
    coordinate_size: int = 1000,
    color_mask: np.ndarray | None = None,
    highlight_mask: np.ndarray | None = None,
) -> list[dict]:
    """Create safe candidate boxes when an Edge Impulse model is absent."""
    if coordinate_size <= 0:
        raise ValueError("coordinate_size must be positive")

    image_height, image_width = preview_rgb.shape[:2]
    mask = (
        color_mask
        if color_mask is not None
        else _tennis_color_mask(preview_rgb, config)
    )
    if highlight_mask is None:
        highlight_mask = _highlight_mask(preview_rgb, config)
    contours, _ = cv2.findContours(
        mask,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )
    contours = sorted(contours, key=cv2.contourArea, reverse=True)

    boxes: list[dict] = []
    image_area = float(image_width * image_height)
    for contour in contours:
        contour_area = float(cv2.contourArea(contour))
        if contour_area / image_area < config.object_area_min:
            continue

        x, y, width, height = cv2.boundingRect(contour)
        boxes.append(
            {
                "label": "tennis_ball",
                "value": 1.0,
                "x": x * coordinate_size / image_width,
                "y": y * coordinate_size / image_height,
                "width": width * coordinate_size / image_width,
                "height": height * coordinate_size / image_height,
                "color_candidate": True,
            }
        )

    _append_bright_circle_candidates(
        preview_rgb,
        config,
        coordinate_size,
        boxes,
        color_mask=mask,
        highlight_mask=highlight_mask,
    )
    _append_component_circle_candidates(
        preview_rgb,
        config,
        coordinate_size,
        boxes,
        mask,
        highlight_mask,
    )
    _append_local_highlight_candidates(
        preview_rgb,
        config,
        coordinate_size,
        boxes,
        mask,
        highlight_mask,
    )
    return boxes


def evaluate_candidate(
    preview_rgb: np.ndarray,
    detection: dict,
    model_width: int,
    model_height: int,
    config: CandidateFilterConfig,
    color_mask: np.ndarray | None = None,
    highlight_mask: np.ndarray | None = None,
) -> CandidateMetrics:
    confidence = float(detection["value"])
    confidence_threshold = (
        config.glare_confidence_threshold
        if bool(detection.get("highlight_candidate"))
        else config.confidence_threshold
    )
    if confidence < confidence_threshold:
        return _rejected("confidence")

    box_x = float(detection["x"])
    box_y = float(detection["y"])
    box_width = float(detection["width"])
    box_height = float(detection["height"])
    if box_width <= 0 or box_height <= 0:
        return _rejected("empty_box")

    image_height, image_width = preview_rgb.shape[:2]
    center_x = box_x + box_width / 2.0
    center_y = box_y + box_height / 2.0
    candidate_x = center_x * image_width / model_width
    candidate_y = center_y * image_height / model_height

    if color_mask is None:
        color_mask = _tennis_color_mask(preview_rgb, config)
    if bool(detection.get("circle_candidate")):
        center_x = int(round(candidate_x))
        center_y = int(round(candidate_y))
        radius = int(round(max(
            box_width * image_width / model_width,
            box_height * image_height / model_height,
        ) / 2.0))
        disk = np.zeros_like(color_mask)
        cv2.circle(disk, (center_x, center_y), radius, 255, -1)
        evidence = cv2.bitwise_or(
            color_mask,
            highlight_mask
            if highlight_mask is not None
            else _highlight_mask(preview_rgb, config),
        )
        evidence_ratio = (
            float(cv2.countNonZero(cv2.bitwise_and(evidence, disk)))
            / float(max(cv2.countNonZero(disk), 1))
        )
        if evidence_ratio < config.glare_coverage_min:
            return _rejected("glare_coverage")
        mask = disk
    elif bool(detection.get("local_highlight_candidate")):
        mask = _add_local_highlight_pixels(
            preview_rgb,
            color_mask,
            detection,
            model_width,
            model_height,
            config,
            highlight_mask=highlight_mask,
        )
    elif bool(detection.get("highlight_candidate")):
        mask = cv2.bitwise_or(
            color_mask,
            highlight_mask
            if highlight_mask is not None
            else _highlight_mask(preview_rgb, config),
        )
    else:
        # A normal color proposal already has enough tennis-color evidence.
        # Keep its geometry tied to that source contour; otherwise a white
        # table, hand or label touching the ball can be absorbed as glare.
        # Mostly-white balls use the explicit circle/local-highlight branches
        # above, where white evidence is bounded by a dedicated proposal.
        mask = color_mask

    contours, _ = cv2.findContours(
        mask,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )
    if not contours:
        return _rejected("tennis_color")

    contour: np.ndarray | None = None
    if bool(detection.get("color_candidate")):
        expected_x = box_x * image_width / model_width
        expected_y = box_y * image_height / model_height
        expected_width = box_width * image_width / model_width
        expected_height = box_height * image_height / model_height
        ranked = []
        for possible_contour in contours:
            rect_x, rect_y, rect_width, rect_height = cv2.boundingRect(
                possible_contour
            )
            boundary_error = (
                abs(rect_x - expected_x)
                + abs(rect_y - expected_y)
                + abs(rect_width - expected_width)
                + abs(rect_height - expected_height)
            )
            ranked.append((boundary_error, possible_contour))
        if ranked:
            boundary_error, possible_contour = min(
                ranked,
                key=lambda item: item[0],
            )
            if boundary_error <= 4.0:
                contour = possible_contour

    if contour is None:
        containing = [
            possible_contour
            for possible_contour in contours
            if cv2.pointPolygonTest(
                possible_contour,
                (float(candidate_x), float(candidate_y)),
                False,
            )
            >= 0
        ]

        if containing:
            contour = max(containing, key=cv2.contourArea)

    if contour is None:
        maximum_distance = max(
            box_width * image_width / model_width,
            box_height * image_height / model_height,
        ) * config.crop_expansion
        nearest: tuple[float, np.ndarray] | None = None
        for possible_contour in contours:
            moments = cv2.moments(possible_contour)
            if moments["m00"] <= 0:
                continue
            possible_x = moments["m10"] / moments["m00"]
            possible_y = moments["m01"] / moments["m00"]
            distance = math.hypot(
                possible_x - candidate_x,
                possible_y - candidate_y,
            )
            if nearest is None or distance < nearest[0]:
                nearest = (distance, possible_contour)
        if nearest is None or nearest[0] > maximum_distance:
            return _rejected("tennis_color")
        contour = nearest[1]

    contour_area = float(cv2.contourArea(contour))
    perimeter = float(cv2.arcLength(contour, True))
    contour_x, contour_y, contour_width, contour_height = cv2.boundingRect(
        contour
    )
    contour_mask = mask[
        contour_y:contour_y + contour_height,
        contour_x:contour_x + contour_width,
    ]
    color_ratio = (
        float(cv2.countNonZero(contour_mask))
        / float(max(contour_mask.size, 1))
    )

    contour_aspect = max(
        contour_width / max(contour_height, 1),
        contour_height / max(contour_width, 1),
    )
    extent = contour_area / float(max(contour_width * contour_height, 1))
    circularity = (
        4.0 * math.pi * contour_area / (perimeter * perimeter)
        if perimeter > 0
        else 0.0
    )
    hull_area = float(cv2.contourArea(cv2.convexHull(contour)))
    solidity = contour_area / hull_area if hull_area > 0 else 0.0
    object_area_ratio = contour_area / float(image_width * image_height)
    moments = cv2.moments(contour)
    object_center = (
        (
            moments["m10"] / moments["m00"],
            moments["m01"] / moments["m00"],
        )
        if moments["m00"] > 0
        else (float(candidate_x), float(candidate_y))
    )

    reasons: list[str] = []
    if color_ratio < config.color_ratio_min:
        reasons.append("tennis_color")
    if object_area_ratio < config.object_area_min:
        reasons.append("too_small")
    trained_shape_relax = (
        bool(detection.get("trained_verifier"))
        and confidence >= config.trained_confidence_relax
    )
    circularity_threshold = config.circularity_min
    extent_min = config.extent_min
    extent_max = config.extent_max
    solidity_min = config.solidity_min
    aspect_max = config.aspect_max
    if trained_shape_relax:
        circularity_threshold = config.trained_circularity_min
        extent_min = config.trained_extent_min
        extent_max = config.trained_extent_max
        solidity_min = config.trained_solidity_min
        aspect_max = config.trained_aspect_max
    if circularity < circularity_threshold and object_area_ratio < 0.15:
        reasons.append("not_round")
    if not extent_min <= extent <= extent_max:
        reasons.append("shape_fill")
    if solidity < solidity_min:
        reasons.append("irregular_shape")
    if contour_aspect > aspect_max:
        reasons.append("shape_aspect")

    return CandidateMetrics(
        accepted=not reasons,
        color_ratio=color_ratio,
        circularity=circularity,
        extent=extent,
        solidity=solidity,
        aspect=contour_aspect,
        object_area_ratio=object_area_ratio,
        object_center=object_center,
        object_contour=contour,
        reasons=tuple(reasons),
    )


class TargetConfirmation:
    def __init__(self, required_frames: int, max_jump: float) -> None:
        self.required_frames = required_frames
        self.max_jump = max_jump
        self.count = 0
        self._last_center: tuple[float, float] | None = None

    def update(self, center_x: float, center_y: float) -> bool:
        center = (center_x, center_y)
        if self._last_center is None:
            self.count = 1
        else:
            distance = math.hypot(
                center_x - self._last_center[0],
                center_y - self._last_center[1],
            )
            self.count = self.count + 1 if distance <= self.max_jump else 1
        self._last_center = center
        return self.count >= self.required_frames

    def reset(self) -> None:
        self.count = 0
        self._last_center = None
