import assert from "node:assert/strict";
import test from "node:test";

import {
  getContainedMediaRect,
  mapNormalizedBoxToPixels,
} from "../src/overlay.js";

test("maps a square camera frame inside a 4:3 stage", () => {
  const media = getContainedMediaRect(580, 435, 640, 640);
  assert.deepEqual(media, { left: 72.5, top: 0, width: 435, height: 435 });

  const box = mapNormalizedBoxToPixels(media, {
    x: 0.4,
    y: 0.3,
    width: 0.2,
    height: 0.1,
  });
  assert.deepEqual(box, {
    left: 246.5,
    top: 130.5,
    width: 87,
    height: 43.5,
  });
});

test("maps a wide media frame with vertical letterboxing", () => {
  const media = getContainedMediaRect(580, 435, 16, 9);
  assert.equal(media.left, 0);
  assert.equal(media.width, 580);
  assert.equal(media.height, 326.25);
  assert.equal(media.top, 54.375);
});
