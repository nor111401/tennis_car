from __future__ import annotations

import unittest
from unittest.mock import patch
import sys

from robot_gateway.obstacle import DistanceSample, Hcsr04Reader, ObstacleGuard


def sample(distance: float | None, at: float, sequence: int) -> DistanceSample:
    return DistanceSample(distance, at, sequence)


class ObstacleGuardTests(unittest.TestCase):
    def test_entry_turn_and_two_fresh_clear_samples(self) -> None:
        guard = ObstacleGuard()
        self.assertEqual(guard.step(sample(25, 1, 1), 1)[0], "NORMAL")
        self.assertEqual(guard.step(sample(20, 1.01, 2), 1.01)[0], "STOP")
        self.assertTrue(guard.avoiding)
        self.assertEqual(guard.step(sample(19, 1.08, 3), 1.08)[0], "STOP")
        self.assertEqual(guard.step(sample(19, 1.15, 4), 1.15)[0], "TURN_START")
        self.assertEqual(guard.step(sample(19, 1.20, 5), 1.20)[0], "TURN_HOLD")
        self.assertEqual(guard.step(sample(35, 1.40, 6), 1.40)[0], "STOP")
        self.assertEqual(guard.step(sample(35, 1.48, 7), 1.52)[0], "STOP")
        self.assertEqual(guard.step(sample(31, 1.55, 8), 1.55)[0], "STOP")
        self.assertEqual(guard.step(sample(31, 1.63, 9), 1.63)[0], "CLEAR")
        self.assertFalse(guard.avoiding)

    def test_no_echo_is_clear_only_before_an_obstacle_is_latched(self) -> None:
        guard = ObstacleGuard()
        self.assertEqual(guard.step(sample(float("inf"), 1, 1), 1)[0], "NORMAL")
        self.assertEqual(guard.step(sample(None, 1, 1), 1)[0], "STOP")
        self.assertEqual(guard.step(sample(50, 1, 2), 1.3)[0], "STOP")
        self.assertEqual(guard.step(sample(50, 1.31, 3), 1.31)[0], "NORMAL")
        guard.step(sample(15, 2, 4), 2)
        self.assertEqual(
            guard.step(sample(float("inf"), 2.2, 5), 2.2),
            ("STOP", "OBSTACLE NO ECHO"),
        )
        self.assertTrue(guard.avoiding)
        self.assertEqual(guard.step(sample(None, 2.2, 5), 2.2)[0], "STOP")
        self.assertTrue(guard.avoiding)
        self.assertEqual(guard.step(sample(35, 2.4, 6), 2.4)[0], "STOP")
        self.assertEqual(guard.step(sample(35, 2.5, 7), 2.5)[0], "CLEAR")

    def test_hysteresis_and_turn_limit(self) -> None:
        guard = ObstacleGuard()
        guard.step(sample(20, 1, 1), 1)
        for turn in range(guard.MAX_TURNS):
            start = 1.2 + turn * 0.5
            self.assertEqual(guard.step(sample(25, start, 2 + turn * 2), start)[0], "TURN_START")
            self.assertEqual(guard.step(sample(25, start + .25, 3 + turn * 2), start + .25)[0], "STOP")
        next_at = 1.2 + guard.MAX_TURNS * 0.5
        self.assertEqual(guard.step(sample(25, next_at, 100), next_at)[0], "STOP")
        self.assertTrue(guard.blocked)
        guard.reset()
        self.assertFalse(guard.avoiding)

    def test_invalid_thresholds(self) -> None:
        with self.assertRaises(ValueError):
            ObstacleGuard(30, 20)

    def test_camera_interruption_keeps_obstacle_latched(self) -> None:
        guard = ObstacleGuard()
        guard.step(sample(18, 1, 1), 1)
        self.assertEqual(guard.step(sample(18, 1.2, 2), 1.2)[0], "TURN_START")
        guard.interrupt(1.25)
        self.assertTrue(guard.avoiding)
        self.assertEqual(guard.step(sample(18, 1.26, 3), 1.26)[0], "STOP")


class Hcsr04ReaderTests(unittest.TestCase):
    def test_echo_width_conversion_and_out_of_range_pulse(self) -> None:
        class FakeGpio:
            BOTH_EDGES = 3
            SET_PULL_DOWN = 32

            def __init__(self) -> None:
                self.width_us = 1160
                self.callback_fn = None

            def gpiochip_open(self, _chip):
                return 1

            def gpio_claim_output(self, *_args):
                return 0

            def gpio_claim_alert(self, *_args):
                return 0

            def callback(self, _handle, _pin, _edges, function):
                self.callback_fn = function
                return self

            def cancel(self):
                pass

            def gpio_read(self, *_args):
                return 0

            def tx_pulse(self, _handle, pin, on_us, *_args):
                self.assertions = (pin, on_us)
                if self.width_us is not None:
                    self.callback_fn(0, 24, 1, 1_000_000)
                    self.callback_fn(0, 24, 0, 1_000_000 + self.width_us * 1000)
                return 1

            def gpio_write(self, *_args):
                return 0

            def gpio_free(self, *_args):
                return 0

            def gpio_claim_input(self, _handle, pin, flags):
                self.input_claim = (pin, flags)
                return 0

            def gpiochip_close(self, *_args):
                return 0

        fake = FakeGpio()
        with patch.dict(sys.modules, {"lgpio": fake}):
            reader = Hcsr04Reader()
            self.assertAlmostEqual(reader.read_cm(), 19.72)
            self.assertEqual(fake.assertions, (23, 10))
            fake.width_us = 1740
            self.assertAlmostEqual(reader.read_cm(), 29.58)
            fake.width_us = 46_800
            self.assertEqual(reader.read_cm(), float("inf"))
            fake.width_us = 66_000
            self.assertEqual(reader.read_cm(), float("inf"))
            fake.width_us = 75_000
            self.assertIsNone(reader.read_cm())
            fake.width_us = None
            self.assertEqual(reader.read_cm(), float("inf"))
            reader.close()
            self.assertEqual(fake.input_claim, (23, fake.SET_PULL_DOWN))


if __name__ == "__main__":
    unittest.main()
