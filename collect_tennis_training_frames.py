"""Collect square camera frames for local tennis-ball model training."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import time

import cv2
from picamera2 import Picamera2


def center_crop_square(image):
    height, width = image.shape[:2]
    side = min(width, height)
    x = (width - side) // 2
    y = (height - side) // 2
    return image[y:y + side, x:x + side]


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("positive", "negative"))
    parser.add_argument("--duration", type=float, default=40.0)
    parser.add_argument("--fps", type=float, default=5.0)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("/home/pi/tennis/training_data"),
    )
    return parser.parse_args()


def main():
    args = parse_args()
    if args.duration <= 0:
        raise ValueError("duration must be positive")
    if args.fps <= 0:
        raise ValueError("fps must be positive")

    session_name = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_folder = args.root / args.mode / session_name
    output_folder.mkdir(parents=True, exist_ok=False)

    camera = Picamera2()
    camera.configure(
        camera.create_video_configuration(
            main={"size": (640, 480), "format": "RGB888"},
            controls={"FrameRate": 30, "Sharpness": 1.5},
        )
    )
    interval = 1.0 / args.fps
    saved = 0

    try:
        camera.start()
        time.sleep(2.0)
        print(f"COLLECTION START mode={args.mode} folder={output_folder}")
        start_time = time.monotonic()
        next_capture = start_time

        while time.monotonic() - start_time < args.duration:
            frame_bgr = camera.capture_array()
            now = time.monotonic()
            if now < next_capture:
                continue

            square = center_crop_square(frame_bgr)
            path = output_folder / f"frame_{saved:04d}.jpg"
            if not cv2.imwrite(
                str(path),
                square,
                [cv2.IMWRITE_JPEG_QUALITY, 92],
            ):
                raise OSError(f"Could not write {path}")
            saved += 1
            next_capture += interval

            if saved % 25 == 0:
                print(f"COLLECTED {saved}")
    finally:
        camera.stop()

    print(f"COLLECTION COMPLETE mode={args.mode} frames={saved}")
    print(f"OUTPUT={output_folder}")


if __name__ == "__main__":
    main()
