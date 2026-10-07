from __future__ import annotations

import unittest
import io
from contextlib import redirect_stdout
from unittest.mock import patch

from zmotord_uart import (
    Motion,
    MotorConfig,
    MotorController,
    SearchPhase,
    commands_for_motion,
    format_motor_command,
)


class MemoryTransport:
    def __init__(self) -> None:
        self.writes: list[bytes] = []
        self.closed = False

    def write(self, data: bytes) -> None:
        self.writes.append(data)

    def close(self) -> None:
        self.closed = True


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class CommandTests(unittest.TestCase):
    def test_obstacle_turn_cancels_pickup_and_bounds_uart_pulse(self) -> None:
        transport = MemoryTransport()
        controller = MotorController(MotorConfig(enabled=True), transport=transport)
        controller.update("CENTER", 0.1, 0.5, 0.4)
        controller.update("CENTER", 0.1, 0.5, 0.94)
        controller.update("LOST", allow_bottom_exit=True)
        self.assertTrue(controller.pickup_active)
        transport.writes.clear()
        self.assertEqual(controller.drive_obstacle_turn(), Motion.TURN_LEFT)
        self.assertFalse(controller.pickup_active)
        self.assertEqual(transport.writes[0], b"#255P1500T0000!")
        self.assertEqual(
            transport.writes[-4:],
            commands_for_motion(Motion.TURN_LEFT, 1000, 200),
        )
        with self.assertRaises(ValueError):
            controller.drive_obstacle_turn(301)
        controller.close()

    def test_default_auto_speed_matches_manual_full_speed(self) -> None:
        self.assertEqual(MotorConfig().min_speed_delta, 200)
        self.assertEqual(MotorConfig().speed_delta, 1000)
        self.assertEqual(MotorConfig().manual_speed_delta, 1000)
        self.assertEqual(MotorConfig().min_command_time_ms, 300)
        self.assertEqual(MotorConfig().command_time_ms, 1000)
        self.assertEqual(MotorConfig().close_area_ratio, 0.44)
        self.assertEqual(MotorConfig().bottom_exit_forward_seconds, 3.0)
        self.assertEqual(MotorConfig().pickup_open_seconds, 3.0)
        self.assertEqual(MotorConfig().bottom_exit_min_bottom, 0.80)
        self.assertEqual(MotorConfig().aim_deadband, 0.06)
        self.assertEqual(MotorConfig().near_aim_min_bottom, 0.80)
        self.assertEqual(MotorConfig().near_aim_deadband, 0.15)
        self.assertEqual(MotorConfig().aim_turn_min_ms, 120)
        self.assertEqual(MotorConfig().aim_turn_max_ms, 220)
        self.assertEqual(MotorConfig().aim_settle_seconds, 0.15)
        self.assertEqual(MotorConfig().lost_search_delay, 2.0)
        self.assertEqual(MotorConfig().search_speed_delta, 1000)
        self.assertEqual(MotorConfig().search_turn_time_ms, 500)
        self.assertEqual(MotorConfig().search_steps_per_revolution, 18)
        self.assertEqual(MotorConfig().search_observe_seconds, 0.80)

    def test_pickup_open_time_cannot_be_shorter_than_drive_or_over_five_seconds(self) -> None:
        for seconds in (1.9, 5.1):
            with self.subTest(seconds=seconds):
                with self.assertRaisesRegex(ValueError, "pickup_open_seconds"):
                    MotorConfig(pickup_open_seconds=seconds).validate()

    def test_environment_uses_committed_pickup_defaults(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            config = MotorConfig.from_environment()
        self.assertEqual(config.bottom_exit_min_bottom, 0.80)
        self.assertEqual(config.bottom_exit_forward_seconds, 3.0)
        self.assertEqual(config.pickup_open_seconds, 3.0)
        self.assertEqual(config.near_aim_min_bottom, 0.80)
        self.assertEqual(config.near_aim_deadband, 0.15)

    def test_near_aim_configuration_is_bounded_and_environment_can_override(self) -> None:
        for values in (
            {"near_aim_min_bottom": 0.49}, {"near_aim_min_bottom": 0.93},
            {"near_aim_deadband": 0.05}, {"near_aim_deadband": 0.26},
        ):
            with self.subTest(values=values), self.assertRaises(ValueError):
                MotorConfig(**values).validate()
        with patch.dict("os.environ", {
            "TENNIS_NEAR_AIM_MIN_BOTTOM": "0.75",
            "TENNIS_NEAR_AIM_DEADBAND": "0.12",
        }, clear=True):
            config = MotorConfig.from_environment()
        self.assertEqual(config.near_aim_min_bottom, 0.75)
        self.assertEqual(config.near_aim_deadband, 0.12)

    def test_configured_forward_pwm(self) -> None:
        self.assertEqual(
            commands_for_motion(Motion.FORWARD, 300, 1000),
            [
                b"#001P1800T1000!",
                b"#002P1800T1000!",
                b"#003P1800T1000!",
                b"#004P1800T1000!",
            ],
        )

    def test_maximum_forward_pwm(self) -> None:
        self.assertEqual(
            commands_for_motion(Motion.FORWARD, 1000, 1000),
            [
                b"#001P2500T1000!",
                b"#002P2500T1000!",
                b"#003P2500T1000!",
                b"#004P2500T1000!",
            ],
        )

    def test_command_format(self) -> None:
        self.assertEqual(
            format_motor_command(1, 1680, 1000),
            b"#001P1680T1000!",
        )

    def test_forward_polarity_matches_installed_vehicle(self) -> None:
        self.assertEqual(
            commands_for_motion(Motion.FORWARD, 180, 1000),
            [
                b"#001P1680T1000!",
                b"#002P1680T1000!",
                b"#003P1680T1000!",
                b"#004P1680T1000!",
            ],
        )

    def test_reverse_polarity_is_opposite_to_forward(self) -> None:
        self.assertEqual(
            commands_for_motion(Motion.REVERSE, 200, 300),
            [
                b"#001P1300T0300!",
                b"#002P1300T0300!",
                b"#003P1300T0300!",
                b"#004P1300T0300!",
            ],
        )

    def test_turn_commands_match_installed_vehicle(self) -> None:
        self.assertEqual(
            commands_for_motion(Motion.TURN_LEFT, 180, 1000),
            [
                b"#001P1320T1000!",
                b"#002P1680T1000!",
                b"#003P1320T1000!",
                b"#004P1680T1000!",
            ],
        )
        self.assertEqual(
            commands_for_motion(Motion.TURN_RIGHT, 180, 1000),
            [
                b"#001P1680T1000!",
                b"#002P1320T1000!",
                b"#003P1680T1000!",
                b"#004P1320T1000!",
            ],
        )

    def test_lost_ball_and_close_ball_stop(self) -> None:
        transport = MemoryTransport()
        controller = MotorController(
            MotorConfig(enabled=True),
            transport=transport,
        )
        transport.writes.clear()

        controller.update("CENTER", area_ratio=0.01)
        controller.update("LOST")
        controller.update("CENTER", area_ratio=0.30)

        self.assertIn(b"#255P1500T0000!", transport.writes)
        controller.close()
        self.assertTrue(transport.closed)

    def test_near_ball_uses_full_speed_with_short_command(self) -> None:
        transport = MemoryTransport()
        controller = MotorController(
            MotorConfig(enabled=True),
            transport=transport,
        )
        transport.writes.clear()

        controller.update("CENTER", area_ratio=0.439, target_x=0.50)

        self.assertEqual(
            transport.writes,
            [
                b"#001P2500T0300!",
                b"#002P2500T0300!",
                b"#003P2500T0300!",
                b"#004P2500T0300!",
            ],
        )
        controller.close()

    def test_far_ball_uses_maximum_configured_forward_command(self) -> None:
        transport = MemoryTransport()
        controller = MotorController(
            MotorConfig(enabled=True),
            transport=transport,
        )
        transport.writes.clear()

        controller.update("CENTER", area_ratio=0.01, target_x=0.50)

        self.assertEqual(
            transport.writes,
            commands_for_motion(Motion.FORWARD, 1000, 1000),
        )
        controller.close()

    def test_manual_turn_reaches_protocol_maximum_at_full_speed(self) -> None:
        transport = MemoryTransport()
        controller = MotorController(
            MotorConfig(enabled=True),
            transport=transport,
        )
        transport.writes.clear()

        controller.drive_manual(Motion.TURN_LEFT, 1.0)

        self.assertEqual(
            transport.writes,
            commands_for_motion(Motion.TURN_LEFT, 1000, 1000),
        )
        self.assertEqual(controller.active_high_pwm, 2500)
        self.assertEqual(controller.active_low_pwm, 500)
        controller.close()

    def test_manual_forward_reaches_protocol_maximum_at_full_speed(self) -> None:
        transport = MemoryTransport()
        controller = MotorController(
            MotorConfig(enabled=True),
            transport=transport,
        )
        transport.writes.clear()

        controller.drive_manual(Motion.FORWARD, 1.0)

        self.assertEqual(
            transport.writes,
            commands_for_motion(Motion.FORWARD, 1000, 1000),
        )
        self.assertEqual(controller.active_high_pwm, 2500)
        self.assertEqual(controller.active_low_pwm, 500)
        controller.close()

    def test_manual_forward_midpoint_uses_full_manual_range(self) -> None:
        transport = MemoryTransport()
        controller = MotorController(
            MotorConfig(enabled=True),
            transport=transport,
        )
        transport.writes.clear()

        controller.drive_manual(Motion.FORWARD, 0.5)

        self.assertEqual(
            transport.writes,
            commands_for_motion(Motion.FORWARD, 600, 650),
        )
        controller.close()

    def test_manual_reverse_uses_full_manual_range(self) -> None:
        transport = MemoryTransport()
        controller = MotorController(
            MotorConfig(enabled=True),
            transport=transport,
        )
        transport.writes.clear()

        controller.drive_manual(Motion.REVERSE, 0.5)

        self.assertEqual(
            transport.writes,
            commands_for_motion(Motion.REVERSE, 600, 650),
        )
        controller.close()

    def test_auto_directions_match_manual_at_full_speed(self) -> None:
        for position, motion, target_x in (
            ("CENTER", Motion.FORWARD, 0.5),
            ("LEFT", Motion.TURN_LEFT, 0.0),
            ("RIGHT", Motion.TURN_RIGHT, 1.0),
        ):
            with self.subTest(position=position):
                auto_transport = MemoryTransport()
                auto_controller = MotorController(
                    MotorConfig(enabled=True),
                    transport=auto_transport,
                )
                auto_transport.writes.clear()
                auto_controller.update(
                    position,
                    area_ratio=0.0,
                    target_x=target_x,
                )

                manual_transport = MemoryTransport()
                manual_controller = MotorController(
                    MotorConfig(enabled=True),
                    transport=manual_transport,
                )
                manual_transport.writes.clear()
                manual_controller.drive_manual(motion, 1.0)

                turn_time = 1000 if motion is Motion.FORWARD else 220
                self.assertEqual(
                    auto_transport.writes,
                    commands_for_motion(motion, 1000, turn_time),
                )
                self.assertEqual(
                    [command[4:9] for command in auto_transport.writes],
                    [command[4:9] for command in manual_transport.writes],
                )
                auto_controller.close()
                manual_controller.close()

    def test_manual_zero_speed_stops_and_invalid_speed_is_rejected(self) -> None:
        controller = MotorController(MotorConfig(enabled=False))
        controller.drive_manual(Motion.FORWARD, 0.5)
        self.assertEqual(controller.drive_manual(Motion.FORWARD, 0.0), Motion.STOP)
        with self.assertRaises(ValueError):
            controller.drive_manual(Motion.FORWARD, 1.1)
        controller.close()

    def test_turn_duration_grows_toward_image_edge(self) -> None:
        near_transport = MemoryTransport()
        near_controller = MotorController(
            MotorConfig(enabled=True),
            transport=near_transport,
        )
        near_transport.writes.clear()
        near_controller.update("RIGHT", area_ratio=0.02, target_x=2 / 3)

        edge_transport = MemoryTransport()
        edge_controller = MotorController(
            MotorConfig(enabled=True),
            transport=edge_transport,
        )
        edge_transport.writes.clear()
        edge_controller.update("RIGHT", area_ratio=0.02, target_x=1.0)

        self.assertEqual(
            near_transport.writes,
            commands_for_motion(Motion.TURN_RIGHT, 1000, 140),
        )
        self.assertEqual(
            edge_transport.writes,
            commands_for_motion(Motion.TURN_RIGHT, 1000, 220),
        )
        near_controller.close()
        edge_controller.close()

    def test_visible_ball_aim_uses_narrow_center_zone(self) -> None:
        transport = MemoryTransport()
        controller = MotorController(MotorConfig(enabled=True), transport=transport)
        transport.writes.clear()

        self.assertEqual(controller.update("CENTER", 0.1, 0.55), Motion.FORWARD)
        self.assertEqual(controller.update("CENTER", 0.1, 0.58), Motion.TURN_RIGHT)
        self.assertEqual(
            transport.writes[-4:],
            commands_for_motion(Motion.TURN_RIGHT, 1000, 120),
        )
        controller.close()

    def test_aim_pulse_stops_and_waits_for_fresh_frame(self) -> None:
        clock = FakeClock()
        transport = MemoryTransport()
        controller = MotorController(
            MotorConfig(enabled=True), transport=transport, clock=clock,
        )
        transport.writes.clear()

        self.assertEqual(
            controller.update("RIGHT", 0.1, 1.0, observation_time=0.0),
            Motion.TURN_RIGHT,
        )
        self.assertEqual(transport.writes, commands_for_motion(Motion.TURN_RIGHT, 1000, 220))
        clock.advance(0.10)
        self.assertEqual(
            controller.update("RIGHT", 0.1, 1.0, observation_time=0.0),
            Motion.TURN_RIGHT,
        )
        self.assertEqual(len(transport.writes), 4)

        clock.advance(0.13)
        self.assertEqual(
            controller.update("RIGHT", 0.1, 1.0, observation_time=0.0),
            Motion.STOP,
        )
        self.assertEqual(transport.writes[-1], b"#255P1500T0000!")
        self.assertEqual(controller.search_status, "AIM OBSERVE")

        clock.advance(0.20)
        self.assertEqual(
            controller.update("RIGHT", 0.1, 1.0, observation_time=0.20),
            Motion.STOP,
        )
        self.assertEqual(len(transport.writes), 5)
        self.assertEqual(
            controller.update("CENTER", 0.1, 0.5, observation_time=clock.now),
            Motion.FORWARD,
        )
        self.assertEqual(transport.writes[-4:], commands_for_motion(Motion.FORWARD, 1000, 850))
        controller.close()

    def test_aim_lost_target_and_manual_takeover_stop_immediately(self) -> None:
        for action in ("LOST", "MANUAL"):
            with self.subTest(action=action):
                transport = MemoryTransport()
                controller = MotorController(
                    MotorConfig(enabled=True), transport=transport,
                )
                controller.update("LEFT", 0.1, 0.0)
                transport.writes.clear()
                if action == "LOST":
                    self.assertEqual(controller.update("LOST"), Motion.STOP)
                else:
                    self.assertEqual(controller.drive_manual(Motion.STOP, 0), Motion.STOP)
                self.assertEqual(transport.writes, [b"#255P1500T0000!"])
                controller.close()

    def test_aim_repeats_only_after_fresh_frame_and_close_ball_cancels(self) -> None:
        clock = FakeClock()
        transport = MemoryTransport()
        controller = MotorController(
            MotorConfig(enabled=True), transport=transport, clock=clock,
        )
        transport.writes.clear()
        self.assertEqual(
            controller.update("RIGHT", 0.1, 1.0, observation_time=0.0),
            Motion.TURN_RIGHT,
        )
        clock.advance(0.23)
        self.assertEqual(
            controller.update("RIGHT", 0.1, 1.0, observation_time=0.0),
            Motion.STOP,
        )
        clock.advance(0.2)
        self.assertEqual(
            controller.update("RIGHT", 0.1, 1.0, observation_time=0.1),
            Motion.STOP,
        )
        self.assertEqual(
            controller.update("RIGHT", 0.1, 1.0, observation_time=0.43),
            Motion.TURN_RIGHT,
        )
        self.assertEqual(transport.writes[-4:], commands_for_motion(Motion.TURN_RIGHT, 1000, 220))
        self.assertEqual(
            controller.update("RIGHT", 0.5, 1.0, observation_time=0.43),
            Motion.STOP,
        )
        self.assertEqual(transport.writes[-1], b"#255P1500T0000!")
        controller.close()

    def test_lost_search_waits_two_seconds_before_turning(self) -> None:
        clock = FakeClock()
        transport = MemoryTransport()
        controller = MotorController(
            MotorConfig(enabled=True),
            transport=transport,
            clock=clock,
        )
        transport.writes.clear()

        controller.update("LOST")
        clock.advance(1.99)
        controller.update("LOST")

        self.assertEqual(transport.writes, [])
        self.assertEqual(controller.search_phase, SearchPhase.WAITING)
        self.assertEqual(controller.search_status, "WAIT 0.0s")

        clock.advance(0.01)
        controller.update("LOST")

        self.assertEqual(
            transport.writes,
            commands_for_motion(Motion.TURN_LEFT, 1000, 500),
        )
        self.assertEqual(controller.search_phase, SearchPhase.SWEEP_TURN)
        self.assertEqual(controller.search_status, "SWEEP TURN 1/18")
        controller.close()

    def test_lost_search_sweeps_one_direction_for_a_full_configured_revolution(self) -> None:
        clock = FakeClock()
        transport = MemoryTransport()
        controller = MotorController(
            MotorConfig(enabled=True),
            transport=transport,
            clock=clock,
        )
        transport.writes.clear()

        controller.update("LOST")
        clock.advance(2.0)
        controller.update("LOST")

        for step in range(18):
            clock.advance(0.501)
            controller.update("LOST")
            self.assertEqual(controller.search_phase, SearchPhase.SWEEP_OBSERVE)
            self.assertEqual(controller.motion, Motion.STOP)
            clock.advance(0.801)
            controller.update("LOST")
            if step < 17:
                self.assertEqual(controller.search_phase, SearchPhase.SWEEP_TURN)
                self.assertEqual(controller.search_status, f"SWEEP TURN {step + 2}/18")

        stop_command = commands_for_motion(Motion.STOP, 0, 0)
        expected = []
        for _ in range(18):
            expected.extend(commands_for_motion(Motion.TURN_LEFT, 1000, 500))
            expected.extend(stop_command)
        self.assertEqual(transport.writes, expected)
        self.assertEqual(controller.search_phase, SearchPhase.WAITING)
        self.assertTrue(controller.search_status.startswith("WAIT "))
        controller.close()

    def test_stop_cancels_sweep_and_restarts_two_second_wait(self) -> None:
        clock = FakeClock()
        transport = MemoryTransport()
        controller = MotorController(
            MotorConfig(enabled=True), transport=transport, clock=clock,
        )
        controller.update("LOST")
        clock.advance(2.0)
        controller.update("LOST")
        transport.writes.clear()

        controller.stop()
        self.assertEqual(transport.writes, [b"#255P1500T0000!"])
        self.assertEqual(controller.search_phase, SearchPhase.IDLE)
        clock.advance(0.5)
        controller.update("LOST")
        clock.advance(1.99)
        controller.update("LOST")
        self.assertEqual(controller.search_phase, SearchPhase.WAITING)
        clock.advance(0.01)
        controller.update("LOST")
        self.assertEqual(controller.search_phase, SearchPhase.SWEEP_TURN)
        controller.close()

    def test_target_found_cancels_search_immediately(self) -> None:
        clock = FakeClock()
        transport = MemoryTransport()
        controller = MotorController(
            MotorConfig(enabled=True),
            transport=transport,
            clock=clock,
        )
        transport.writes.clear()

        controller.update("LOST")
        clock.advance(2.0)
        controller.update("LOST")
        controller.update("CENTER", area_ratio=0.10, target_x=0.50)

        expected = [
            *commands_for_motion(Motion.TURN_LEFT, 1000, 500),
            *commands_for_motion(Motion.STOP, 0, 0),
            *commands_for_motion(Motion.FORWARD, 1000, 850),
        ]
        self.assertEqual(transport.writes, expected)
        self.assertEqual(controller.search_phase, SearchPhase.IDLE)
        self.assertEqual(controller.search_status, "TRACKING")
        self.assertEqual(controller.motion, Motion.FORWARD)
        controller.close()


if __name__ == "__main__":
    unittest.main()
