"""HC-SR04 sampling and bounded, fail-safe AUTO obstacle avoidance."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Event, Lock, Thread
import math
import time
from typing import Callable


@dataclass(frozen=True)
class DistanceSample:
    distance_cm: float | None = None
    captured_at: float = 0.0
    sequence: int = 0
    error: str | None = None


class Hcsr04Reader:
    """Time Echo edges in the kernel; never poll a millisecond pulse in Python."""

    def __init__(self, trigger_pin: int = 23, echo_pin: int = 24) -> None:
        import lgpio

        self._gpio = lgpio
        self._trigger = trigger_pin
        self._echo = echo_pin
        self._handle = lgpio.gpiochip_open(0)  # Pi 4 40-pin header
        self._lock = Lock()
        self._done = Event()
        self._rise_ns: int | None = None
        self._width_us: float | None = None
        self._callback = None
        try:
            lgpio.gpio_claim_output(self._handle, trigger_pin, 0)
            lgpio.gpio_claim_alert(self._handle, echo_pin, lgpio.BOTH_EDGES)
            self._callback = lgpio.callback(
                self._handle, echo_pin, lgpio.BOTH_EDGES, self._edge
            )
        except BaseException:
            self.close()
            raise

    def _edge(self, _chip: int, gpio: int, level: int, timestamp_ns: int) -> None:
        if gpio != self._echo:
            return
        with self._lock:
            if level == 1:
                self._rise_ns = timestamp_ns
            elif level == 0 and self._rise_ns is not None:
                self._width_us = (timestamp_ns - self._rise_ns) / 1000.0
                self._done.set()

    def read_cm(self) -> float | None:
        gpio = self._gpio
        if gpio.gpio_read(self._handle, self._echo):
            return None  # Echo stuck high; do not interpret as clear space.
        with self._lock:
            self._rise_ns = None
            self._width_us = None
            self._done.clear()
        gpio.tx_pulse(self._handle, self._trigger, 10, 100, 0, 1)
        if not self._done.wait(0.08):
            return float("inf")  # No reflected pulse during a complete ranging cycle.
        with self._lock:
            width_us = self._width_us
        if width_us is None or width_us <= 0:
            return None
        if 36_000 <= width_us <= 72_000:
            # Out-of-range pulse: this vehicle measured ~46.8 ms, while the
            # supplied module document describes ~66 ms. Neither is a near wall.
            return float("inf")
        if width_us > 72_000:
            return None
        return width_us * 0.034 / 2.0

    def close(self) -> None:
        if self._callback is not None:
            self._callback.cancel()
            self._callback = None
        if self._handle is not None:
            try:
                self._gpio.gpio_write(self._handle, self._trigger, 0)
            except Exception:
                pass
            try:
                self._gpio.gpio_free(self._handle, self._trigger)
                self._gpio.gpio_claim_input(
                    self._handle, self._trigger, self._gpio.SET_PULL_DOWN
                )
            except Exception:
                pass
            self._gpio.gpiochip_close(self._handle)
            self._handle = None


class UltrasonicSampler:
    PERIOD_SECONDS = 0.085  # >70 ms worst-case cycle in this module's datasheet.

    def __init__(
        self,
        trigger_pin: int = 23,
        echo_pin: int = 24,
        reader_factory: Callable[[int, int], Hcsr04Reader] = Hcsr04Reader,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._pins = (trigger_pin, echo_pin)
        self._reader_factory = reader_factory
        self._clock = clock
        self._lock = Lock()
        self._sample = DistanceSample(error="STARTING")
        self._stop = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = Thread(target=self._loop, name="tennis-ultrasonic", daemon=True)
        self._thread.start()

    def snapshot(self) -> DistanceSample:
        with self._lock:
            return self._sample

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    def _loop(self) -> None:
        reader = None
        try:
            reader = self._reader_factory(*self._pins)
            while not self._stop.is_set():
                started = self._clock()
                try:
                    distance = reader.read_cm()
                    error = None if distance is not None else "NO_ECHO"
                except Exception as exc:
                    distance = None
                    error = f"{type(exc).__name__}: {exc}"
                with self._lock:
                    self._sample = DistanceSample(
                        distance, self._clock(), self._sample.sequence + 1, error
                    )
                self._stop.wait(max(0.0, self.PERIOD_SECONDS - (self._clock() - started)))
        except Exception as exc:
            with self._lock:
                self._sample = DistanceSample(
                    None, self._clock(), self._sample.sequence + 1,
                    f"{type(exc).__name__}: {exc}",
                )
        finally:
            if reader is not None:
                reader.close()


class ObstacleGuard:
    """Return NORMAL, STOP, TURN_START or TURN_HOLD for each AUTO motor tick."""

    MAX_SAMPLE_AGE_SECONDS = 0.25
    TURN_SECONDS = 0.20
    SETTLE_SECONDS = 0.12
    # 18 x 500 ms was the uncalibrated ball-search revolution estimate.
    MAX_TURNS = 45  # Same nominal total turn time with 200 ms pulses.

    def __init__(self, enter_cm: float = 20.0, clear_cm: float = 30.0) -> None:
        if not 0 < enter_cm < clear_cm:
            raise ValueError("obstacle enter distance must be below clear distance")
        self.enter_cm = enter_cm
        self.clear_cm = clear_cm
        self.reset()

    def reset(self) -> None:
        self.avoiding = False
        self.turn_deadline = 0.0
        self.settle_deadline = 0.0
        self.last_sequence = 0
        self.clear_count = 0
        self.turns = 0
        self.blocked = False

    def interrupt(self, now: float) -> None:
        """Stop an active turn without forgetting an uncleared obstacle."""
        if self.avoiding and self.turn_deadline:
            self.turn_deadline = 0.0
            self.settle_deadline = now + self.SETTLE_SECONDS

    def step(self, sample: DistanceSample, now: float) -> tuple[str, str]:
        if (
            sample.distance_cm is None
            or sample.captured_at <= 0
            or now - sample.captured_at > self.MAX_SAMPLE_AGE_SECONDS
            or sample.captured_at > now
        ):
            self.turn_deadline = 0.0
            self.clear_count = 0
            return "STOP", "OBSTACLE SENSOR WAIT"

        if math.isinf(sample.distance_cm) and self.avoiding:
            # A previously measured near obstacle needs real >clear_cm readings.
            # Losing its echo must not release the latch and resume forward.
            self.turn_deadline = 0.0
            self.clear_count = 0
            return "STOP", "OBSTACLE NO ECHO"

        if not self.avoiding:
            if sample.distance_cm > self.enter_cm:
                return "NORMAL", ""
            self.avoiding = True
            self.settle_deadline = now + self.SETTLE_SECONDS
            self.last_sequence = sample.sequence
            return "STOP", "OBSTACLE STOP"

        if self.blocked:
            return "STOP", "OBSTACLE TURN LIMIT"
        if self.turn_deadline:
            if now < self.turn_deadline:
                return "TURN_HOLD", f"OBSTACLE LEFT {self.turns}/{self.MAX_TURNS}"
            self.turn_deadline = 0.0
            self.settle_deadline = now + self.SETTLE_SECONDS
            self.last_sequence = sample.sequence
            return "STOP", "OBSTACLE MEASURE"
        if now < self.settle_deadline or sample.sequence <= self.last_sequence or sample.captured_at < self.settle_deadline:
            return "STOP", "OBSTACLE MEASURE"

        self.last_sequence = sample.sequence
        if sample.distance_cm > self.clear_cm:
            self.clear_count += 1
            if self.clear_count >= 2:
                self.reset()
                return "CLEAR", "OBSTACLE RESUME"
            return "STOP", "OBSTACLE CLEAR CHECK"
        self.clear_count = 0
        if self.turns >= self.MAX_TURNS:
            self.blocked = True
            return "STOP", "OBSTACLE TURN LIMIT"
        self.turns += 1
        self.turn_deadline = now + self.TURN_SECONDS
        return "TURN_START", f"OBSTACLE LEFT {self.turns}/{self.MAX_TURNS}"
