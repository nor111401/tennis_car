"""Safe UART control for the ZMotorD four-motor vehicle.

The motor polarity and IDs in this module come from ``小车指令.docx``:

* Motors 001 and 003 move forward above PWM 1500.
* Motors 002 and 004 move forward below PWM 1500.
* PWM 1500 stops a motor.

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
    LEFT_SCAN = "LEFT_SCAN"
    LEFT_OBSERVE = "LEFT_OBSERVE"
    RETURN_FROM_LEFT = "RETURN_FROM_LEFT"
    RETURN_FROM_LEFT_PAUSE = "RETURN_FROM_LEFT_PAUSE"
    CENTER_SETTLE = "CENTER_SETTLE"
    RIGHT_SCAN = "RIGHT_SCAN"
    RIGHT_OBSERVE = "RIGHT_OBSERVE"
    RETURN_FROM_RIGHT = "RETURN_FROM_RIGHT"
    RETURN_FROM_RIGHT_PAUSE = "RETURN_FROM_RIGHT_PAUSE"


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
    speed_delta: int = 300
    refresh_interval: float = 0.25
    min_command_time_ms: int = 300
    command_time_ms: int = 1000
    close_area_ratio: float = 0.44
    lost_search_enabled: bool = True
    lost_search_delay: float = 10.0
    search_speed_delta: int = 400
    search_turn_time_ms: int = 250
    search_steps_per_side: int = 3
    search_observe_seconds: float = 0.80
    search_step_pause_seconds: float = 0.25
    search_settle_seconds: float = 0.50

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
            speed_delta=_env_int("TENNIS_MOTOR_SPEED_DELTA", 300),
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
            lost_search_enabled=_env_bool(
                "TENNIS_LOST_SEARCH_ENABLE",
                True,
            ),
            lost_search_delay=_env_float(
                "TENNIS_LOST_SEARCH_DELAY_SECONDS",
                10.0,
            ),
            search_speed_delta=_env_int(
                "TENNIS_SEARCH_SPEED_DELTA",
                400,
            ),
            search_turn_time_ms=_env_int(
                "TENNIS_SEARCH_TURN_MS",
                250,
            ),
            search_steps_per_side=_env_int(
                "TENNIS_SEARCH_STEPS_PER_SIDE",
                3,
            ),
            search_observe_seconds=_env_float(
                "TENNIS_SEARCH_OBSERVE_SECONDS",
                0.80,
            ),
            search_step_pause_seconds=_env_float(
                "TENNIS_SEARCH_STEP_PAUSE_SECONDS",
                0.25,
            ),
            search_settle_seconds=_env_float(
                "TENNIS_SEARCH_SETTLE_SECONDS",
                0.50,
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
        if self.lost_search_delay <= 0:
            raise ValueError("lost_search_delay must be positive")
        if not self.min_speed_delta <= self.search_speed_delta <= 1000:
            raise ValueError(
                "search_speed_delta must be between min_speed_delta and 1000"
            )
        if not 1 <= self.search_turn_time_ms <= 9999:
            raise ValueError("search_turn_time_ms must be between 1 and 9999")
        if not 1 <= self.search_steps_per_side <= 20:
            raise ValueError("search_steps_per_side must be between 1 and 20")
        if self.search_observe_seconds <= 0:
            raise ValueError("search_observe_seconds must be positive")
        if self.search_step_pause_seconds < 0:
            raise ValueError("search_step_pause_seconds cannot be negative")
        if self.search_settle_seconds < 0:
            raise ValueError("search_settle_seconds cannot be negative")


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

    if motion is Motion.FORWARD:
        pwm_by_id = {1: high, 2: low, 3: high, 4: low}
    elif motion is Motion.REVERSE:
        pwm_by_id = {1: low, 2: high, 3: low, 4: high}
    elif motion is Motion.TURN_LEFT:
        pwm_by_id = {1: low, 2: low, 3: low, 4: low}
    elif motion is Motion.TURN_RIGHT:
        pwm_by_id = {1: high, 2: high, 3: high, 4: high}
    else:
        raise ValueError(f"Unsupported motion: {motion}")

    return [
        format_motor_command(motor_id, pwm, time_ms)
        for motor_id, pwm in pwm_by_id.items()
    ]


class MotorController:
    """Turns ball position into safe, refreshable motor commands."""

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
    def search_status(self) -> str:
        if not self.config.lost_search_enabled:
            return "DISABLED"
        if self._lost_since is None:
            return "TRACKING"
        if self._search_phase is SearchPhase.WAITING:
            remaining = max(
                0.0,
                self.config.lost_search_delay
                - (self._clock() - self._lost_since),
            )
            return f"WAIT {remaining:.1f}s"
        status = self._search_phase.value.replace("_", " ")
        if self._search_step:
            status += f" {self._search_step}/{self.config.search_steps_per_side}"
        return status

    def update(
        self,
        position: str,
        area_ratio: float = 0.0,
        target_x: float | None = None,
    ) -> Motion:
        if target_x is not None and not 0.0 <= target_x <= 1.0:
            raise ValueError("target_x must be within [0, 1]")

        if position == "LOST":
            return self._update_lost_search()

        if (
            self._search_phase is not SearchPhase.IDLE
            and self._motion in (Motion.TURN_LEFT, Motion.TURN_RIGHT)
        ):
            print("SEARCH STATE: STOP_FOR_TARGET")
            self._set_motion(Motion.STOP, force=True)
        self._reset_lost_search()

        if area_ratio >= self.config.close_area_ratio:
            desired = Motion.STOP
        elif position == "LEFT":
            desired = Motion.TURN_LEFT
        elif position == "RIGHT":
            desired = Motion.TURN_RIGHT
        elif position == "CENTER":
            desired = Motion.FORWARD
        else:
            raise ValueError(f"Unknown target position: {position}")

        if desired is Motion.STOP:
            speed_delta = 0
            command_time_ms = 0
        else:
            intensity = self._motion_intensity(
                desired,
                area_ratio,
                target_x,
            )
            speed_delta = self._quantized_interpolation(
                self.config.min_speed_delta,
                self.config.speed_delta,
                intensity,
                step=10,
            )
            command_time_ms = self._quantized_interpolation(
                self.config.min_command_time_ms,
                self.config.command_time_ms,
                intensity,
                step=50,
            )

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

        self._reset_lost_search()
        if motion is Motion.STOP or intensity == 0:
            self._set_motion(Motion.STOP)
            return Motion.STOP

        speed_delta = self._quantized_interpolation(
            self.config.min_speed_delta,
            self.config.speed_delta,
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

        if self._search_phase is SearchPhase.WAITING:
            if now - self._lost_since >= self.config.lost_search_delay:
                self._search_step = 1
                self._begin_search_turn(
                    Motion.TURN_LEFT,
                    SearchPhase.LEFT_SCAN,
                    now,
                )
        elif self._search_phase is SearchPhase.LEFT_SCAN:
            if now >= self._search_deadline:
                self._set_motion(Motion.STOP, force=True)
                self._set_search_phase(
                    SearchPhase.LEFT_OBSERVE,
                    now + self.config.search_observe_seconds,
                )
        elif self._search_phase is SearchPhase.LEFT_OBSERVE:
            if now >= self._search_deadline:
                if self._search_step < self.config.search_steps_per_side:
                    self._search_step += 1
                    self._begin_search_turn(
                        Motion.TURN_LEFT,
                        SearchPhase.LEFT_SCAN,
                        now,
                    )
                else:
                    self._search_step = 1
                    self._begin_search_turn(
                        Motion.TURN_RIGHT,
                        SearchPhase.RETURN_FROM_LEFT,
                        now,
                    )
        elif self._search_phase is SearchPhase.RETURN_FROM_LEFT:
            if now >= self._search_deadline:
                self._set_motion(Motion.STOP, force=True)
                if self._search_step < self.config.search_steps_per_side:
                    self._set_search_phase(
                        SearchPhase.RETURN_FROM_LEFT_PAUSE,
                        now + self.config.search_step_pause_seconds,
                    )
                else:
                    self._set_search_phase(
                        SearchPhase.CENTER_SETTLE,
                        now + self.config.search_settle_seconds,
                    )
        elif self._search_phase is SearchPhase.RETURN_FROM_LEFT_PAUSE:
            if now >= self._search_deadline:
                self._search_step += 1
                self._begin_search_turn(
                    Motion.TURN_RIGHT,
                    SearchPhase.RETURN_FROM_LEFT,
                    now,
                )
        elif self._search_phase is SearchPhase.CENTER_SETTLE:
            if now >= self._search_deadline:
                self._search_step = 1
                self._begin_search_turn(
                    Motion.TURN_RIGHT,
                    SearchPhase.RIGHT_SCAN,
                    now,
                )
        elif self._search_phase is SearchPhase.RIGHT_SCAN:
            if now >= self._search_deadline:
                self._set_motion(Motion.STOP, force=True)
                self._set_search_phase(
                    SearchPhase.RIGHT_OBSERVE,
                    now + self.config.search_observe_seconds,
                )
        elif self._search_phase is SearchPhase.RIGHT_OBSERVE:
            if now >= self._search_deadline:
                if self._search_step < self.config.search_steps_per_side:
                    self._search_step += 1
                    self._begin_search_turn(
                        Motion.TURN_RIGHT,
                        SearchPhase.RIGHT_SCAN,
                        now,
                    )
                else:
                    self._search_step = 1
                    self._begin_search_turn(
                        Motion.TURN_LEFT,
                        SearchPhase.RETURN_FROM_RIGHT,
                        now,
                    )
        elif self._search_phase is SearchPhase.RETURN_FROM_RIGHT:
            if now >= self._search_deadline:
                self._set_motion(Motion.STOP, force=True)
                if self._search_step < self.config.search_steps_per_side:
                    self._set_search_phase(
                        SearchPhase.RETURN_FROM_RIGHT_PAUSE,
                        now + self.config.search_step_pause_seconds,
                    )
                else:
                    self._lost_since = now
                    self._search_step = 0
                    self._set_search_phase(SearchPhase.WAITING)
        elif self._search_phase is SearchPhase.RETURN_FROM_RIGHT_PAUSE:
            if now >= self._search_deadline:
                self._search_step += 1
                self._begin_search_turn(
                    Motion.TURN_LEFT,
                    SearchPhase.RETURN_FROM_RIGHT,
                    now,
                )

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

    def _reset_lost_search(self) -> None:
        if self._lost_since is not None:
            print("SEARCH STATE: TARGET_FOUND")
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
        self._set_motion(Motion.STOP, force=force)

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
                f"PWM={NEUTRAL_PWM + speed_delta}/"
                f"{NEUTRAL_PWM - speed_delta} "
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
