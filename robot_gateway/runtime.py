"""Camera, recognition, video and motor workers for the robot gateway."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from threading import Condition, Event, Lock, Thread
import time

from .core import GatewayMode, GatewayMotion, RobotGatewayCore


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class RuntimeSettings:
    camera_enabled: bool = False
    video_fps: float = 15.0
    jpeg_quality: int = 78
    motor_output_enabled: bool = False
    boot_mode: GatewayMode = GatewayMode.AUTO

    @classmethod
    def from_environment(cls) -> "RuntimeSettings":
        boot_mode_value = os.environ.get(
            "TENNIS_GATEWAY_BOOT_MODE",
            GatewayMode.AUTO.value,
        ).strip().upper()
        try:
            boot_mode = GatewayMode(boot_mode_value)
        except ValueError as exc:
            raise ValueError(
                "TENNIS_GATEWAY_BOOT_MODE must be AUTO or PAUSED"
            ) from exc
        if boot_mode not in {GatewayMode.AUTO, GatewayMode.PAUSED}:
            raise ValueError("TENNIS_GATEWAY_BOOT_MODE must be AUTO or PAUSED")

        settings = cls(
            camera_enabled=_env_bool("TENNIS_GATEWAY_CAMERA_ENABLE"),
            video_fps=float(os.environ.get("TENNIS_GATEWAY_VIDEO_FPS", "15")),
            jpeg_quality=int(os.environ.get("TENNIS_GATEWAY_JPEG_QUALITY", "78")),
            motor_output_enabled=_env_bool("TENNIS_MOTOR_ENABLE"),
            boot_mode=boot_mode,
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if not 1.0 <= self.video_fps <= 30.0:
            raise ValueError("TENNIS_GATEWAY_VIDEO_FPS must be within [1, 30]")
        if not 40 <= self.jpeg_quality <= 95:
            raise ValueError("TENNIS_GATEWAY_JPEG_QUALITY must be within [40, 95]")


class LatestJpegFrame:
    """Single-slot frame buffer; slow clients always skip to the latest frame."""

    def __init__(self) -> None:
        self._condition = Condition()
        self._sequence = 0
        self._jpeg: bytes | None = None
        self._captured_at = 0.0
        self._closed = False

    def publish(self, jpeg: bytes, captured_at: float) -> int:
        if not jpeg:
            raise ValueError("jpeg frame cannot be empty")
        with self._condition:
            if self._closed:
                return self._sequence
            self._sequence += 1
            self._jpeg = bytes(jpeg)
            self._captured_at = captured_at
            self._condition.notify_all()
            return self._sequence

    def wait_after(
        self,
        sequence: int,
        timeout: float = 1.0,
    ) -> tuple[int, bytes, float] | None:
        with self._condition:
            self._condition.wait_for(
                lambda: self._closed or self._sequence > sequence,
                timeout=max(0.0, timeout),
            )
            if self._closed or self._sequence <= sequence or self._jpeg is None:
                return None
            return self._sequence, self._jpeg, self._captured_at

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()


@dataclass(frozen=True)
class TrackingObservation:
    position: str = "LOST"
    area_ratio: float = 0.0
    target_x: float | None = None
    captured_at: float = 0.0
    valid: bool = False


class RobotRuntime:
    MOTOR_PERIOD_SECONDS = 0.02
    MAX_OBSERVATION_AGE_SECONDS = 0.50

    def __init__(
        self,
        core: RobotGatewayCore,
        settings: RuntimeSettings | None = None,
        project_folder: Path | None = None,
    ) -> None:
        self.core = core
        self.settings = settings or RuntimeSettings.from_environment()
        self.project_folder = project_folder or Path(__file__).resolve().parent.parent
        self.frames = LatestJpegFrame()
        self._stop_event = Event()
        self._threads: list[Thread] = []
        self._observation_lock = Lock()
        self._observation = TrackingObservation()

        self.core.configure_runtime(
            video_available=self.settings.camera_enabled,
            motor_output_enabled=self.settings.motor_output_enabled,
            boot_mode=self.settings.boot_mode,
        )

    def start(self) -> None:
        if self._threads:
            return
        self._stop_event.clear()
        motor_thread = Thread(
            target=self._motor_loop,
            name="tennis-motor-runtime",
            daemon=True,
        )
        self._threads.append(motor_thread)
        motor_thread.start()

        if self.settings.camera_enabled:
            vision_thread = Thread(
                target=self._vision_loop,
                name="tennis-vision-runtime",
                daemon=True,
            )
            self._threads.append(vision_thread)
            vision_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self.frames.close()
        for thread in self._threads:
            thread.join(timeout=4.0)
        self._threads.clear()

    def wait_for_frame(
        self,
        sequence: int,
        timeout: float = 1.0,
    ) -> tuple[int, bytes, float] | None:
        return self.frames.wait_after(sequence, timeout)

    def _set_observation(self, observation: TrackingObservation) -> None:
        with self._observation_lock:
            self._observation = observation

    def _get_observation(self) -> TrackingObservation:
        with self._observation_lock:
            return self._observation

    def _vision_loop(self) -> None:
        camera = None
        camera_started = False
        try:
            import cv2
            from picamera2 import Picamera2

            from tennis_ball_rpi import (
                CAMERA_FPS,
                CAMERA_HEIGHT,
                CAMERA_SHARPNESS,
                CAMERA_WIDTH,
                DIGITAL_ZOOM,
                FILTER_CONFIG,
                TargetConfirmation,
                apply_center_zoom,
                build_runner_context,
                center_crop_square,
                process_bounding_boxes,
                process_classification,
                resize_for_display,
            )

            camera = Picamera2()
            camera.configure(camera.create_video_configuration(
                main={
                    "size": (CAMERA_WIDTH, CAMERA_HEIGHT),
                    "format": "RGB888",
                },
                controls={
                    "FrameRate": CAMERA_FPS,
                    "Sharpness": CAMERA_SHARPNESS,
                },
            ))
            camera.start()
            camera_started = True
            time.sleep(1.0)

            target_confirmation = TargetConfirmation(
                FILTER_CONFIG.confirm_frames,
                FILTER_CONFIG.confirm_max_jump,
            )
            runner_context = build_runner_context(self.project_folder)
            previous_frame_at = time.perf_counter()
            last_video_at = 0.0
            minimum_video_period = 1.0 / self.settings.video_fps

            with runner_context as runner:
                model_info = runner.init()
                parameters = model_info["model_parameters"]
                labels = parameters.get("labels", [])
                model_width = int(parameters["image_input_width"])
                model_height = int(parameters["image_input_height"])

                while not self._stop_event.is_set():
                    captured_at = time.monotonic()
                    frame_bgr = camera.capture_array()
                    frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
                    inference_rgb = apply_center_zoom(frame_rgb, DIGITAL_ZOOM)
                    features, _ = runner.get_features_from_image(inference_rgb)
                    preview_rgb = center_crop_square(inference_rgb)
                    result = runner.classify(features)
                    result_data = result.get("result", {})

                    if "bounding_boxes" in result_data:
                        display, position, area_ratio, target_x, details = (
                            process_bounding_boxes(
                                result,
                                preview_rgb,
                                model_width,
                                model_height,
                                target_confirmation,
                                log_events=False,
                            )
                        )
                    elif "classification" in result_data:
                        target_confirmation.reset()
                        display = process_classification(result, labels, preview_rgb)
                        position, area_ratio, target_x = "LOST", 0.0, None
                        details = {
                            "detected": False,
                            "confidence": 0.0,
                            "ball_x": None,
                            "ball_y": None,
                            "ball_width": None,
                            "ball_height": None,
                        }
                    else:
                        target_confirmation.reset()
                        display_bgr = cv2.cvtColor(preview_rgb, cv2.COLOR_RGB2BGR)
                        display, _ = resize_for_display(display_bgr)
                        position, area_ratio, target_x = "LOST", 0.0, None
                        details = {
                            "detected": False,
                            "confidence": 0.0,
                            "ball_x": None,
                            "ball_y": None,
                            "ball_width": None,
                            "ball_height": None,
                        }

                    now = time.perf_counter()
                    elapsed = now - previous_frame_at
                    previous_frame_at = now
                    fps = 1.0 / elapsed if elapsed > 0 else 0.0
                    inference_ms = float(
                        result.get("timing", {}).get("classification", 0.0)
                    )

                    self._set_observation(TrackingObservation(
                        position=position,
                        area_ratio=area_ratio,
                        target_x=target_x,
                        captured_at=captured_at,
                        valid=True,
                    ))
                    self.core.update_perception(
                        detected=bool(details["detected"]),
                        confidence=float(details["confidence"]),
                        ball_x=details["ball_x"],
                        ball_y=details["ball_y"],
                        ball_width=details["ball_width"],
                        ball_height=details["ball_height"],
                        camera_fps=fps,
                        inference_ms=inference_ms,
                    )

                    self._draw_gateway_status(display, cv2)
                    if now - last_video_at >= minimum_video_period:
                        encoded, jpeg = cv2.imencode(
                            ".jpg",
                            display,
                            [cv2.IMWRITE_JPEG_QUALITY, self.settings.jpeg_quality],
                        )
                        if not encoded:
                            raise RuntimeError("OpenCV JPEG encoding failed")
                        self.frames.publish(jpeg.tobytes(), captured_at)
                        last_video_at = now

        except Exception as exc:
            self.core.report_runtime_error(
                f"camera runtime: {type(exc).__name__}: {exc}",
                camera_failed=True,
            )
        finally:
            if camera_started and camera is not None:
                try:
                    camera.stop()
                except Exception:
                    pass

    def _draw_gateway_status(self, display, cv2) -> None:
        snapshot = self.core.control_snapshot()
        mode = snapshot["mode"].value
        motion = snapshot["motion"].value
        cv2.putText(
            display,
            f"MODE: {mode}  MOTION: {motion}",
            (15, max(25, display.shape[0] - 15)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (255, 255, 0),
            2,
        )

    def _motor_loop(self) -> None:
        controller = None
        try:
            from zmotord_uart import Motion, MotorController

            controller = MotorController.from_environment()
            output_online = bool(controller.config.enabled)
            self.core.update_runtime_motion(
                GatewayMotion.STOP,
                search_phase="READY",
                motor_online=output_online,
                uart_online=output_online,
            )

            motion_map = {
                GatewayMotion.STOP: Motion.STOP,
                GatewayMotion.FORWARD: Motion.FORWARD,
                GatewayMotion.TURN_LEFT: Motion.TURN_LEFT,
                GatewayMotion.TURN_RIGHT: Motion.TURN_RIGHT,
            }
            gateway_map = {value: key for key, value in motion_map.items()}

            while not self._stop_event.is_set():
                self.core.tick()
                snapshot = self.core.control_snapshot()
                mode = snapshot["mode"]
                observation = self._get_observation()

                if snapshot["emergency_stop"]:
                    actual = Motion.STOP
                    controller.stop()
                    search_phase = "EMERGENCY_STOP"
                elif mode is GatewayMode.AUTO:
                    observation_age = time.monotonic() - observation.captured_at
                    if not observation.valid or observation_age > self.MAX_OBSERVATION_AGE_SECONDS:
                        actual = Motion.STOP
                        controller.stop()
                        search_phase = "CAMERA_WAIT"
                    elif observation.area_ratio >= 1.0:
                        actual = controller.update("CENTER", 1.0, 0.5)
                        search_phase = "TOO_CLOSE"
                    else:
                        actual = controller.update(
                            observation.position,
                            observation.area_ratio,
                            observation.target_x,
                        )
                        search_phase = controller.search_status
                elif mode is GatewayMode.MANUAL:
                    actual = controller.drive_manual(
                        motion_map[snapshot["motion"]],
                        float(snapshot["manual_speed"]),
                    )
                    search_phase = "MANUAL"
                else:
                    actual = Motion.STOP
                    controller.stop()
                    search_phase = mode.value

                self.core.update_runtime_motion(
                    gateway_map[actual],
                    search_phase=search_phase,
                    motor_online=output_online,
                    uart_online=output_online,
                )
                self._stop_event.wait(self.MOTOR_PERIOD_SECONDS)

        except Exception as exc:
            self.core.report_runtime_error(
                f"motor runtime: {type(exc).__name__}: {exc}",
            )
        finally:
            if controller is not None:
                try:
                    controller.close()
                except Exception:
                    pass
            self.core.update_runtime_motion(
                GatewayMotion.STOP,
                search_phase="STOPPED" if self._stop_event.is_set() else "MOTOR_ERROR",
                motor_online=False,
                uart_online=False,
            )
