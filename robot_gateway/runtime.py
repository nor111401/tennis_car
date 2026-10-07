"""Camera, recognition, video and motor workers for the robot gateway."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
from threading import Condition, Event, Lock, Thread
import time

from .core import GatewayMode, GatewayMotion, RobotGatewayCore, TaskMode
from .obstacle import ObstacleGuard, UltrasonicSampler


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class RuntimeSettings:
    camera_enabled: bool = False
    camera_width: int = 960
    camera_height: int = 720
    camera_fps: float = 30.0
    video_fps: float = 15.0
    jpeg_quality: int = 78
    motor_output_enabled: bool = False
    mode_gpio_enabled: bool = False
    mode_gpio_pin: int = 17
    obstacle_enabled: bool = False
    obstacle_trigger_pin: int = 23
    obstacle_echo_pin: int = 24
    obstacle_enter_cm: float = 20.0
    obstacle_clear_cm: float = 30.0
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
            camera_width=int(os.environ.get(
                "TENNIS_GATEWAY_CAMERA_WIDTH",
                "960",
            )),
            camera_height=int(os.environ.get(
                "TENNIS_GATEWAY_CAMERA_HEIGHT",
                "720",
            )),
            camera_fps=float(os.environ.get(
                "TENNIS_GATEWAY_CAMERA_FPS",
                "30",
            )),
            video_fps=float(os.environ.get("TENNIS_GATEWAY_VIDEO_FPS", "15")),
            jpeg_quality=int(os.environ.get("TENNIS_GATEWAY_JPEG_QUALITY", "78")),
            motor_output_enabled=_env_bool("TENNIS_MOTOR_ENABLE"),
            mode_gpio_enabled=_env_bool("TENNIS_MODE_GPIO_ENABLE"),
            mode_gpio_pin=int(os.environ.get("TENNIS_MODE_GPIO_PIN", "17")),
            obstacle_enabled=_env_bool("TENNIS_OBSTACLE_ENABLE"),
            obstacle_trigger_pin=int(os.environ.get("TENNIS_OBSTACLE_TRIG_PIN", "23")),
            obstacle_echo_pin=int(os.environ.get("TENNIS_OBSTACLE_ECHO_PIN", "24")),
            obstacle_enter_cm=float(os.environ.get("TENNIS_OBSTACLE_ENTER_CM", "20")),
            obstacle_clear_cm=float(os.environ.get("TENNIS_OBSTACLE_CLEAR_CM", "30")),
            boot_mode=boot_mode,
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if not 320 <= self.camera_width <= 2592:
            raise ValueError(
                "TENNIS_GATEWAY_CAMERA_WIDTH must be within [320, 2592]"
            )
        if not 240 <= self.camera_height <= 1944:
            raise ValueError(
                "TENNIS_GATEWAY_CAMERA_HEIGHT must be within [240, 1944]"
            )
        if self.camera_width % 2 or self.camera_height % 2:
            raise ValueError("gateway camera dimensions must be even")
        if not 1.0 <= self.camera_fps <= 60.0:
            raise ValueError(
                "TENNIS_GATEWAY_CAMERA_FPS must be within [1, 60]"
            )
        if not 1.0 <= self.video_fps <= 30.0:
            raise ValueError("TENNIS_GATEWAY_VIDEO_FPS must be within [1, 30]")
        if not 40 <= self.jpeg_quality <= 95:
            raise ValueError("TENNIS_GATEWAY_JPEG_QUALITY must be within [40, 95]")
        if not 0 <= self.mode_gpio_pin <= 27:
            raise ValueError("TENNIS_MODE_GPIO_PIN must be within [0, 27]")
        if self.mode_gpio_pin in {14, 15}:
            raise ValueError("TENNIS_MODE_GPIO_PIN must not use UART GPIO14/15")
        pins = (self.obstacle_trigger_pin, self.obstacle_echo_pin)
        if any(pin < 0 or pin > 27 or pin in {14, 15} for pin in pins):
            raise ValueError("obstacle pins must be BCM 0..27 and not UART 14/15")
        if len({self.mode_gpio_pin, *pins}) != 3:
            raise ValueError("obstacle pins must differ from each other and task GPIO")
        if not 0 < self.obstacle_enter_cm < self.obstacle_clear_cm <= 600:
            raise ValueError("obstacle thresholds must satisfy 0 < enter < clear <= 600 cm")


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
    target_bottom: float | None = None
    bottom_exit_loss: bool = False
    captured_at: float = 0.0
    valid: bool = False
    candidate_visible: bool = False


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
        self._obstacle_sampler = (
            UltrasonicSampler(
                self.settings.obstacle_trigger_pin,
                self.settings.obstacle_echo_pin,
            ) if self.settings.obstacle_enabled else None
        )
        self._obstacle_guard = ObstacleGuard(
            self.settings.obstacle_enter_cm,
            self.settings.obstacle_clear_cm,
        )

        self.core.configure_runtime(
            video_available=self.settings.camera_enabled,
            motor_output_enabled=self.settings.motor_output_enabled,
            mode_gpio_enabled=self.settings.mode_gpio_enabled,
            mode_gpio_pin=self.settings.mode_gpio_pin,
            boot_mode=self.settings.boot_mode,
        )

    def start(self) -> None:
        if self._threads:
            return
        self._stop_event.clear()
        if self._obstacle_sampler is not None:
            self._obstacle_sampler.start()
        if self.settings.mode_gpio_enabled:
            mode_gpio_thread = Thread(
                target=self._mode_gpio_loop,
                name="tennis-task-mode-gpio",
                daemon=True,
            )
            self._threads.append(mode_gpio_thread)
            mode_gpio_thread.start()

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
        if self._obstacle_sampler is not None:
            self._obstacle_sampler.close()

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

    def _write_mode_gpio(self, level: int) -> None:
        pin = self.settings.mode_gpio_pin
        level_flag = "dh" if level else "dl"
        result = subprocess.run(
            ["/usr/bin/pinctrl", "set", str(pin), "op", "pn", level_flag],
            check=False,
            capture_output=True,
            text=True,
            timeout=2.0,
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            raise RuntimeError(
                f"pinctrl exited {result.returncode}"
                + (f": {detail}" if detail else "")
            )

    def _mode_gpio_loop(self) -> None:
        current_level: int | None = None
        while not self._stop_event.is_set():
            snapshot = self.core.control_snapshot()
            target_mode = snapshot["task_mode"]
            desired_level = 1 if target_mode is TaskMode.PICKUP else 0
            if desired_level != current_level:
                try:
                    self._write_mode_gpio(desired_level)
                except Exception as exc:
                    self.core.update_mode_gpio(
                        online=False,
                        level=current_level,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                    self._stop_event.wait(1.0)
                    continue
                current_level = desired_level
                self.core.update_mode_gpio(
                    online=True,
                    level=current_level,
                )
            self._stop_event.wait(0.05)

        try:
            self._write_mode_gpio(0)
            self.core.update_mode_gpio(online=False, level=0)
        except Exception as exc:
            self.core.update_mode_gpio(
                online=False,
                level=None,
                error=f"shutdown low failed: {type(exc).__name__}: {exc}",
            )

    def _vision_loop(self) -> None:
        camera = None
        camera_started = False
        try:
            import cv2
            from picamera2 import Picamera2

            from tennis_ball_rpi import (
                CAMERA_SHARPNESS,
                DIGITAL_ZOOM,
                FILTER_CONFIG,
                MultiBallTracker,
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
                    "size": (
                        self.settings.camera_width,
                        self.settings.camera_height,
                    ),
                    "format": "RGB888",
                },
                controls={
                    "FrameRate": self.settings.camera_fps,
                    "Sharpness": CAMERA_SHARPNESS,
                },
                buffer_count=4,
            ))
            camera.start()
            camera_started = True
            time.sleep(1.0)

            target_confirmation = TargetConfirmation(
                FILTER_CONFIG.confirm_frames,
                FILTER_CONFIG.confirm_max_jump,
            )
            target_tracker = MultiBallTracker()
            runner_context = build_runner_context(self.project_folder)
            previous_frame_at = time.perf_counter()
            last_video_at = 0.0
            last_vision_status = None
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
                                target_tracker,
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
                            "bottom_exit_loss": False,
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
                            "bottom_exit_loss": False,
                        }

                    now = time.perf_counter()
                    elapsed = now - previous_frame_at
                    previous_frame_at = now
                    fps = 1.0 / elapsed if elapsed > 0 else 0.0
                    inference_ms = float(
                        result.get("timing", {}).get("classification", 0.0)
                    )

                    target_bottom = (
                        min(1.0, details["ball_y"] + details["ball_height"] / 2)
                        if details["detected"] else None
                    )
                    vision_status = details.get("vision_status", "NO_TARGET_GEOMETRY")
                    if vision_status != last_vision_status:
                        print(
                            f"VISION STATE: {vision_status} x={target_x} "
                            f"bottom={target_bottom} area={area_ratio:.4f} "
                            f"loss_ok={details['bottom_exit_loss']}"
                        )
                        last_vision_status = vision_status
                    self._set_observation(TrackingObservation(
                        position=position,
                        area_ratio=area_ratio,
                        target_x=target_x,
                        target_bottom=target_bottom,
                        bottom_exit_loss=details["bottom_exit_loss"],
                        captured_at=captured_at,
                        valid=True,
                        candidate_visible=bool(details.get("candidate_visible", False)),
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
                GatewayMotion.REVERSE: Motion.REVERSE,
                GatewayMotion.TURN_LEFT: Motion.TURN_LEFT,
                GatewayMotion.TURN_RIGHT: Motion.TURN_RIGHT,
            }
            gateway_map = {value: key for key, value in motion_map.items()}
            obstacle_resume_after = 0.0

            while not self._stop_event.is_set():
                self.core.tick()
                snapshot = self.core.control_snapshot()
                mode = snapshot["mode"]
                observation = self._get_observation()

                if snapshot["emergency_stop"]:
                    self._obstacle_guard.reset()
                    actual = Motion.STOP
                    controller.stop()
                    search_phase = "EMERGENCY_STOP"
                elif mode is GatewayMode.AUTO:
                    observation_age = time.monotonic() - observation.captured_at
                    if not observation.valid or observation_age > self.MAX_OBSERVATION_AGE_SECONDS:
                        self._obstacle_guard.interrupt(time.monotonic())
                        actual = Motion.STOP
                        controller.stop()
                        search_phase = "CAMERA_WAIT"
                    else:
                        obstacle_action, obstacle_phase = (
                            self._obstacle_guard.step(
                                self._obstacle_sampler.snapshot(), time.monotonic()
                            ) if self._obstacle_sampler is not None else ("NORMAL", "")
                        )
                        if obstacle_action == "STOP":
                            actual = Motion.STOP
                            controller.stop()
                            search_phase = obstacle_phase
                        elif obstacle_action == "CLEAR":
                            actual = Motion.STOP
                            controller.stop(force=True)
                            obstacle_resume_after = time.monotonic()
                            search_phase = obstacle_phase
                        elif obstacle_action == "TURN_START":
                            actual = controller.drive_obstacle_turn(
                                int(self._obstacle_guard.TURN_SECONDS * 1000)
                            )
                            search_phase = obstacle_phase
                        elif obstacle_action == "TURN_HOLD":
                            actual = Motion.TURN_LEFT
                            search_phase = obstacle_phase
                        elif observation.captured_at <= obstacle_resume_after:
                            actual = Motion.STOP
                            controller.stop()
                            search_phase = "OBSTACLE VISION WAIT"
                        else:
                            actual = controller.update(
                                "CENTER" if observation.area_ratio >= 1.0 else observation.position,
                                observation.area_ratio,
                                0.5 if observation.area_ratio >= 1.0 else observation.target_x,
                                None if observation.area_ratio >= 1.0 else observation.target_bottom,
                                observation.bottom_exit_loss,
                                observation.captured_at,
                                candidate_visible=observation.candidate_visible,
                            )
                            search_phase = (
                                "TOO_CLOSE" if observation.area_ratio >= 1.0
                                and not controller.pickup_active else controller.search_status
                            )
                elif mode is GatewayMode.MANUAL:
                    self._obstacle_guard.reset()
                    actual = controller.drive_manual(
                        motion_map[snapshot["motion"]],
                        float(snapshot["manual_speed"]),
                    )
                    search_phase = "MANUAL"
                else:
                    self._obstacle_guard.reset()
                    actual = Motion.STOP
                    controller.stop()
                    search_phase = mode.value

                self.core.update_runtime_motion(
                    gateway_map[actual],
                    search_phase=search_phase,
                    motor_online=output_online,
                    uart_online=output_online,
                    auto_pickup=(
                        mode is GatewayMode.AUTO
                        and controller.pickup_active
                    ),
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
