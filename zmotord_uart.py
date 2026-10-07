"""Safe UART control for the ZMotorD four-motor vehicle.

Motion PWM patterns are calibrated to the current wheel installation.
PWM 1500 stops a motor; the raw command format comes from ``小车指令.docx``.

Real motor output is disabled unless ``TENNIS_MOTOR_ENABLE=1`` is set.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import os
from pathlib import Path
import time
from typing import Callable, Protocol

try:
    import termios
except ImportError:  # Allows command-generation tests to run on Windows.
    termios = None


NEUTRAL_PWM = 1500
MIN_PWM = 500
MAX_PWM = 2500


class Motion(str, Enum):
    STOP = "STOP"
    FORWARD = "FORWARD"
    REVERSE = "REVERSE"
    TURN_LEFT = "TURN_LEFT"
    TURN_RIGHT = "TURN_RIGHT"


class SearchPhase(str, Enum):
    IDLE = "IDLE"
    WAITING = "WAITING"
    SWEEP_TURN = "SWEEP_TURN"
    SWEEP_OBSERVE = "SWEEP_OBSERVE"


class UartTransport(Protocol):
    def write(self, data: bytes) -> None:
        ...

    def close(self) -> None:
        ...


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    return default if value is None else int(value)


def _env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    return default if value is None else float(value)


@dataclass(frozen=True)
class MotorConfig:
    enabled: bool = False
    device: str = "/dev/serial0"
    baud: int = 115200
    min_speed_delta: int = 200
    speed_delta: int = 1000
    manual_speed_delta: int = 1000
    refresh_interval: float = 0.25
    min_command_time_ms: int = 300
    command_time_ms: int = 1000
    close_area_ratio: float = 0.44
    bottom_exit_forward_seconds: float = 3.0
    pickup_open_seconds: float = 3.0
    bottom_exit_min_bottom: float = 0.80
    aim_deadband: float = 0.06
    near_aim_min_bottom: float = 0.80
    near_aim_deadband: float = 0.15
    aim_turn_min_ms: int = 120
    aim_turn_max_ms: int = 220
    aim_settle_seconds: float = 0.15
    lost_search_enabled: bool = True
    lost_search_delay: float = 2.0
    search_speed_delta: int = 1000
    search_turn_time_ms: int = 500
    # Estimated from the reported old 6-step / 120-degree scan; calibrate on the vehicle.
    search_steps_per_revolution: int = 18
    search_observe_seconds: float = 0.80

    @classmethod
    def from_environment(cls) -> "MotorConfig":
        config = cls(
            enabled=_env_bool("TENNIS_MOTOR_ENABLE"),
            device=os.environ.get(
                "TENNIS_UART_DEVICE",
                "/dev/serial0",
            ),
            baud=_env_int("TENNIS_UART_BAUD", 115200),
            min_speed_delta=_env_int(
                "TENNIS_MOTOR_MIN_SPEED_DELTA",
                200,
            ),
            speed_delta=_env_int("TENNIS_MOTOR_SPEED_DELTA", 1000),
            manual_speed_delta=_env_int(
                "TENNIS_MANUAL_SPEED_DELTA",
                _env_int("TENNIS_MANUAL_FORWARD_SPEED_DELTA", 1000),
            ),
            refresh_interval=_env_float(
                "TENNIS_MOTOR_REFRESH_SECONDS",
                0.25,
            ),
            min_command_time_ms=_env_int(
                "TENNIS_MOTOR_MIN_COMMAND_MS",
                300,
            ),
            command_time_ms=_env_int(
                "TENNIS_MOTOR_COMMAND_MS",
                1000,
            ),
            close_area_ratio=_env_float(
                "TENNIS_STOP_AREA_RATIO",
                0.44,
            ),
            bottom_exit_forward_seconds=_env_float(
                "TENNIS_BOTTOM_EXIT_FORWARD_SECONDS",
                3.0,
            ),
            pickup_open_seconds=_env_float(
                "TENNIS_PICKUP_OPEN_SECONDS",
                3.0,
            ),
            bottom_exit_min_bottom=_env_float(
                "TENNIS_BOTTOM_EXIT_MIN_BOTTOM",
                0.80,
            ),
            aim_deadband=_env_float("TENNIS_AIM_DEADBAND", 0.06),
            near_aim_min_bottom=_env_float("TENNIS_NEAR_AIM_MIN_BOTTOM", 0.80),
            near_aim_deadband=_env_float("TENNIS_NEAR_AIM_DEADBAND", 0.15),
            aim_turn_min_ms=_env_int("TENNIS_AIM_TURN_MIN_MS", 120),
            aim_turn_max_ms=_env_int("TENNIS_AIM_TURN_MAX_MS", 220),
            aim_settle_seconds=_env_float("TENNIS_AIM_SETTLE_SECONDS", 0.15),
            lost_search_enabled=_env_bool(
                "TENNIS_LOST_SEARCH_ENABLE",
                True,
            ),
            lost_search_delay=_env_float(
                "TENNIS_LOST_SEARCH_DELAY_SECONDS",
                2.0,
            ),
            search_speed_delta=_env_int(
                "TENNIS_SEARCH_SPEED_DELTA",
                1000,
            ),
            search_turn_time_ms=_env_int(
                "TENNIS_SEARCH_TURN_MS",
                500,
            ),
            search_steps_per_revolution=_env_int(
                "TENNIS_SEARCH_STEPS_PER_REVOLUTION",
                18,
            ),
            search_observe_seconds=_env_float(
                "TENNIS_SEARCH_OBSERVE_SECONDS",
                0.80,
            ),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if not 200 <= self.min_speed_delta <= 1000:
            raise ValueError(
                "min_speed_delta must be between 200 and 1000 "
                "so moving PWM stays at least 1700/1300"
            )
        if not 1 <= self.speed_delta <= 1000:
            raise ValueError("speed_delta must be between 1 and 1000")
        if self.min_speed_delta > self.speed_delta:
            raise ValueError("min_speed_delta cannot exceed speed_delta")
        if not self.min_speed_delta <= self.manual_speed_delta <= 1000:
            raise ValueError(
                "manual_speed_delta must be between "
                "min_speed_delta and 1000"
            )
        if self.refresh_interval <= 0:
            raise ValueError("refresh_interval must be positive")
        if not 1 <= self.min_command_time_ms <= 9999:
            raise ValueError("min_command_time_ms must be between 1 and 9999")
        if not 1 <= self.command_time_ms <= 9999:
            raise ValueError("command_time_ms must be between 1 and 9999")
        if self.min_command_time_ms > self.command_time_ms:
            raise ValueError(
                "min_command_time_ms cannot exceed command_time_ms"
            )
        if not 0 < self.close_area_ratio <= 1:
            raise ValueError("close_area_ratio must be in (0, 1]")
        if not 0 <= self.bottom_exit_forward_seconds <= 5.0:
            raise ValueError("bottom_exit_forward_seconds must be within [0, 5]")
        if not self.bottom_exit_forward_seconds <= self.pickup_open_seconds <= 5.0:
            raise ValueError(
                "pickup_open_seconds must be between "
                "bottom_exit_forward_seconds and 5"
            )
        if not 0.5 <= self.bottom_exit_min_bottom <= 1.0:
            raise ValueError("bottom_exit_min_bottom must be within [0.5, 1]")
        if not 0 < self.aim_deadband < 0.5:
            raise ValueError("aim_deadband must be within (0, 0.5)")
        if not 0.5 <= self.near_aim_min_bottom <= self.bottom_exit_min_bottom:
            raise ValueError(
                "near_aim_min_bottom must be within [0.5, bottom_exit_min_bottom]"
            )
        if not self.aim_deadband <= self.near_aim_deadband <= 0.25:
            raise ValueError("near_aim_deadband must be within [aim_deadband, 0.25]")
        if not 1 <= self.aim_turn_min_ms <= self.aim_turn_max_ms <= 1000:
            raise ValueError("aim turn times must be within [1, 1000] and ordered")
        if not 0 <= self.aim_settle_seconds <= 1.0:
            raise ValueError("aim_settle_seconds must be within [0, 1]")
        if self.lost_search_delay <= 0:
            raise ValueError("lost_search_delay must be positive")
        if not self.min_speed_delta <= self.search_speed_delta <= 1000:
            raise ValueError(
                "search_speed_delta must be between min_speed_delta and 1000"
            )
        if not 1 <= self.search_turn_time_ms <= 9999:
            raise ValueError("search_turn_time_ms must be between 1 and 9999")
        if not 1 <= self.search_steps_per_revolution <= 36:
            raise ValueError("search_steps_per_revolution must be between 1 and 36")
        if self.search_observe_seconds <= 0:
            raise ValueError("search_observe_seconds must be positive")


class PosixUart:
    """Small dependency-free POSIX UART writer."""

    def __init__(self, device: str, baud: int) -> None:
        if termios is None:
            raise OSError("POSIX termios UART is only available on Linux")

        device_path = Path(device)
        if not device_path.exists():
            raise FileNotFoundError(f"UART device does not exist: {device}")

        command_line_path = Path("/proc/cmdline")
        if command_line_path.exists():
            command_line = command_line_path.read_text(
                encoding="utf-8",
                errors="replace",
            )
            resolved_name = device_path.resolve().name
            console_names = {"serial0", resolved_name}
            if any(
                f"console={name}," in command_line
                for name in console_names
            ):
                raise RuntimeError(
                    f"UART {device} is still used as a Linux serial console. "
                    "Disable the serial login console and reboot before "
                    "setting TENNIS_MOTOR_ENABLE=1."
                )

        baud_constant = getattr(termios, f"B{baud}", None)
        if baud_constant is None:
            raise ValueError(f"This system does not support UART baud {baud}")

        self._fd = os.open(
            device,
            os.O_RDWR | os.O_NOCTTY | os.O_SYNC,
        )

        try:
            attributes = termios.tcgetattr(self._fd)
            attributes[0] = 0
            attributes[1] = 0
            attributes[2] = (
                termios.CLOCAL
                | termios.CREAD
                | termios.CS8
            )
            attributes[3] = 0
            attributes[4] = baud_constant
            attributes[5] = baud_constant
            attributes[6][termios.VMIN] = 0
            attributes[6][termios.VTIME] = 0
            termios.tcsetattr(
                self._fd,
                termios.TCSANOW,
                attributes,
            )
            termios.tcflush(self._fd, termios.TCIOFLUSH)
        except Exception:
            os.close(self._fd)
            self._fd = -1
            raise

    def write(self, data: bytes) -> None:
        if self._fd < 0:
            raise RuntimeError("UART is closed")

        view = memoryview(data)
        while view:
            written = os.write(self._fd, view)
            if written <= 0:
                raise OSError("UART write returned no data")
            view = view[written:]
        termios.tcdrain(self._fd)

    def close(self) -> None:
        if self._fd >= 0:
            os.close(self._fd)
            self._fd = -1


def format_motor_command(
    motor_id: int,
    pwm: int,
    time_ms: int,
) -> bytes:
    if not 0 <= motor_id <= 255:
        raise ValueError("motor_id must be between 0 and 255")
    if not MIN_PWM <= pwm <= MAX_PWM:
        raise ValueError("pwm must be between 500 and 2500")
    if not 0 <= time_ms <= 9999:
        raise ValueError("time_ms must be between 0 and 9999")

    return f"#{motor_id:03d}P{pwm:04d}T{time_ms:04d}!".encode("ascii")


def commands_for_motion(
    motion: Motion,
    speed_delta: int,
    time_ms: int,
) -> list[bytes]:
    if motion is Motion.STOP:
        return [format_motor_command(255, NEUTRAL_PWM, 0)]

    high = NEUTRAL_PWM + speed_delta
    low = NEUTRAL_PWM - speed_delta

    # Installed motors: the original forward/reverse patterns turned right/left,
    # while the original right/left patterns drove forward/reverse.
    if motion is Motion.FORWARD:
        pwm_by_id = {1: high, 2: high, 3: high, 4: high}
    elif motion is Motion.REVERSE:
        pwm_by_id = {1: low, 2: low, 3: low, 4: low}
    elif motion is Motion.TURN_LEFT:
        pwm_by_id = {1: low, 2: high, 3: low, 4: high}
    elif motion is Motion.TURN_RIGHT:
        pwm_by_id = {1: high, 2: low, 3: high, 4: low}
    else:
        raise ValueError(f"Unsupported motion: {motion}")

    return [
        format_motor_command(motor_id, pwm, time_ms)
        for motor_id, pwm in pwm_by_id.items()
    ]


class MotorController:
    """Turns ball position into safe, refreshable motor commands."""

    CANDIDATE_CONFIRM_SECONDS = 1.0

    def __init__(
        self,
        config: MotorConfig,
        transport: UartTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        config.validate()
        self.config = config
        self._transport = transport
        self._motion: Motion | None = None
        self._last_send = 0.0
        self._last_speed_delta = 0
        self._last_command_time_ms = 0
        self._closed = False
        self._clock = clock
        self._lost_since: float | None = None
        self._search_phase = SearchPhase.IDLE
        self._search_deadline = 0.0
        self._search_step = 0
        self._pickup_consumed = False
        self._pickup_rearm_after = 0.0
        self._bottom_exit_deadline: float | None = None
        self._pickup_open_deadline: float | None = None
        self._aim_turn_deadline: float | None = None
        self._aim_observe_after: float | None = None
        self._candidate_deadline: float | None = None
        self._candidate_observe_after: float | None = None
        self._candidate_blocked = False
        self._candidate_retry_after = 0.0

        if self.config.enabled and self._transport is None:
            self._transport = PosixUart(
                self.config.device,
                self.config.baud,
            )

        if self.config.enabled:
            print(
                "Motor UART ENABLED: "
                f"{self.config.device} at {self.config.baud} baud"
            )
            self.stop(force=True)
        else:
            print(
                "Motor UART disabled (dry run). "
                "Set TENNIS_MOTOR_ENABLE=1 only after wiring checks."
            )

    @classmethod
    def from_environment(cls) -> "MotorController":
        return cls(MotorConfig.from_environment())

    @property
    def motion(self) -> Motion | None:
        return self._motion

    @property
    def active_high_pwm(self) -> int:
        if self._motion is Motion.STOP or self._motion is None:
            return NEUTRAL_PWM
        return NEUTRAL_PWM + self._last_speed_delta

    @property
    def active_low_pwm(self) -> int:
        if self._motion is Motion.STOP or self._motion is None:
            return NEUTRAL_PWM
        return NEUTRAL_PWM - self._last_speed_delta

    @property
    def active_command_time_ms(self) -> int:
        return self._last_command_time_ms

    @property
    def search_phase(self) -> SearchPhase:
        return self._search_phase

    @property
    def bottom_exit_active(self) -> bool:
        return (
            self._bottom_exit_deadline is not None
            and self._clock() < self._bottom_exit_deadline
        )

    @property
    def pickup_active(self) -> bool:
        """Collection output window, including the stopped hold after driving."""
        return (
            self._pickup_open_deadline is not None
            and self._clock() < self._pickup_open_deadline
        )

    @property
    def search_status(self) -> str:
        if self._bottom_exit_deadline is not None:
            remaining = max(0.0, self._bottom_exit_deadline - self._clock())
            return f"PICKUP {remaining:.1f}s"
        if self.pickup_active:
            remaining = self._pickup_open_deadline - self._clock()
            return f"PICKUP HOLD {remaining:.1f}s"
        if self._candidate_deadline is not None:
            remaining = max(0.0, self._candidate_deadline - self._clock())
            return f"TARGET VERIFY {remaining:.1f}s"
        if self._aim_turn_deadline is not None:
            return f"AIM {self._motion.value}" if self._motion else "AIM TURN"
        if self._aim_observe_after is not None:
            return "AIM OBSERVE"
        if not self.config.lost_search_enabled:
            return "DISABLED"
        if self._lost_since is None:
            return "PICKUP COMPLETE" if self._pickup_consumed else "TRACKING"
        if self._search_phase is SearchPhase.WAITING:
            remaining = max(
                0.0,
                self.config.lost_search_delay
                - (self._clock() - self._lost_since),
            )
            return f"WAIT {remaining:.1f}s"
        status = self._search_phase.value.replace("_", " ")
        if self._search_step:
            status += f" {self._search_step}/{self.config.search_steps_per_revolution}"
        return status

    def update(
        self,
        position: str,
        area_ratio: float = 0.0,
        target_x: float | None = None,
        target_bottom: float | None = None,
        allow_bottom_exit: bool = False,
        observation_time: float | None = None,
        *,
        candidate_visible: bool = False,
    ) -> Motion:
        # Legacy allow_bottom_exit is accepted for API compatibility only.
        # Collection now starts from visible geometry, not a later empty frame.
        if target_x is not None and not 0.0 <= target_x <= 1.0:
            raise ValueError("target_x must be within [0, 1]")
        if target_bottom is not None and not 0.0 <= target_bottom <= 1.0:
            raise ValueError("target_bottom must be within [0, 1]")
        if position not in {"LEFT", "CENTER", "RIGHT", "LOST"}:
            raise ValueError(f"Unknown target position: {position}")

        # The committed window has priority over ALL visual target outcomes.
        # External mode, camera and obstacle guards still call stop() before update().
        if self._bottom_exit_deadline is not None or self._pickup_open_deadline is not None:
            return self._update_pickup_window()

        # A provisional candidate can only stop us, never supply driving geometry.
        # TOO_CLOSE remains an immediate stop, including during confirmation.
        if position != "LOST" and area_ratio >= self.config.close_area_ratio:
            self._reset_candidate_confirmation()
        else:
            candidate_motion = self._update_candidate_confirmation(
                position, candidate_visible, observation_time,
            )
            if candidate_motion is not None:
                return candidate_motion

        if position == "LOST":
            self._reset_aim()
            return self._update_lost_search()

        if (
            self._pickup_consumed and target_bottom is not None
            and target_bottom >= self.config.bottom_exit_min_bottom
        ):
            self._reset_aim()
            self._reset_lost_search()
            self._set_motion(Motion.STOP)
            return Motion.STOP

        if (
            self._search_phase is not SearchPhase.IDLE
            and self._motion in (Motion.TURN_LEFT, Motion.TURN_RIGHT)
        ):
            print("SEARCH STATE: STOP_FOR_TARGET")
            self._set_motion(Motion.STOP, force=True)
        self._reset_lost_search()

        near_target = (
            target_bottom is not None
            and target_bottom >= self.config.near_aim_min_bottom
        )
        active_deadband = (
            self.config.near_aim_deadband if near_target else self.config.aim_deadband
        )
        if area_ratio >= self.config.close_area_ratio:
            desired = Motion.STOP
        elif target_x is not None:
            error = target_x - 0.5
            if abs(error) <= active_deadband + 1e-9:
                desired = Motion.FORWARD
            else:
                desired = Motion.TURN_RIGHT if error > 0 else Motion.TURN_LEFT
        elif position == "LEFT":
            desired = Motion.TURN_LEFT
        elif position == "RIGHT":
            desired = Motion.TURN_RIGHT
        elif position == "CENTER":
            desired = Motion.FORWARD

        if desired is Motion.STOP:
            self._reset_aim()
        elif self._aim_turn_deadline is not None:
            turn_started_at = self._aim_turn_deadline - self._last_command_time_ms / 1000.0
            if (
                near_target and desired is Motion.FORWARD
                and observation_time is not None and observation_time > turn_started_at
            ):
                # A fresh near-ball frame can stop a turn, but not skip settling.
                print("PICKUP STATE: NEAR_AIM_STOP")
                self._set_motion(Motion.STOP, force=True)
                self._aim_turn_deadline = None
                self._aim_observe_after = self._clock() + self.config.aim_settle_seconds
                return Motion.STOP
            if self._clock() < self._aim_turn_deadline:
                return self._motion if self._motion is not None else Motion.STOP
            self._set_motion(Motion.STOP, force=True)
            self._aim_turn_deadline = None
            self._aim_observe_after = self._clock() + self.config.aim_settle_seconds
            return Motion.STOP
        elif self._aim_observe_after is not None:
            if (
                self._clock() < self._aim_observe_after
                or (
                    observation_time is not None
                    and observation_time <= self._aim_observe_after
                )
            ):
                self._set_motion(Motion.STOP)
                return Motion.STOP
            self._aim_observe_after = None

        if desired in (Motion.TURN_LEFT, Motion.TURN_RIGHT):
            horizontal_error = abs(target_x - 0.5) if target_x is not None else 0.5
            intensity = min(1.0, max(0.0, (
                horizontal_error - self.config.aim_deadband
            ) / (0.5 - self.config.aim_deadband)))
            command_time_ms = self._quantized_interpolation(
                self.config.aim_turn_min_ms,
                self.config.aim_turn_max_ms,
                intensity,
                step=10,
            )
            self._set_motion(
                desired,
                speed_delta=self.config.speed_delta,
                command_time_ms=command_time_ms,
            )
            self._aim_turn_deadline = self._clock() + command_time_ms / 1000.0
            return desired

        if desired is Motion.STOP:
            speed_delta = 0
            command_time_ms = 0
        else:
            intensity = self._motion_intensity(
                desired,
                area_ratio,
                target_x,
            )
            speed_delta = self.config.speed_delta
            command_time_ms = self._quantized_interpolation(
                self.config.min_command_time_ms,
                self.config.command_time_ms,
                intensity,
                step=50,
            )

        if (
            desired is Motion.FORWARD
            and target_x is not None
            and target_bottom is not None
            and target_bottom < self.config.bottom_exit_min_bottom
            and (observation_time is None or observation_time > self._pickup_rearm_after)
        ):
            self._pickup_consumed = False

        # A confirmed, aligned visible near ball starts the one-shot window now.
        if (
            desired is Motion.FORWARD and not self._pickup_consumed
            and target_x is not None and target_bottom is not None
            and target_bottom >= self.config.bottom_exit_min_bottom
            and abs(target_x - 0.5) <= active_deadband + 1e-9
            and self.config.bottom_exit_forward_seconds > 0
        ):
            now = self._clock()
            self._pickup_consumed = True
            self._bottom_exit_deadline = now + self.config.bottom_exit_forward_seconds
            self._pickup_open_deadline = now + self.config.pickup_open_seconds
            self._reset_aim()
            self._reset_lost_search()
            print(
                f"PICKUP STATE: NEAR_BALL x={target_x} bottom={target_bottom} "
                f"drive={self.config.bottom_exit_forward_seconds}s "
                f"collector={self.config.pickup_open_seconds}s"
            )
            return self._update_pickup_window(force=True)
        self._set_motion(
            desired,
            speed_delta=speed_delta,
            command_time_ms=command_time_ms,
        )
        return desired

    def drive_manual(self, motion: Motion, intensity: float) -> Motion:
        """Apply a validated manual command using the configured safe range."""
        if not isinstance(intensity, (int, float)) or isinstance(intensity, bool):
            raise ValueError("intensity must be a number")
        if not 0.0 <= float(intensity) <= 1.0:
            raise ValueError("intensity must be within [0, 1]")

        if self._bottom_exit_deadline is not None:
            self._set_motion(Motion.STOP, force=True)
        self._reset_aim()
        self._reset_candidate_confirmation()
        self._reset_pickup()
        self._reset_lost_search(target_found=False)
        if motion is Motion.STOP or intensity == 0:
            self._set_motion(Motion.STOP)
            return Motion.STOP

        speed_delta = self._quantized_interpolation(
            self.config.min_speed_delta,
            self.config.manual_speed_delta,
            float(intensity),
            step=10,
        )
        command_time_ms = self._quantized_interpolation(
            self.config.min_command_time_ms,
            self.config.command_time_ms,
            float(intensity),
            step=50,
        )
        self._set_motion(
            motion,
            speed_delta=speed_delta,
            command_time_ms=command_time_ms,
        )
        return motion

    def drive_obstacle_turn(self, command_time_ms: int = 200) -> Motion:
        """Cancel pickup/search and issue one bounded left-turn pulse."""
        if not 1 <= command_time_ms <= 300:
            raise ValueError("obstacle turn pulse must be within [1, 300] ms")
        self.stop(force=True)
        self._set_motion(
            Motion.TURN_LEFT,
            speed_delta=self.config.search_speed_delta,
            command_time_ms=command_time_ms,
        )
        return Motion.TURN_LEFT

    def _update_pickup_window(self, force: bool = False) -> Motion:
        """Run one fixed deadline; visual observations cannot cancel or extend it."""
        now = self._clock()
        if self._bottom_exit_deadline is not None:
            if now < self._bottom_exit_deadline:
                remaining_ms = max(1, int((self._bottom_exit_deadline - now) * 1000))
                self._set_motion(
                    Motion.FORWARD, force=force, speed_delta=self.config.speed_delta,
                    command_time_ms=min(300, remaining_ms),
                )
                return Motion.FORWARD
            self._bottom_exit_deadline = None
            self._set_motion(Motion.STOP, force=True)
            print("PICKUP STATE: DRIVE_DONE")
        if self._pickup_open_deadline is not None and now < self._pickup_open_deadline:
            self._set_motion(Motion.STOP)
            return Motion.STOP
        self._pickup_open_deadline = None
        self._pickup_rearm_after = now
        self._reset_lost_search()
        self._set_motion(Motion.STOP)
        print("PICKUP STATE: COMPLETE")
        return Motion.STOP

    def _update_candidate_confirmation(
        self, position: str, candidate_visible: bool,
        observation_time: float | None,
    ) -> Motion | None:
        now = self._clock()
        if self._candidate_deadline is not None:
            fresh_confirmed = (
                position != "LOST"
                and now >= self._candidate_observe_after
                and observation_time is not None
                and observation_time > self._candidate_observe_after
            )
            if fresh_confirmed:
                print("SEARCH STATE: CANDIDATE_CONFIRMED")
                self._reset_candidate_confirmation()
                return None
            if now < self._candidate_deadline:
                self._set_motion(Motion.STOP)
                return Motion.STOP
            print("SEARCH STATE: CANDIDATE_TIMEOUT")
            self._candidate_deadline = None
            self._candidate_observe_after = None
            self._candidate_blocked = True
            self._candidate_retry_after = (
                now + self.config.search_turn_time_ms / 1000.0
                + self.config.search_observe_seconds
            )
            # Do not resume the interrupted pulse or restart a two-second wait.
            # Continue with the next bounded search step, retaining sweep progress.
            if self._lost_since is None:
                self._lost_since = now
            self._set_search_phase(SearchPhase.SWEEP_OBSERVE, now)
            return self._update_lost_search()

        if position != "LOST":
            self._reset_candidate_confirmation()
            return None
        if (
            self._candidate_blocked and not candidate_visible
            and observation_time is not None
            and observation_time > self._candidate_retry_after
        ):
            # Require fresh absence after a search turn/observation before retry.
            self._candidate_blocked = False
        if (
            candidate_visible and not self._candidate_blocked
            and self.config.lost_search_enabled
        ):
            self._reset_aim()
            self._candidate_deadline = now + self.CANDIDATE_CONFIRM_SECONDS
            self._candidate_observe_after = now + self.config.aim_settle_seconds
            print("SEARCH STATE: CANDIDATE_VERIFY")
            self._set_motion(Motion.STOP, force=True)
            return Motion.STOP
        return None

    def _reset_candidate_confirmation(self) -> None:
        self._candidate_deadline = None
        self._candidate_observe_after = None
        self._candidate_blocked = False
        self._candidate_retry_after = 0.0

    def _update_lost_search(self) -> Motion:
        now = self._clock()
        if not self.config.lost_search_enabled:
            self._set_motion(Motion.STOP)
            return Motion.STOP

        if self._lost_since is None:
            self._lost_since = now
            self._set_search_phase(SearchPhase.WAITING)
            self._set_motion(Motion.STOP)
            return Motion.STOP

        if self.pickup_active:
            self._set_motion(Motion.STOP)
            return Motion.STOP

        if self._search_phase is SearchPhase.WAITING:
            if now - self._lost_since >= self.config.lost_search_delay:
                self._search_step = 1
                self._begin_search_turn(
                    Motion.TURN_LEFT,
                    SearchPhase.SWEEP_TURN,
                    now,
                )
        elif self._search_phase is SearchPhase.SWEEP_TURN:
            if now >= self._search_deadline:
                self._set_motion(Motion.STOP, force=True)
                self._set_search_phase(
                    SearchPhase.SWEEP_OBSERVE,
                    now + self.config.search_observe_seconds,
                )
        elif self._search_phase is SearchPhase.SWEEP_OBSERVE:
            if now >= self._search_deadline:
                if self._search_step < self.config.search_steps_per_revolution:
                    self._search_step += 1
                    self._begin_search_turn(
                        Motion.TURN_LEFT,
                        SearchPhase.SWEEP_TURN,
                        now,
                    )
                else:
                    self._lost_since = now
                    self._search_step = 0
                    self._set_search_phase(SearchPhase.WAITING)

        return self._motion if self._motion is not None else Motion.STOP

    def _begin_search_turn(
        self,
        motion: Motion,
        phase: SearchPhase,
        now: float,
    ) -> None:
        self._set_search_phase(
            phase,
            now + self.config.search_turn_time_ms / 1000.0,
        )
        self._set_motion(
            motion,
            force=True,
            speed_delta=self.config.search_speed_delta,
            command_time_ms=self.config.search_turn_time_ms,
        )

    def _set_search_phase(
        self,
        phase: SearchPhase,
        deadline: float = 0.0,
    ) -> None:
        if phase is not self._search_phase:
            print(f"SEARCH STATE: {phase.value}")
        self._search_phase = phase
        self._search_deadline = deadline

    def _reset_lost_search(self, target_found: bool = True) -> None:
        if self._lost_since is not None:
            print("SEARCH STATE: TARGET_FOUND" if target_found else "SEARCH STATE: CANCELLED")
        self._lost_since = None
        self._search_phase = SearchPhase.IDLE
        self._search_deadline = 0.0
        self._search_step = 0

    def _motion_intensity(
        self,
        desired: Motion,
        area_ratio: float,
        target_x: float | None,
    ) -> float:
        if desired is Motion.FORWARD:
            return max(
                0.0,
                min(1.0, 1.0 - area_ratio / self.config.close_area_ratio),
            )

        if target_x is None:
            return 1.0

        center_boundary_error = 1.0 / 6.0
        maximum_error = 0.5
        horizontal_error = abs(target_x - 0.5)
        return max(
            0.0,
            min(
                1.0,
                (horizontal_error - center_boundary_error)
                / (maximum_error - center_boundary_error),
            ),
        )

    @staticmethod
    def _quantized_interpolation(
        minimum: int,
        maximum: int,
        intensity: float,
        step: int,
    ) -> int:
        raw_value = minimum + (maximum - minimum) * intensity
        quantized = int(round(raw_value / step) * step)
        return max(minimum, min(maximum, quantized))

    def stop(self, force: bool = False) -> None:
        self._reset_aim()
        self._reset_candidate_confirmation()
        self._reset_lost_search(target_found=False)
        self._reset_pickup()
        self._set_motion(Motion.STOP, force=force)

    def _reset_pickup(self) -> None:
        if self._bottom_exit_deadline is not None or self._pickup_open_deadline is not None:
            print("PICKUP STATE: RESET_EXTERNAL")
        self._bottom_exit_deadline = None
        self._pickup_open_deadline = None
        self._pickup_consumed = False
        self._pickup_rearm_after = 0.0

    def _reset_aim(self) -> None:
        self._aim_turn_deadline = None
        self._aim_observe_after = None

    def _set_motion(
        self,
        desired: Motion,
        force: bool = False,
        speed_delta: int | None = None,
        command_time_ms: int | None = None,
    ) -> None:
        if desired is Motion.STOP:
            speed_delta = 0
            command_time_ms = 0
        else:
            if speed_delta is None:
                speed_delta = self.config.speed_delta
            if command_time_ms is None:
                command_time_ms = self.config.command_time_ms

        now = self._clock()
        changed = desired is not self._motion
        parameters_changed = (
            speed_delta != self._last_speed_delta
            or command_time_ms != self._last_command_time_ms
        )
        refresh_due = (
            desired is not Motion.STOP
            and now - self._last_send >= self.config.refresh_interval
        )

        if not (force or changed or refresh_due):
            return

        if changed:
            print(f"MOTOR STATE: {desired.value}")

        if self.config.enabled:
            if self._transport is None:
                raise RuntimeError("Motor output enabled without a UART transport")

            commands = commands_for_motion(
                desired,
                speed_delta,
                command_time_ms,
            )
            for command in commands:
                self._transport.write(command)

        if desired is not Motion.STOP and (changed or parameters_changed):
            print(
                "MOTOR COMMAND: "
                f"DELTA={speed_delta} "
                f"T={command_time_ms}ms"
            )

        self._motion = desired
        self._last_speed_delta = speed_delta
        self._last_command_time_ms = command_time_ms
        self._last_send = now

    def close(self) -> None:
        if self._closed:
            return

        try:
            if self.config.enabled:
                self.stop(force=True)
        finally:
            if self._transport is not None:
                self._transport.close()
            self._closed = True

    def __enter__(self) -> "MotorController":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()
