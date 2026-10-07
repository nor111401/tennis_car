from pathlib import Path
import os
import time

import cv2

try:
    from picamera2 import Picamera2
except ModuleNotFoundError:
    Picamera2 = None

try:
    from edge_impulse_linux.image import ImageImpulseRunner
except ModuleNotFoundError:
    ImageImpulseRunner = None

from tennis_candidate_filter import (
    CandidateFilterConfig,
    MultiBallTracker,
    TemporalTargetTracker,
    TargetConfirmation,
    build_candidate_masks,
    evaluate_candidate,
    find_color_candidate_boxes,
    resolve_verified_circle_splits,
    tennis_color_coverage,
)
from tennis_ball_verifier import TennisBallVerifier, expanded_crop
from zmotord_uart import MotorController


CAMERA_WIDTH = 1296
CAMERA_HEIGHT = 972
CAMERA_FPS = 40
CAMERA_SHARPNESS = 2.0

DIGITAL_ZOOM = max(
    1.0,
    float(os.environ.get("TENNIS_DIGITAL_ZOOM", "1.0"))
)

FILTER_CONFIG = CandidateFilterConfig.from_environment()
CONFIDENCE_THRESHOLD = FILTER_CONFIG.confidence_threshold
DISPLAY_MAX_SIZE = 640

SHOW_WINDOW = bool(os.environ.get("DISPLAY"))
FILTER_SNAPSHOT_PATH = os.environ.get("TENNIS_FILTER_SNAPSHOT")


def find_model_file(folder):
    model_files = sorted(folder.glob("*.eim"))

    if not model_files:
        return None

    if len(model_files) > 1:
        print("Multiple .eim files found:")

        for model_file in model_files:
            print(f"  {model_file.name}")

        print(f"Using: {model_files[0].name}")

    return model_files[0]


class ColorOnlyRunner:
    """Edge Impulse-compatible local color proposal and trained verifier."""

    coordinate_size = 1000

    def __init__(self, config, verifier_path=None):
        self.config = config
        self.verifier = (
            TennisBallVerifier(verifier_path)
            if verifier_path is not None
            else None
        )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return None

    def init(self):
        project_name = (
            "local trained tennis verifier"
            if self.verifier is not None
            else "tennis color/shape fallback"
        )
        return {
            "project": {
                "owner": "local",
                "name": project_name,
            },
            "model_parameters": {
                "labels": ["tennis_ball"],
                "image_input_width": self.coordinate_size,
                "image_input_height": self.coordinate_size,
            },
        }

    def get_features_from_image(self, image_rgb):
        return center_crop_square(image_rgb), None

    def classify(self, preview_rgb):
        start_time = time.perf_counter()
        color_mask, highlight_mask = build_candidate_masks(
            preview_rgb,
            self.config,
        )
        boxes = find_color_candidate_boxes(
            preview_rgb,
            self.config,
            self.coordinate_size,
            color_mask=color_mask,
            highlight_mask=highlight_mask,
        )
        if self.verifier is not None:
            image_height, image_width = preview_rgb.shape[:2]
            for box in boxes:
                pixel_box = (
                    float(box["x"]) * image_width / self.coordinate_size,
                    float(box["y"]) * image_height / self.coordinate_size,
                    float(box["width"]) * image_width / self.coordinate_size,
                    float(box["height"]) * image_height / self.coordinate_size,
                )
                patch = expanded_crop(preview_rgb, pixel_box)
                if box.get("highlight_candidate"):
                    box["value"] = self.verifier.predict_probability(patch)
                    box["glare_candidate"] = True
                else:
                    box["value"] = self.verifier.predict_probability(patch)
                    box["trained_verifier"] = True
        elapsed_ms = int(round((time.perf_counter() - start_time) * 1000))
        return {
            "result": {
                "bounding_boxes": boxes,
                "_candidate_masks": (color_mask, highlight_mask),
            },
            "timing": {"dsp": 0, "classification": elapsed_ms},
        }


def build_runner_context(project_folder):
    """Select the same inference backend for CLI and gateway execution."""
    model_path = find_model_file(project_folder)
    if model_path is None:
        verifier_path = project_folder / "tennis_ball_verifier.npz"
        if verifier_path.exists():
            print(f"Model: {verifier_path.name} (local trained verifier)")
            return ColorOnlyRunner(FILTER_CONFIG, verifier_path)
        print("Model: not found; using color/shape fallback mode")
        return ColorOnlyRunner(FILTER_CONFIG)

    print(f"Model: {model_path}")
    if not os.access(model_path, os.X_OK):
        raise PermissionError(
            f"{model_path.name} is not executable. "
            f"Run: chmod +x {model_path.name}"
        )
    if ImageImpulseRunner is None:
        raise RuntimeError(
            "edge_impulse_linux is required when a .eim model is present"
        )
    return ImageImpulseRunner(str(model_path))


def get_position(center_x, image_width):
    left_boundary = image_width / 3
    right_boundary = image_width * 2 / 3

    if center_x < left_boundary:
        return "LEFT"

    if center_x > right_boundary:
        return "RIGHT"

    return "CENTER"


def apply_center_zoom(image, zoom):
    if zoom <= 1.0:
        return image

    height, width = image.shape[:2]

    crop_width = max(1, int(round(width / zoom)))
    crop_height = max(1, int(round(height / zoom)))

    x = max(0, (width - crop_width) // 2)
    y = max(0, (height - crop_height) // 2)

    return image[
        y:y + crop_height,
        x:x + crop_width
    ]


def center_crop_square(image):
    height, width = image.shape[:2]
    side = min(width, height)

    x = max(0, (width - side) // 2)
    y = max(0, (height - side) // 2)

    return image[
        y:y + side,
        x:x + side
    ]


def resize_for_display(image):
    height, width = image.shape[:2]

    largest_dimension = max(width, height)

    if largest_dimension <= 0:
        return image, 1.0

    scale = min(
        DISPLAY_MAX_SIZE / largest_dimension,
        1.0
    )

    display_width = int(round(width * scale))
    display_height = int(round(height * scale))

    resized = cv2.resize(
        image,
        (display_width, display_height),
        interpolation=cv2.INTER_AREA
    )

    return resized, scale


def draw_vehicle_status(display, motion, motor_controller):
    motion_text = motion.value.replace("_", " ")
    if motion.value == "STOP":
        color = (0, 0, 255)
    elif motion.value == "FORWARD":
        color = (0, 255, 0)
    else:
        color = (0, 165, 255)

    mode_text = "LIVE" if motor_controller.config.enabled else "DRY RUN"
    cv2.putText(
        display,
        f"CAR: {motion_text} [{mode_text}]",
        (15, 90),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.70,
        color,
        2,
    )

    cv2.putText(
        display,
        f"SEARCH: {motor_controller.search_status}",
        (15, 150),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.60,
        (255, 0, 255),
        2,
    )

    cv2.putText(
        display,
        (
            f"PWM: {motor_controller.active_high_pwm}/"
            f"{motor_controller.active_low_pwm} "
            f"T{motor_controller.active_command_time_ms}ms"
        ),
        (15, 120),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        color,
        2,
    )


def draw_detection(
    display,
    detection,
    scale_x,
    scale_y,
    color=(0, 255, 0),
    suffix="",
):
    x = int(detection["x"] * scale_x)
    y = int(detection["y"] * scale_y)
    width = int(detection["width"] * scale_x)
    height = int(detection["height"] * scale_y)

    confidence = float(detection["value"])
    label = detection["label"]

    x2 = x + width
    y2 = y + height

    cv2.rectangle(
        display,
        (x, y),
        (x2, y2),
        color,
        2
    )

    text = f"{label} {confidence:.2f}{suffix}"

    text_y = y - 8

    if text_y < 20:
        text_y = y + 22

    cv2.putText(
        display,
        text,
        (x, text_y),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        color,
        2
    )


def should_draw_filtered_contour(detection):
    """Keep accepted-ball contours hidden in the operator video."""
    return False


def target_center_marker_color(target, primary_target, primary_confirmed=True):
    """Confirmed primary is red, provisional primary yellow, other balls blue."""
    if (
        primary_target is not None
        and target.track_id == primary_target.track_id
    ):
        return (0, 0, 255) if primary_confirmed else (0, 255, 255)
    return (255, 0, 0)


def draw_target_center_markers(
    display,
    visible_targets,
    primary_target,
    model_width,
    model_height,
    scale_x,
    scale_y,
    primary_confirmed=True,
):
    """Draw only center dots; render the primary target last."""
    ordered_targets = sorted(
        visible_targets,
        key=lambda target: (
            primary_target is not None
            and target.track_id == primary_target.track_id
        ),
    )
    for target in ordered_targets:
        center_x = int(target.center_x * model_width * scale_x)
        center_y = int(target.center_y * model_height * scale_y)
        cv2.circle(
            display,
            (center_x, center_y),
            5,
            target_center_marker_color(target, primary_target, primary_confirmed),
            -1,
        )


def draw_filtered_contour(
    display,
    detection,
    metrics,
    scale,
):
    if not should_draw_filtered_contour(detection):
        return

    contour = metrics.object_contour
    if contour is None:
        return

    scaled_contour = (
        contour.astype("float32") * scale
    ).astype("int32")
    cv2.drawContours(
        display,
        [scaled_contour],
        -1,
        (0, 255, 0),
        3,
    )

    x, y, _, _ = cv2.boundingRect(scaled_contour)
    text_y = y - 8 if y >= 25 else y + 22
    cv2.putText(
        display,
        (
            f"tennis_ball {float(detection['value']):.2f} "
            f"area={metrics.object_area_ratio:.2f}"
        ),
        (x, text_y),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (0, 255, 0),
        2,
    )


def recover_candidate_near_target(
    preview_rgb,
    previous,
    model_width,
    model_height,
    color_mask=None,
    highlight_mask=None,
):
    """Re-detect the previous target using evidence from the current frame."""
    previous_confidence = float(previous.current_item[0].get("value", 0.0))
    minimum_confidence = (
        FILTER_CONFIG.glare_confidence_threshold
        if previous.source == "glare"
        else FILTER_CONFIG.confidence_threshold
    )
    confidence = max(minimum_confidence, previous_confidence * 0.85)
    width = min(1.0, max(previous.width * 1.20, 0.02))
    height = min(1.0, max(previous.height * 1.20, 0.02))
    x0 = max(0.0, previous.center_x - width / 2.0)
    y0 = max(0.0, previous.center_y - height / 2.0)
    x1 = min(1.0, previous.center_x + width / 2.0)
    y1 = min(1.0, previous.center_y + height / 2.0)
    detection = {
        "label": "tennis_ball",
        "value": confidence,
        "x": x0 * model_width,
        "y": y0 * model_height,
        "width": (x1 - x0) * model_width,
        "height": (y1 - y0) * model_height,
        "color_candidate": True,
        "local_highlight_candidate": True,
        "temporal_recovery_candidate": True,
    }
    if previous.source == "glare":
        detection["highlight_candidate"] = True

    metrics = evaluate_candidate(
        preview_rgb,
        detection,
        model_width,
        model_height,
        FILTER_CONFIG,
        color_mask=color_mask,
        highlight_mask=highlight_mask,
    )
    if not metrics.accepted or metrics.object_center is None:
        return None

    image_height, image_width = preview_rgb.shape[:2]
    recovered_x = float(metrics.object_center[0]) / image_width
    recovered_y = float(metrics.object_center[1]) / image_height
    displacement = (
        (recovered_x - previous.center_x) ** 2
        + (recovered_y - previous.center_y) ** 2
    ) ** 0.5
    allowed_displacement = max(
        0.04,
        min(0.15, 1.50 * max(previous.width, previous.height)),
    )
    if displacement > allowed_displacement:
        return None
    return detection, metrics


def recover_tracked_candidate(
    preview_rgb,
    target_tracker,
    model_width,
    model_height,
    color_mask=None,
    highlight_mask=None,
):
    """Compatibility wrapper that recovers the selected target only."""
    previous = target_tracker.current_target()
    if previous is None:
        return None
    return recover_candidate_near_target(
        preview_rgb,
        previous,
        model_width,
        model_height,
        color_mask=color_mask,
        highlight_mask=highlight_mask,
    )


def _candidate_view_geometry(
    item,
    image_width,
    image_height,
    model_width,
    model_height,
):
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
    return center_x, center_y, width, height


def _item_matches_target(
    item,
    target,
    image_width,
    image_height,
    model_width,
    model_height,
):
    center_x, center_y, width, height = _candidate_view_geometry(
        item,
        image_width,
        image_height,
        model_width,
        model_height,
    )
    allowed_distance = max(
        0.035,
        min(
            0.15,
            0.85 * (
                max(target.width, target.height) + max(width, height)
            ) / 2.0,
        ),
    )
    return (
        (center_x - target.center_x) ** 2
        + (center_y - target.center_y) ** 2
    ) ** 0.5 <= allowed_distance


def _same_current_object(
    left,
    right,
    image_width,
    image_height,
    model_width,
    model_height,
):
    left_x, left_y, left_width, left_height = _candidate_view_geometry(
        left,
        image_width,
        image_height,
        model_width,
        model_height,
    )
    right_x, right_y, right_width, right_height = _candidate_view_geometry(
        right,
        image_width,
        image_height,
        model_width,
        model_height,
    )
    allowed_distance = max(
        0.035,
        min(
            0.15,
            0.75 * (
                max(left_width, left_height)
                + max(right_width, right_height)
            ) / 2.0,
        ),
    )
    return ((left_x - right_x) ** 2 + (left_y - right_y) ** 2) ** 0.5 <= (
        allowed_distance
    )


def recover_missing_tracked_candidates(
    preview_rgb,
    target_tracker,
    accepted,
    model_width,
    model_height,
    color_mask=None,
    highlight_mask=None,
):
    """Recover each missing track independently from current-frame pixels."""
    if hasattr(target_tracker, "current_targets"):
        previous_targets = target_tracker.current_targets()
    else:
        previous = target_tracker.current_target()
        previous_targets = () if previous is None else (previous,)

    image_height, image_width = preview_rgb.shape[:2]
    current_items = list(accepted)
    recovered_items = []
    for previous in previous_targets:
        if any(
            _item_matches_target(
                item,
                previous,
                image_width,
                image_height,
                model_width,
                model_height,
            )
            for item in current_items
        ):
            continue
        recovered = recover_candidate_near_target(
            preview_rgb,
            previous,
            model_width,
            model_height,
            color_mask=color_mask,
            highlight_mask=highlight_mask,
        )
        if recovered is None:
            continue
        if any(
            _same_current_object(
                recovered,
                item,
                image_width,
                image_height,
                model_width,
                model_height,
            )
            for item in current_items
        ):
            continue
        recovered_items.append(recovered)
        current_items.append(recovered)
    return recovered_items


def process_bounding_boxes(
    result,
    preview_rgb,
    model_width,
    model_height,
    target_confirmation,
    target_tracker,
    log_events=True,
):
    boxes = result["result"].get(
        "bounding_boxes",
        []
    )
    candidate_masks = result["result"].get("_candidate_masks", ())
    color_mask = candidate_masks[0] if len(candidate_masks) >= 1 else None
    highlight_mask = (
        candidate_masks[1] if len(candidate_masks) >= 2 else None
    )

    evaluated = [
        (
            box,
            evaluate_candidate(
                preview_rgb,
                box,
                model_width,
                model_height,
                FILTER_CONFIG,
                color_mask=color_mask,
                highlight_mask=highlight_mask,
            ),
        )
        for box in boxes
        if float(box["value"]) >= (
            FILTER_CONFIG.glare_confidence_threshold
            if box.get("highlight_candidate")
            else CONFIDENCE_THRESHOLD
        )
    ]
    accepted = resolve_verified_circle_splits([
        item for item in evaluated if item[1].accepted
    ])
    rejected = [item for item in evaluated if not item[1].accepted]

    frame_color_coverage = tennis_color_coverage(
        preview_rgb,
        FILTER_CONFIG,
        color_mask=color_mask,
    )
    too_close = (
        not accepted
        and frame_color_coverage >= FILTER_CONFIG.close_color_coverage
    )
    if not too_close:
        recovered = recover_missing_tracked_candidates(
            preview_rgb,
            target_tracker,
            accepted,
            model_width,
            model_height,
            color_mask=color_mask,
            highlight_mask=highlight_mask,
        )
        if recovered:
            had_accepted = bool(accepted)
            accepted.extend(recovered)
            if not had_accepted:
                rejected = []

    accepted.sort(
        key=lambda item: (
            item[1].object_area_ratio,
            float(item[0]["value"]),
        ),
        reverse=True,
    )

    preview_bgr = cv2.cvtColor(
        preview_rgb,
        cv2.COLOR_RGB2BGR
    )

    display, scale = resize_for_display(
        preview_bgr
    )

    scale_x = (
        preview_rgb.shape[1]
        / model_width
        * scale
    )
    scale_y = (
        preview_rgb.shape[0]
        / model_height
        * scale
    )

    for box, metrics in rejected:
        reason = metrics.reasons[0] if metrics.reasons else "shape"
        draw_detection(
            display,
            box,
            scale_x,
            scale_y,
            color=(0, 0, 255),
            suffix=f" reject:{reason}",
        )

    if too_close:
        target_tracker.reset()
        tracked_target = None
        visible_targets = ()
        primary_changed = False
    else:
        tracking_result = target_tracker.update(
            accepted,
            preview_rgb.shape[1],
            preview_rgb.shape[0],
            model_width,
            model_height,
        )
        if hasattr(tracking_result, "visible_targets"):
            visible_targets = tracking_result.visible_targets
            tracked_target = tracking_result.primary_target
            primary_changed = tracking_result.primary_changed
        else:
            tracked_target = tracking_result
            visible_targets = (
                () if tracked_target is None else (tracked_target,)
            )
            primary_changed = False
    related_box_ids = frozenset(
        box_id
        for target in visible_targets
        for box_id in target.related_box_ids
    )
    for box, metrics in accepted:
        if id(box) in related_box_ids:
            continue
        draw_filtered_contour(display, box, metrics, scale)
    for visible_target in visible_targets:
        display_box, display_metrics = visible_target.display_item
        draw_filtered_contour(
            display,
            display_box,
            display_metrics,
            scale,
        )

    if primary_changed:
        target_confirmation.reset()

    target_item = (
        tracked_target.current_item
        if tracked_target is not None
        else None
    )
    observation = {
        "detected": False,
        "candidate_visible": target_item is not None,
        "confidence": 0.0,
        "ball_x": None,
        "ball_y": None,
        "ball_width": None,
        "ball_height": None,
        "bottom_exit_loss": False,
        "vision_status": "VERIFYING",
    }

    if target_item is not None:
        target, metrics = target_item
        center_x = tracked_target.center_x * model_width
        center_y = tracked_target.center_y * model_height

        detected_position = get_position(
            center_x,
            model_width
        )

        confirmed = target_confirmation.update(
            center_x / model_width,
            center_y / model_height,
        )
        position = detected_position if confirmed else "LOST"
        target_x = center_x / model_width if confirmed else None
        confidence = float(target["value"])

        area_ratio = tracked_target.area_ratio

        if confirmed:
            observation.update({
                "vision_status": "CONFIRMED",
                "detected": True,
                "confidence": confidence,
                "ball_x": tracked_target.center_x,
                "ball_y": tracked_target.center_y,
                "ball_width": tracked_target.width,
                "ball_height": tracked_target.height,
            })

        if confirmed:
            target_text = (
                f"TARGET: {detected_position} "
                f"{confidence:.2f} "
                f"area={area_ratio:.3f}"
            )
        else:
            target_text = (
                "TARGET: VERIFYING "
                f"{target_confirmation.count}/"
                f"{target_confirmation.required_frames}"
            )

        if log_events:
            print(
                f"BALL {'CONFIRMED' if confirmed else 'VERIFYING'} "
                f"confidence={confidence:.3f} "
                f"x={center_x:.1f} "
                f"y={center_y:.1f} "
                f"area={area_ratio:.4f} "
                f"color={metrics.color_ratio:.3f} "
                f"round={metrics.circularity:.3f} "
                f"object_area={metrics.object_area_ratio:.3f} "
                f"source={tracked_target.source} "
                f"position={detected_position}"
            )

    else:
        if target_tracker.current_target() is None:
            target_confirmation.reset()
        position = "LOST"
        area_ratio = 0.0
        target_x = None

        if too_close:
            observation["vision_status"] = "TOO_CLOSE"
            target_text = (
                "TARGET: TOO CLOSE "
                f"color={frame_color_coverage:.2f}"
            )
            area_ratio = 1.0
            if log_events:
                print(
                    "BALL TOO CLOSE "
                    f"frame_color={frame_color_coverage:.3f}"
                )
        elif rejected:
            target_text = "TARGET: REJECTED"
            rejected_box, rejected_metrics = rejected[0]
            reasons = ",".join(rejected_metrics.reasons)
            observation["vision_status"] = "REJECTED:" + reasons
            if log_events:
                print(
                    "BALL REJECTED "
                    f"confidence={float(rejected_box['value']):.3f} "
                    f"color={rejected_metrics.color_ratio:.3f} "
                    f"round={rejected_metrics.circularity:.3f} "
                    f"extent={rejected_metrics.extent:.3f} "
                    f"solidity={rejected_metrics.solidity:.3f} "
                    f"aspect={rejected_metrics.aspect:.3f} "
                    f"object_area={rejected_metrics.object_area_ratio:.3f} "
                    f"reasons={reasons}"
                )
        else:
            target_text = "TARGET: LOST"
            observation["bottom_exit_loss"] = not visible_targets and not accepted
            observation["vision_status"] = (
                "EMPTY" if observation["bottom_exit_loss"] else "UNCONFIRMED"
            )
            if log_events:
                print("BALL LOST")

    draw_target_center_markers(
        display, visible_targets, tracked_target,
        model_width, model_height, scale_x, scale_y,
        primary_confirmed=observation["detected"],
    )

    cv2.putText(
        display,
        target_text,
        (15, 30),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        (0, 255, 255),
        2
    )

    cv2.putText(
        display,
        f"Balls: {len(visible_targets)} Rejected: {len(rejected)}",
        (15, 60),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        (0, 255, 255),
        2
    )

    return display, position, area_ratio, target_x, observation


def process_classification(
    result,
    labels,
    preview_rgb
):
    classification = result["result"].get(
        "classification",
        {}
    )

    preview_bgr = cv2.cvtColor(
        preview_rgb,
        cv2.COLOR_RGB2BGR
    )

    display, _ = resize_for_display(
        preview_bgr
    )

    best_label = None
    best_score = 0.0

    for label in labels:
        score = float(
            classification.get(label, 0.0)
        )

        if score > best_score:
            best_score = score
            best_label = label

    if (
        best_label is not None
        and best_score >= CONFIDENCE_THRESHOLD
    ):
        text = f"{best_label}: {best_score:.2f}"
        color = (0, 255, 0)

        print(
            f"{best_label} "
            f"confidence={best_score:.3f}"
        )

    else:
        text = f"NO CONFIDENT RESULT: {best_score:.2f}"
        color = (0, 0, 255)

        print("NO CONFIDENT RESULT")

    cv2.putText(
        display,
        text,
        (15, 30),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        color,
        2
    )

    return display


def print_model_information(model_info):
    project = model_info.get("project", {})
    parameters = model_info.get(
        "model_parameters",
        {}
    )

    owner = project.get("owner", "unknown")
    project_name = project.get(
        "name",
        "unknown"
    )

    labels = parameters.get("labels", [])

    image_width = parameters.get(
        "image_input_width",
        "unknown"
    )

    image_height = parameters.get(
        "image_input_height",
        "unknown"
    )

    print(f"Project owner: {owner}")
    print(f"Project name: {project_name}")
    print(f"Labels: {labels}")
    print(
        f"Model input: "
        f"{image_width}x{image_height}"
    )


def main():
    if Picamera2 is None:
        raise RuntimeError(
            "Picamera2 is required to run the Raspberry Pi camera loop"
        )
    project_folder = Path(
        __file__
    ).resolve().parent
    runner_context = build_runner_context(project_folder)

    camera = Picamera2()
    motor_controller = None
    camera_started = False

    camera_config = (
        camera.create_video_configuration(
            main={
                "size": (
                    CAMERA_WIDTH,
                    CAMERA_HEIGHT
                ),
                "format": "RGB888"
            },
            controls={
                "FrameRate": CAMERA_FPS,
                "Sharpness": CAMERA_SHARPNESS
            }
        )
    )

    try:
        camera.configure(camera_config)
        camera.start()
        camera_started = True

        time.sleep(2)

        motor_controller = MotorController.from_environment()
        target_confirmation = TargetConfirmation(
            FILTER_CONFIG.confirm_frames,
            FILTER_CONFIG.confirm_max_jump,
        )
        target_tracker = MultiBallTracker()

        print(
            f"Camera capture: {CAMERA_WIDTH}x{CAMERA_HEIGHT} "
            f"at {CAMERA_FPS} FPS"
        )
        print(f"Camera sharpness: {CAMERA_SHARPNESS:.1f}")
        print(f"Digital zoom: {DIGITAL_ZOOM:.2f}x")
        print(
            "Candidate filter: "
            f"confidence>={FILTER_CONFIG.confidence_threshold:.2f}, "
            f"color>={FILTER_CONFIG.color_ratio_min:.2f}, "
            f"circularity>={FILTER_CONFIG.circularity_min:.2f}, "
            f"trained_round>={FILTER_CONFIG.trained_circularity_min:.2f} "
            f"at confidence>={FILTER_CONFIG.trained_confidence_relax:.2f}, "
            f"area>={FILTER_CONFIG.object_area_min:.4f}, "
            f"close_color>={FILTER_CONFIG.close_color_coverage:.2f}, "
            f"crop={FILTER_CONFIG.crop_expansion:.1f}x, "
            f"confirm={FILTER_CONFIG.confirm_frames} frames"
        )

        previous_time = time.perf_counter()
        filter_snapshot_saved = False

        with runner_context as runner:
            model_info = runner.init()

            print_model_information(
                model_info
            )

            labels = model_info[
                "model_parameters"
            ].get("labels", [])

            model_width = int(
                model_info["model_parameters"][
                    "image_input_width"
                ]
            )
            model_height = int(
                model_info["model_parameters"][
                    "image_input_height"
                ]
            )

            while True:
                frame_bgr = camera.capture_array()

                frame_rgb = cv2.cvtColor(
                    frame_bgr,
                    cv2.COLOR_BGR2RGB
                )

                inference_rgb = apply_center_zoom(
                    frame_rgb,
                    DIGITAL_ZOOM
                )

                features, _ = (
                    runner.get_features_from_image(
                        inference_rgb
                    )
                )

                preview_rgb = center_crop_square(
                    inference_rgb
                )

                result = runner.classify(
                    features
                )

                result_data = result.get(
                    "result",
                    {}
                )

                if "bounding_boxes" in result_data:
                    display, position, area_ratio, target_x, observation = (
                        process_bounding_boxes(
                            result,
                            preview_rgb,
                            model_width,
                            model_height,
                            target_confirmation,
                            target_tracker,
                        )
                    )

                    motion = motor_controller.update(
                        position,
                        area_ratio,
                        target_x,
                        min(1.0, observation["ball_y"] + observation["ball_height"] / 2)
                        if observation["detected"]
                        else None,
                        observation["bottom_exit_loss"],
                        observation_time=time.monotonic(),
                        candidate_visible=observation["candidate_visible"],
                    )

                elif "classification" in result_data:
                    target_confirmation.reset()
                    display = process_classification(
                        result,
                        labels,
                        preview_rgb
                    )
                    motion = motor_controller.update("LOST")

                else:
                    target_confirmation.reset()
                    display_bgr = cv2.cvtColor(
                        preview_rgb,
                        cv2.COLOR_RGB2BGR
                    )

                    display, _ = resize_for_display(
                        display_bgr
                    )

                    cv2.putText(
                        display,
                        "UNSUPPORTED MODEL OUTPUT",
                        (15, 30),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.6,
                        (0, 0, 255),
                        2
                    )

                    print(
                        f"Unsupported result keys: "
                        f"{list(result_data.keys())}"
                    )
                    motion = motor_controller.update("LOST")

                draw_vehicle_status(
                    display,
                    motion,
                    motor_controller,
                )

                current_time = time.perf_counter()
                elapsed = (
                    current_time - previous_time
                )
                previous_time = current_time

                fps = (
                    1.0 / elapsed
                    if elapsed > 0
                    else 0.0
                )

                timing = result.get(
                    "timing",
                    {}
                )

                dsp_time = timing.get("dsp", 0)
                inference_time = timing.get(
                    "classification",
                    0
                )

                height = display.shape[0]

                cv2.putText(
                    display,
                    f"FPS: {fps:.1f}",
                    (15, height - 40),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (255, 255, 0),
                    2
                )

                cv2.putText(
                    display,
                    (
                        f"DSP: {dsp_time} ms "
                        f"NN: {inference_time} ms"
                    ),
                    (15, height - 15),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.55,
                    (255, 255, 0),
                    2
                )

                if FILTER_SNAPSHOT_PATH and not filter_snapshot_saved:
                    if not cv2.imwrite(FILTER_SNAPSHOT_PATH, display):
                        raise OSError(
                            "Could not write filter snapshot: "
                            f"{FILTER_SNAPSHOT_PATH}"
                        )
                    filter_snapshot_saved = True
                    print(f"Filter snapshot: {FILTER_SNAPSHOT_PATH}")

                if SHOW_WINDOW:
                    cv2.imshow(
                        "Tennis Detection",
                        display
                    )

                    key = cv2.waitKey(1) & 0xFF

                    if key == ord("q"):
                        break

    except KeyboardInterrupt:
        print("Stopped by user")

    finally:
        if motor_controller is not None:
            motor_controller.close()
        if camera_started:
            camera.stop()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
