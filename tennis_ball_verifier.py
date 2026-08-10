"""Lightweight trained verifier for color-proposed tennis-ball crops.

The feature extractor intentionally depends only on NumPy so the exported
linear model can run on a Raspberry Pi without scikit-learn.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np


FEATURE_VERSION = 1
FEATURE_IMAGE_SIZE = 32
CROP_EXPANSION = 1.35


def resize_bilinear(image: np.ndarray, size: int = FEATURE_IMAGE_SIZE) -> np.ndarray:
    """Resize an RGB array with deterministic NumPy bilinear interpolation."""
    if image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("Expected an HxWx3 RGB image")
    height, width = image.shape[:2]
    if height < 1 or width < 1:
        raise ValueError("Cannot resize an empty image")

    source = image.astype(np.float32, copy=False)
    ys = np.linspace(0.0, height - 1.0, size, dtype=np.float32)
    xs = np.linspace(0.0, width - 1.0, size, dtype=np.float32)
    y0 = np.floor(ys).astype(np.int32)
    x0 = np.floor(xs).astype(np.int32)
    y1 = np.minimum(y0 + 1, height - 1)
    x1 = np.minimum(x0 + 1, width - 1)
    wy = (ys - y0).reshape(size, 1, 1)
    wx = (xs - x0).reshape(1, size, 1)

    top = source[y0[:, None], x0[None, :]] * (1.0 - wx)
    top += source[y0[:, None], x1[None, :]] * wx
    bottom = source[y1[:, None], x0[None, :]] * (1.0 - wx)
    bottom += source[y1[:, None], x1[None, :]] * wx
    return top * (1.0 - wy) + bottom * wy


def rgb_to_hsv(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return hue, saturation and value in the [0, 1] range."""
    pixels = rgb.astype(np.float32, copy=False) / 255.0
    red, green, blue = np.moveaxis(pixels, -1, 0)
    maximum = pixels.max(axis=-1)
    minimum = pixels.min(axis=-1)
    difference = maximum - minimum

    hue = np.zeros_like(maximum)
    nonzero = difference > 1e-7
    red_max = nonzero & (maximum == red)
    green_max = nonzero & (maximum == green)
    blue_max = nonzero & (maximum == blue)
    hue[red_max] = ((green[red_max] - blue[red_max]) / difference[red_max]) % 6.0
    hue[green_max] = (blue[green_max] - red[green_max]) / difference[green_max] + 2.0
    hue[blue_max] = (red[blue_max] - green[blue_max]) / difference[blue_max] + 4.0
    hue /= 6.0

    saturation = np.zeros_like(maximum)
    positive = maximum > 1e-7
    saturation[positive] = difference[positive] / maximum[positive]
    return hue, saturation, maximum


def expanded_crop(
    image_rgb: np.ndarray,
    box: tuple[float, float, float, float],
    expansion: float = CROP_EXPANSION,
) -> np.ndarray:
    """Crop a padded x/y/width/height box while staying within the image."""
    x, y, width, height = box
    if width <= 0 or height <= 0:
        raise ValueError("Candidate box must have positive dimensions")
    image_height, image_width = image_rgb.shape[:2]
    side = max(width, height) * expansion
    center_x = x + width / 2.0
    center_y = y + height / 2.0
    left = max(0, int(np.floor(center_x - side / 2.0)))
    top = max(0, int(np.floor(center_y - side / 2.0)))
    right = min(image_width, int(np.ceil(center_x + side / 2.0)))
    bottom = min(image_height, int(np.ceil(center_y + side / 2.0)))
    return image_rgb[top:bottom, left:right]


def _hog(gray: np.ndarray, cells: int = 8, bins: int = 9) -> np.ndarray:
    gx = np.zeros_like(gray, dtype=np.float32)
    gy = np.zeros_like(gray, dtype=np.float32)
    gx[:, 1:-1] = gray[:, 2:] - gray[:, :-2]
    gx[:, 0] = gray[:, 1] - gray[:, 0]
    gx[:, -1] = gray[:, -1] - gray[:, -2]
    gy[1:-1, :] = gray[2:, :] - gray[:-2, :]
    gy[0, :] = gray[1, :] - gray[0, :]
    gy[-1, :] = gray[-1, :] - gray[-2, :]

    magnitude = np.hypot(gx, gy)
    orientation = np.mod(np.arctan2(gy, gx), np.pi)
    bin_position = orientation * (bins / np.pi)
    bin0 = np.floor(bin_position).astype(np.int32) % bins
    bin1 = (bin0 + 1) % bins
    weight1 = bin_position - np.floor(bin_position)
    weight0 = 1.0 - weight1

    cell_size = gray.shape[0] // cells
    cell_y = np.repeat(np.arange(cells), cell_size)[:, None]
    cell_x = np.repeat(np.arange(cells), cell_size)[None, :]
    cell_y = np.broadcast_to(cell_y, gray.shape)
    cell_x = np.broadcast_to(cell_x, gray.shape)
    histograms = np.zeros((cells, cells, bins), dtype=np.float32)
    np.add.at(histograms, (cell_y, cell_x, bin0), magnitude * weight0)
    np.add.at(histograms, (cell_y, cell_x, bin1), magnitude * weight1)

    blocks: list[np.ndarray] = []
    for y in range(cells - 1):
        for x in range(cells - 1):
            block = histograms[y:y + 2, x:x + 2].ravel()
            block /= np.sqrt(np.dot(block, block) + 1e-6)
            blocks.append(block)
    return np.concatenate(blocks)


def extract_features(patch_rgb: np.ndarray) -> np.ndarray:
    resized = resize_bilinear(patch_rgb) / 255.0
    hue, saturation, value = rgb_to_hsv(resized * 255.0)
    hue_angle = hue * (2.0 * np.pi)
    hue_sin = np.sin(hue_angle) * saturation
    hue_cos = np.cos(hue_angle) * saturation
    tennis_mask = (
        (hue >= 18.0 / 180.0)
        & (hue <= 60.0 / 180.0)
        & (saturation >= 45.0 / 255.0)
        & (value >= 35.0 / 255.0)
    ).astype(np.float32)

    spatial = np.stack((hue_sin, hue_cos, saturation, value, tennis_mask), axis=-1)
    spatial = spatial.reshape(16, 2, 16, 2, 5).mean(axis=(1, 3)).ravel()

    gray = (
        resized[..., 0] * 0.299
        + resized[..., 1] * 0.587
        + resized[..., 2] * 0.114
    )
    hog = _hog(gray)

    hue_hist = np.histogram(hue, bins=18, range=(0.0, 1.0), weights=saturation)[0]
    hue_hist = hue_hist / max(float(hue_hist.sum()), 1e-6)
    saturation_hist = np.histogram(saturation, bins=8, range=(0.0, 1.0))[0].astype(np.float32)
    value_hist = np.histogram(value, bins=8, range=(0.0, 1.0))[0].astype(np.float32)
    saturation_hist /= saturation.size
    value_hist /= value.size

    center = tennis_mask[8:24, 8:24]
    border = tennis_mask.copy()
    border[8:24, 8:24] = 0.0
    statistics = np.asarray(
        [
            *resized.mean(axis=(0, 1)),
            *resized.std(axis=(0, 1)),
            saturation.mean(),
            saturation.std(),
            value.mean(),
            value.std(),
            tennis_mask.mean(),
            center.mean(),
            border.sum() / float(tennis_mask.size - center.size),
            gray.std(),
        ],
        dtype=np.float32,
    )

    return np.concatenate(
        (
            spatial.astype(np.float32),
            hog.astype(np.float32),
            hue_hist.astype(np.float32),
            saturation_hist,
            value_hist,
            statistics,
        )
    )


class TennisBallVerifier:
    """Load and run the exported standardized logistic-regression model."""

    def __init__(self, model_path: str | Path) -> None:
        with np.load(model_path, allow_pickle=False) as model:
            version = int(model["feature_version"])
            if version != FEATURE_VERSION:
                raise ValueError(
                    f"Unsupported verifier feature version {version}; expected {FEATURE_VERSION}"
                )
            self.mean = model["mean"].astype(np.float32)
            self.scale = model["scale"].astype(np.float32)
            self.weights = model["weights"].astype(np.float32)
            self.intercept = float(model["intercept"])
            self.threshold = float(model["threshold"])

    def predict_probability(self, patch_rgb: np.ndarray) -> float:
        features = extract_features(patch_rgb)
        if features.shape != self.weights.shape:
            raise ValueError(
                f"Verifier feature mismatch: {features.shape} != {self.weights.shape}"
            )
        standardized = (features - self.mean) / self.scale
        logit = float(np.dot(standardized, self.weights) + self.intercept)
        logit = float(np.clip(logit, -40.0, 40.0))
        return 1.0 / (1.0 + float(np.exp(-logit)))
