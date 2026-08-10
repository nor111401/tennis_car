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
    train: list[Path] = []
    validation: list[Path] = []
    session_folders = sorted(path for path in root.iterdir() if path.is_dir())
    for session in session_folders:
        files = sorted(session.glob("*.jpg"))
        if not files:
            continue
        validation_count = max(1, int(math.ceil(len(files) * validation_fraction)))
        train.extend(files[:-validation_count])
        validation.extend(files[-validation_count:])
    return train, validation


def color_jitter(patch: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    pixels = patch.astype(np.float32)
    contrast = rng.uniform(0.86, 1.14)
    brightness = rng.uniform(-14.0, 14.0)
    channel_gain = rng.uniform(0.94, 1.06, size=(1, 1, 3))
    pixels = (pixels - 127.5) * contrast + 127.5 + brightness
    pixels *= channel_gain
    noise = rng.normal(0.0, rng.uniform(0.0, 2.5), size=pixels.shape)
    return np.clip(pixels + noise, 0.0, 255.0).astype(np.uint8)


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
        if index:
            patch = color_jitter(patch, rng)
        patches.append(patch)
    return patches


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
            features.append(extract_features(expanded_crop(image_rgb, box)))
            labels.append(0)
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
            features.append(extract_features(expanded_crop(image_rgb, box)))
            labels.append(0)
            counts["vivid_negatives"] += 1
            vivid_count += 1
            if vivid_count >= (2 if augment else 1):
                break

        random_count = 3 if augment else 2
        for box in random_negative_boxes(image_rgb, rng, random_count, target):
            features.append(extract_features(expanded_crop(image_rgb, box, 1.0)))
            labels.append(0)
            counts["random_negatives"] += 1

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
    train_metrics = metric_summary(y_train, train_probabilities)

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
        "feature_count": int(x_train.shape[1]),
        "train_sample_count": int(len(y_train)),
        "validation_sample_count": int(len(y_validation)),
        "train_class_count": {
            "negative": int(np.count_nonzero(y_train == 0)),
            "positive": int(np.count_nonzero(y_train == 1)),
        },
        "validation_class_count": {
            "negative": int(np.count_nonzero(y_validation == 0)),
            "positive": int(np.count_nonzero(y_validation == 1)),
        },
        "train_frame_counts": train_counts,
        "validation_frame_counts": validation_counts,
        "train_metrics": train_metrics,
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
