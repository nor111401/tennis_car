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
    trained_circularity_min: float = 0.16
    extent_min: float = 0.30
    extent_max: float = 0.92
    solidity_min: float = 0.72
    aspect_max: float = 1.85
    object_area_min: float = 0.0005
    crop_expansion: float = 2.50
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
                0.16,
            ),
            extent_min=_env_float("TENNIS_EXTENT_MIN", 0.30),
            extent_max=_env_float("TENNIS_EXTENT_MAX", 0.92),
            solidity_min=_env_float("TENNIS_SOLIDITY_MIN", 0.72),
            aspect_max=_env_float("TENNIS_ASPECT_MAX", 1.85),
            object_area_min=_env_float(
                "TENNIS_OBJECT_AREA_MIN",
                0.0005,
            ),
            crop_expansion=_env_float("TENNIS_CROP_EXPANSION", 2.50),
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
        if not 0 <= self.solidity_min <= 1:
            raise ValueError("solidity_min must be between 0 and 1")
        if self.aspect_max < 1:
            raise ValueError("aspect_max must be at least 1")
        if not 0 <= self.object_area_min < 1:
            raise ValueError("object_area_min must be within [0, 1)")
        if self.crop_expansion < 1:
            raise ValueError("crop_expansion must be at least 1")
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
) -> float:
    mask = _tennis_color_mask(preview_rgb, config, clean=False)
    return float(cv2.countNonZero(mask)) / float(mask.size)


def _tennis_color_mask(
    preview_rgb: np.ndarray,
    config: CandidateFilterConfig,
    clean: bool = True,
) -> np.ndarray:
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


def find_color_candidate_boxes(
    preview_rgb: np.ndarray,
    config: CandidateFilterConfig,
    coordinate_size: int = 1000,
) -> list[dict]:
    """Create safe candidate boxes when an Edge Impulse model is absent."""
    if coordinate_size <= 0:
        raise ValueError("coordinate_size must be positive")

    image_height, image_width = preview_rgb.shape[:2]
    mask = _tennis_color_mask(preview_rgb, config)
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
            }
        )
    return boxes


def evaluate_candidate(
    preview_rgb: np.ndarray,
    detection: dict,
    model_width: int,
    model_height: int,
    config: CandidateFilterConfig,
) -> CandidateMetrics:
    confidence = float(detection["value"])
    if confidence < config.confidence_threshold:
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

    mask = _tennis_color_mask(preview_rgb, config)

    contours, _ = cv2.findContours(
        mask,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )
    if not contours:
        return _rejected("tennis_color")

    containing = [
        contour
        for contour in contours
        if cv2.pointPolygonTest(
            contour,
            (float(candidate_x), float(candidate_y)),
            False,
        )
        >= 0
    ]

    if containing:
        contour = max(containing, key=cv2.contourArea)
    else:
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
    circularity_threshold = config.circularity_min
    if (
        bool(detection.get("trained_verifier"))
        and confidence >= config.trained_confidence_relax
    ):
        circularity_threshold = config.trained_circularity_min
    if circularity < circularity_threshold and object_area_ratio < 0.15:
        reasons.append("not_round")
    if not config.extent_min <= extent <= config.extent_max:
        reasons.append("shape_fill")
    if solidity < config.solidity_min:
        reasons.append("irregular_shape")
    if contour_aspect > config.aspect_max:
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
