"""Train and export the lightweight tennis-ball candidate verifier."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import zlib

import numpy as np
from PIL import Image
from scipy import ndimage
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import confusion_matrix, precision_recall_fscore_support, roc_auc_score
from sklearn.preprocessing import StandardScaler

from tennis_ball_verifier import (
    CROP_EXPANSION,
    FEATURE_VERSION,
    expanded_crop,
    extract_features,
    rgb_to_hsv,
)


MODEL_THRESHOLD = 0.70
LIGHTING_CONDITIONS = (
    "original",
    "low_light",
    "overexposed",
    "warm_light",
    "cool_light",
    "uneven_light",
)


def load_rgb(path: Path) -> np.ndarray:
    with Image.open(path) as image:
        return np.asarray(image.convert("RGB"))


def overlap_fraction(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> float:
    ax, ay, aw, ah = first
    bx, by, bw, bh = second
    left = max(ax, bx)
    top = max(ay, by)
    right = min(ax + aw, bx + bw)
    bottom = min(ay + ah, by + bh)
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    return intersection / max(min(aw * ah, bw * bh), 1.0)


def component_boxes(mask: np.ndarray, minimum_area: int) -> list[tuple[float, float, float, float]]:
    labels, count = ndimage.label(mask)
    objects = ndimage.find_objects(labels)
    boxes: list[tuple[float, float, float, float, int]] = []
    for label_index, slices in enumerate(objects, start=1):
        if slices is None:
            continue
        area = int(np.count_nonzero(labels[slices] == label_index))
        if area < minimum_area:
            continue
        y_slice, x_slice = slices
        boxes.append(
            (
                float(x_slice.start),
                float(y_slice.start),
                float(x_slice.stop - x_slice.start),
                float(y_slice.stop - y_slice.start),
                area,
            )
        )
    boxes.sort(key=lambda item: item[4], reverse=True)
    return [item[:4] for item in boxes]


def proposal_boxes(image_rgb: np.ndarray) -> list[tuple[float, float, float, float]]:
    hue, saturation, value = rgb_to_hsv(image_rgb)
    mask = (
        (hue >= 18.0 / 180.0)
        & (hue <= 60.0 / 180.0)
        & (saturation >= 70.0 / 255.0)
        & (value >= 45.0 / 255.0)
    )
    structure = np.ones((5, 5), dtype=bool)
    mask = ndimage.binary_opening(mask, structure=structure)
    mask = ndimage.binary_closing(mask, structure=structure)
    minimum_area = max(20, int(round(mask.size * 0.0005)))
    return component_boxes(mask, minimum_area)


def vivid_boxes(image_rgb: np.ndarray) -> list[tuple[float, float, float, float]]:
    _, saturation, value = rgb_to_hsv(image_rgb)
    mask = (saturation >= 0.28) & (value >= 0.18)
    structure = np.ones((3, 3), dtype=bool)
    mask = ndimage.binary_opening(mask, structure=structure)
    mask = ndimage.binary_closing(mask, structure=structure)
    return component_boxes(mask, max(30, int(round(mask.size * 0.00025))))


def split_session_files(root: Path, validation_fraction: float) -> tuple[list[Path], list[Path]]:
    """Hold out complete capture sessions instead of adjacent video frames."""
    train: list[Path] = []
    validation: list[Path] = []
    session_folders = sorted(path for path in root.iterdir() if path.is_dir())
    session_folders = [
        session for session in session_folders if any(session.glob("*.jpg"))
    ]
    if len(session_folders) < 2:
        raise ValueError(f"Need at least two capture sessions in {root}")
    if not 0.0 < validation_fraction < 1.0:
        raise ValueError("validation_fraction must be between 0 and 1")
    validation_count = max(
        1,
        min(
            len(session_folders) - 1,
            int(math.ceil(len(session_folders) * validation_fraction)),
        ),
    )
    for session in session_folders[:-validation_count]:
        train.extend(sorted(session.glob("*.jpg")))
    for session in session_folders[-validation_count:]:
        validation.extend(sorted(session.glob("*.jpg")))
    return train, validation


def simulate_lighting(
    patch: np.ndarray,
    condition: str,
    rng: np.random.Generator,
) -> np.ndarray:
    """Apply a deterministic family of camera-like illumination changes."""
    if condition not in LIGHTING_CONDITIONS:
        raise ValueError(f"Unknown lighting condition: {condition}")
    pixels = patch.astype(np.float32) / 255.0

    if condition == "low_light":
        pixels = np.power(pixels, rng.uniform(1.25, 1.65)) * rng.uniform(0.42, 0.65)
    elif condition == "overexposed":
        pixels = np.power(pixels, rng.uniform(0.65, 0.85)) * rng.uniform(1.18, 1.48)
    elif condition == "warm_light":
        pixels *= np.asarray((1.18, 1.02, 0.78), dtype=np.float32)
        pixels = (pixels - 0.5) * rng.uniform(0.90, 1.08) + 0.5
    elif condition == "cool_light":
        pixels *= np.asarray((0.78, 1.00, 1.20), dtype=np.float32)
        pixels = (pixels - 0.5) * rng.uniform(0.90, 1.08) + 0.5
    elif condition == "uneven_light":
        height, width = pixels.shape[:2]
        axis = np.linspace(0.38, 1.08, width if rng.random() < 0.5 else height)
        if rng.random() < 0.5:
            axis = axis[::-1]
        shade = axis.reshape(1, width, 1) if len(axis) == width else axis.reshape(height, 1, 1)
        pixels *= shade.astype(np.float32)
        yy, xx = np.mgrid[0:height, 0:width]
        center_x = rng.uniform(0.15, 0.85) * width
        center_y = rng.uniform(0.15, 0.85) * height
        radius = max(height, width) * rng.uniform(0.22, 0.42)
        hotspot = np.exp(-((xx - center_x) ** 2 + (yy - center_y) ** 2) / (2.0 * radius ** 2))
        pixels = pixels * (1.0 - 0.38 * hotspot[..., None]) + 0.38 * hotspot[..., None]

    if condition != "original":
        contrast = rng.uniform(0.90, 1.10)
        pixels = (pixels - 0.5) * contrast + 0.5
        noise_sigma = rng.uniform(0.0, 0.018 if condition == "low_light" else 0.010)
        pixels += rng.normal(0.0, noise_sigma, size=pixels.shape)
    return np.clip(pixels * 255.0, 0.0, 255.0).astype(np.uint8)


def jittered_positive_patches(
    image_rgb: np.ndarray,
    box: tuple[float, float, float, float],
    rng: np.random.Generator,
    augment: bool,
) -> list[np.ndarray]:
    if not augment:
        return [expanded_crop(image_rgb, box, CROP_EXPANSION)]

    x, y, width, height = box
    settings = (
        (1.22, 0.00, 0.00),
        (1.35, 0.00, 0.00),
        (1.48, 0.00, 0.00),
        (1.35, -0.05, 0.02),
        (1.35, 0.05, -0.02),
        (1.42, 0.02, 0.05),
    )
    patches: list[np.ndarray] = []
    for index, (expansion, dx, dy) in enumerate(settings):
        shifted = (x + dx * width, y + dy * height, width, height)
        patch = expanded_crop(image_rgb, shifted, expansion)
        if index % 2:
            patch = np.ascontiguousarray(patch[:, ::-1])
        patch = simulate_lighting(patch, LIGHTING_CONDITIONS[index], rng)
        patches.append(patch)
    return patches


def append_negative_patch(
    features: list[np.ndarray],
    labels: list[int],
    patch: np.ndarray,
    rng: np.random.Generator,
    augment: bool,
    augmentation_index: int,
) -> int:
    features.append(extract_features(patch))
    labels.append(0)
    if not augment:
        return 0
    condition = LIGHTING_CONDITIONS[1 + augmentation_index % (len(LIGHTING_CONDITIONS) - 1)]
    features.append(extract_features(simulate_lighting(patch, condition, rng)))
    labels.append(0)
    return 1


def random_negative_boxes(
    image_rgb: np.ndarray,
    rng: np.random.Generator,
    count: int,
    excluded: tuple[float, float, float, float] | None,
) -> list[tuple[float, float, float, float]]:
    height, width = image_rgb.shape[:2]
    _, saturation, value = rgb_to_hsv(image_rgb)
    interesting = np.argwhere((saturation >= 0.20) & (value >= 0.15))
    boxes: list[tuple[float, float, float, float]] = []
    attempts = 0
    while len(boxes) < count and attempts < count * 30:
        attempts += 1
        if len(interesting) and rng.random() < 0.75:
            center_y, center_x = interesting[rng.integers(0, len(interesting))]
        else:
            center_y = rng.integers(0, height)
            center_x = rng.integers(0, width)
        side = float(rng.choice((28, 40, 56, 76, 104, 136)))
        box = (float(center_x) - side / 2, float(center_y) - side / 2, side, side)
        if excluded is not None and overlap_fraction(box, excluded) > 0.02:
            continue
        boxes.append(box)
    return boxes


def path_rng(path: Path) -> np.random.Generator:
    seed = zlib.crc32(str(path).encode("utf-8"))
    return np.random.default_rng(seed)


def build_samples(
    files: list[Path],
    contains_ball: bool,
    augment: bool,
) -> tuple[list[np.ndarray], list[int], dict[str, int]]:
    features: list[np.ndarray] = []
    labels: list[int] = []
    counts = {
        "frames": 0,
        "positive_patches": 0,
        "proposal_negatives": 0,
        "vivid_negatives": 0,
        "random_negatives": 0,
        "lighting_augmented_negatives": 0,
        "missing_positive": 0,
    }

    for path in files:
        image_rgb = load_rgb(path)
        rng = path_rng(path)
        proposals = proposal_boxes(image_rgb)
        counts["frames"] += 1
        target = proposals[0] if contains_ball and proposals else None

        if contains_ball:
            if target is None:
                counts["missing_positive"] += 1
                continue
            for patch in jittered_positive_patches(image_rgb, target, rng, augment):
                features.append(extract_features(patch))
                labels.append(1)
                counts["positive_patches"] += 1

        negative_limit = 4 if augment else 2
        proposal_negative_count = 0
        for box in proposals:
            if target is not None and overlap_fraction(box, target) > 0.20:
                continue
            counts["lighting_augmented_negatives"] += append_negative_patch(
                features,
                labels,
                expanded_crop(image_rgb, box),
                rng,
                augment,
                proposal_negative_count,
            )
            counts["proposal_negatives"] += 1
            proposal_negative_count += 1
            if proposal_negative_count >= negative_limit:
                break

        vivid_count = 0
        for box in vivid_boxes(image_rgb):
            if target is not None and overlap_fraction(box, target) > 0.02:
                continue
            if any(overlap_fraction(box, proposal) > 0.70 for proposal in proposals):
                continue
            counts["lighting_augmented_negatives"] += append_negative_patch(
                features,
                labels,
                expanded_crop(image_rgb, box),
                rng,
                augment,
                vivid_count + 1,
            )
            counts["vivid_negatives"] += 1
            vivid_count += 1
            if vivid_count >= (2 if augment else 1):
                break

        random_count = 3 if augment else 2
        for random_index, box in enumerate(
            random_negative_boxes(image_rgb, rng, random_count, target)
        ):
            counts["lighting_augmented_negatives"] += append_negative_patch(
                features,
                labels,
                expanded_crop(image_rgb, box, 1.0),
                rng,
                augment,
                random_index + 2,
            )
            counts["random_negatives"] += 1

    return features, labels, counts


def build_annotated_positive_samples(
    root: Path,
    augment: bool,
) -> tuple[list[np.ndarray], list[int], dict[str, int]]:
    """Build one positive training target for every annotated ball box.

    Full-frame positive folders can only choose the largest color proposal.
    Explicit annotations let a touching-ball scene contribute both physical
    balls independently without teaching the verifier that their merged blob
    is one object.
    """
    features: list[np.ndarray] = []
    labels: list[int] = []
    counts = {
        "frames": 0,
        "objects": 0,
        "positive_patches": 0,
    }
    if not root.exists():
        return features, labels, counts

    for annotation_path in sorted(root.rglob("*.json")):
        payload = json.loads(annotation_path.read_text(encoding="utf-8"))
        image_name = str(payload.get("image", "")).strip()
        if not image_name:
            raise ValueError(f"Missing image in {annotation_path}")
        image_path = annotation_path.parent / image_name
        image_rgb = load_rgb(image_path)
        image_height, image_width = image_rgb.shape[:2]
        if int(payload.get("width", image_width)) != image_width:
            raise ValueError(f"Width mismatch in {annotation_path}")
        if int(payload.get("height", image_height)) != image_height:
            raise ValueError(f"Height mismatch in {annotation_path}")

        objects = payload.get("objects", [])
        if not isinstance(objects, list):
            raise ValueError(f"Objects must be a list in {annotation_path}")
        rng = path_rng(annotation_path)
        frame_objects = 0
        for item in objects:
            if not isinstance(item, dict) or item.get("label") != "tennis_ball":
                continue
            bbox = item.get("bbox")
            if not isinstance(bbox, dict):
                raise ValueError(f"Missing bbox in {annotation_path}")
            box = tuple(float(bbox[name]) for name in (
                "x", "y", "width", "height"
            ))
            if box[2] <= 0 or box[3] <= 0:
                raise ValueError(f"Invalid bbox in {annotation_path}")
            for patch in jittered_positive_patches(
                image_rgb,
                box,
                rng,
                augment,
            ):
                features.append(extract_features(patch))
                labels.append(1)
                counts["positive_patches"] += 1
            frame_objects += 1
        if frame_objects:
            counts["frames"] += 1
            counts["objects"] += frame_objects

    return features, labels, counts


def metric_summary(labels: np.ndarray, probabilities: np.ndarray) -> dict[str, object]:
    predictions = probabilities >= MODEL_THRESHOLD
    matrix = confusion_matrix(labels, predictions, labels=[0, 1])
    true_negative, false_positive, false_negative, true_positive = matrix.ravel()
    precision, recall, f1, _ = precision_recall_fscore_support(
        labels,
        predictions,
        average="binary",
        zero_division=0,
    )
    return {
        "threshold": MODEL_THRESHOLD,
        "confusion_matrix": matrix.tolist(),
        "accuracy": float((predictions == labels).mean()),
        "precision": float(precision),
        "recall": float(recall),
        "f1": float(f1),
        "false_positive_rate": float(false_positive / max(false_positive + true_negative, 1)),
        "roc_auc": float(roc_auc_score(labels, probabilities)),
        "positive_probability": {
            "minimum": float(probabilities[labels == 1].min()),
            "median": float(np.median(probabilities[labels == 1])),
            "maximum": float(probabilities[labels == 1].max()),
        },
        "negative_probability": {
            "minimum": float(probabilities[labels == 0].min()),
            "median": float(np.median(probabilities[labels == 0])),
            "maximum": float(probabilities[labels == 0].max()),
        },
    }


def session_names(files: list[Path]) -> list[str]:
    return sorted({path.parent.name for path in files})


def session_descriptors(files: list[Path]) -> list[dict[str, str]]:
    descriptors: list[dict[str, str]] = []
    for session_name in session_names(files):
        session = next(path.parent for path in files if path.parent.name == session_name)
        condition = "unlabeled"
        metadata_path = session / "session.json"
        if metadata_path.exists():
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            condition = str(metadata.get("lighting_condition", condition))
        descriptors.append({"session": session_name, "lighting_condition": condition})
    return descriptors


def fit_classifier(
    features: np.ndarray,
    labels: np.ndarray,
    regularization: float,
) -> tuple[StandardScaler, LogisticRegression, np.ndarray]:
    scaler = StandardScaler()
    scaled = scaler.fit_transform(features)
    classifier = LogisticRegression(
        C=regularization,
        class_weight="balanced",
        max_iter=1000,
        solver="liblinear",
        random_state=20260808,
    )
    classifier.fit(scaled, labels)
    return scaler, classifier, scaled


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=Path("training_data"))
    parser.add_argument("--output", type=Path, default=Path("tennis_ball_verifier.npz"))
    parser.add_argument("--report", type=Path, default=Path("tennis_ball_verifier_report.json"))
    parser.add_argument("--validation-fraction", type=float, default=0.25)
    args = parser.parse_args()

    positive_train, positive_validation = split_session_files(
        args.data / "positive", args.validation_fraction
    )
    negative_train, negative_validation = split_session_files(
        args.data / "negative", args.validation_fraction
    )
    print(
        "Frame split: "
        f"positive train={len(positive_train)} validation={len(positive_validation)}, "
        f"negative train={len(negative_train)} validation={len(negative_validation)}"
    )

    train_features: list[np.ndarray] = []
    train_labels: list[int] = []
    train_counts: dict[str, dict[str, int]] = {}
    for name, files, contains_ball in (
        ("positive", positive_train, True),
        ("negative", negative_train, False),
    ):
        features, labels, counts = build_samples(files, contains_ball, augment=True)
        train_features.extend(features)
        train_labels.extend(labels)
        train_counts[name] = counts
        print(f"Training {name}: {counts}")

    annotated_features, annotated_labels, annotated_counts = (
        build_annotated_positive_samples(
            args.data / "annotated",
            augment=True,
        )
    )
    train_features.extend(annotated_features)
    train_labels.extend(annotated_labels)
    train_counts["annotated_positive"] = annotated_counts
    print(f"Training annotated_positive: {annotated_counts}")

    validation_features: list[np.ndarray] = []
    validation_labels: list[int] = []
    validation_counts: dict[str, dict[str, int]] = {}
    for name, files, contains_ball in (
        ("positive", positive_validation, True),
        ("negative", negative_validation, False),
    ):
        features, labels, counts = build_samples(files, contains_ball, augment=False)
        validation_features.extend(features)
        validation_labels.extend(labels)
        validation_counts[name] = counts
        print(f"Validation {name}: {counts}")

    x_train = np.asarray(train_features, dtype=np.float32)
    y_train = np.asarray(train_labels, dtype=np.int8)
    x_validation = np.asarray(validation_features, dtype=np.float32)
    y_validation = np.asarray(validation_labels, dtype=np.int8)
    if len(np.unique(y_train)) != 2 or len(np.unique(y_validation)) != 2:
        raise RuntimeError("Training and validation sets must both contain two classes")

    scaler = StandardScaler()
    scaled_train = scaler.fit_transform(x_train)
    scaled_validation = scaler.transform(x_validation)

    trials: list[dict[str, object]] = []
    best: tuple[float, LogisticRegression, np.ndarray] | None = None
    for regularization in (0.003, 0.01, 0.03, 0.1):
        classifier = LogisticRegression(
            C=regularization,
            class_weight="balanced",
            max_iter=1000,
            solver="liblinear",
            random_state=20260808,
        )
        classifier.fit(scaled_train, y_train)
        probabilities = classifier.predict_proba(scaled_validation)[:, 1]
        metrics = metric_summary(y_validation, probabilities)
        selection_score = float(metrics["f1"]) - 1.5 * float(metrics["false_positive_rate"])
        trials.append({"C": regularization, "selection_score": selection_score, **metrics})
        print(
            f"C={regularization:.3f} val_f1={float(metrics['f1']):.4f} "
            f"recall={float(metrics['recall']):.4f} "
            f"fpr={float(metrics['false_positive_rate']):.4f} "
            f"auc={float(metrics['roc_auc']):.4f}"
        )
        if best is None or selection_score > best[0]:
            best = (selection_score, classifier, probabilities)

    assert best is not None
    _, classifier, validation_probabilities = best
    selected_c = float(classifier.C)
    validation_metrics = metric_summary(y_validation, validation_probabilities)
    train_probabilities = classifier.predict_proba(scaled_train)[:, 1]
    selection_train_metrics = metric_summary(y_train, train_probabilities)

    # The held-out sessions remain untouched while choosing C and reporting
    # validation metrics. Once selection is complete, include those reviewed
    # frames in the deployed model so valuable dark-light sessions are not
    # permanently discarded from training.
    refit_features: list[np.ndarray] = []
    refit_labels: list[int] = []
    refit_counts: dict[str, dict[str, int]] = {}
    for name, files, contains_ball in (
        ("positive", positive_validation, True),
        ("negative", negative_validation, False),
    ):
        features, labels, counts = build_samples(files, contains_ball, augment=True)
        refit_features.extend(features)
        refit_labels.extend(labels)
        refit_counts[name] = counts
        print(f"Deployment refit {name}: {counts}")

    x_deployment = np.concatenate(
        (x_train, np.asarray(refit_features, dtype=np.float32)),
        axis=0,
    )
    y_deployment = np.concatenate(
        (y_train, np.asarray(refit_labels, dtype=np.int8)),
        axis=0,
    )
    scaler, classifier, scaled_deployment = fit_classifier(
        x_deployment,
        y_deployment,
        selected_c,
    )
    deployment_probabilities = classifier.predict_proba(scaled_deployment)[:, 1]
    train_metrics = metric_summary(y_deployment, deployment_probabilities)

    scale = scaler.scale_.astype(np.float32)
    scale[scale < 1e-7] = 1.0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        args.output,
        feature_version=np.asarray(FEATURE_VERSION, dtype=np.int32),
        mean=scaler.mean_.astype(np.float32),
        scale=scale,
        weights=classifier.coef_[0].astype(np.float32),
        intercept=np.asarray(classifier.intercept_[0], dtype=np.float32),
        threshold=np.asarray(MODEL_THRESHOLD, dtype=np.float32),
    )

    report = {
        "model": str(args.output),
        "selected_C": selected_c,
        "feature_count": int(x_deployment.shape[1]),
        "train_sample_count": int(len(y_deployment)),
        "selection_train_sample_count": int(len(y_train)),
        "validation_sample_count": int(len(y_validation)),
        "train_class_count": {
            "negative": int(np.count_nonzero(y_deployment == 0)),
            "positive": int(np.count_nonzero(y_deployment == 1)),
        },
        "validation_class_count": {
            "negative": int(np.count_nonzero(y_validation == 0)),
            "positive": int(np.count_nonzero(y_validation == 1)),
        },
        "split": {
            "strategy": "hold_out_complete_capture_sessions_then_refit_all",
            "validation_fraction": args.validation_fraction,
            "positive_train_sessions": session_descriptors(positive_train),
            "positive_validation_sessions": session_descriptors(positive_validation),
            "negative_train_sessions": session_descriptors(negative_train),
            "negative_validation_sessions": session_descriptors(negative_validation),
        },
        "lighting_augmentation_conditions": list(LIGHTING_CONDITIONS),
        "selection_train_frame_counts": train_counts,
        "deployment_refit_frame_counts": refit_counts,
        "validation_frame_counts": validation_counts,
        "train_metrics": train_metrics,
        "selection_train_metrics": selection_train_metrics,
        "validation_metrics": validation_metrics,
        "trials": trials,
    }
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Selected C={selected_c}")
    print(json.dumps(validation_metrics, indent=2))
    print(f"MODEL={args.output.resolve()}")
    print(f"REPORT={args.report.resolve()}")


if __name__ == "__main__":
    main()
