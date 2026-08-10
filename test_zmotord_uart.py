from __future__ import annotations

import unittest

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
    def test_default_speed_matches_vehicle_document(self) -> None:
        self.assertEqual(MotorConfig().min_speed_delta, 200)
        self.assertEqual(MotorConfig().speed_delta, 300)
        self.assertEqual(MotorConfig().min_command_time_ms, 300)
        self.assertEqual(MotorConfig().command_time_ms, 1000)
        self.assertEqual(MotorConfig().close_area_ratio, 0.44)
        self.assertEqual(MotorConfig().lost_search_delay, 10.0)
        self.assertEqual(MotorConfig().search_speed_delta, 250)
        self.assertEqual(MotorConfig().search_turn_time_ms, 350)
        self.assertEqual(MotorConfig().search_steps_per_side, 3)
        self.assertEqual(MotorConfig().search_observe_seconds, 0.50)

    def test_configured_forward_pwm(self) -> None:
        self.assertEqual(
            commands_for_motion(Motion.FORWARD, 300, 1000),
            [
                b"#001P1800T1000!",
                b"#002P1200T1000!",
                b"#003P1800T1000!",
                b"#004P1200T1000!",
            ],
        )

    def test_maximum_forward_pwm(self) -> None:
        self.assertEqual(
            commands_for_motion(Motion.FORWARD, 1000, 1000),
            [
                b"#001P2500T1000!",
                b"#002P0500T1000!",
                b"#003P2500T1000!",
                b"#004P0500T1000!",
            ],
        )

    def test_command_format(self) -> None:
        self.assertEqual(
            format_motor_command(1, 1680, 1000),
            b"#001P1680T1000!",
        )

    def test_forward_polarity_matches_vehicle_document(self) -> None:
        self.assertEqual(
            commands_for_motion(Motion.FORWARD, 180, 1000),
            [
                b"#001P1680T1000!",
                b"#002P1320T1000!",
                b"#003P1680T1000!",
                b"#004P1320T1000!",
            ],
        )

    def test_turn_commands_match_vehicle_document(self) -> None:
        self.assertEqual(
            commands_for_motion(Motion.TURN_LEFT, 180, 1000),
            [
                b"#001P1320T1000!",
                b"#002P1320T1000!",
                b"#003P1320T1000!",
                b"#004P1320T1000!",
            ],
        )
        self.assertEqual(
            commands_for_motion(Motion.TURN_RIGHT, 180, 1000),
            [
                b"#001P1680T1000!",
                b"#002P1680T1000!",
                b"#003P1680T1000!",
                b"#004P1680T1000!",
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

    def test_near_ball_uses_at_least_1700_and_1300_pwm(self) -> None:
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
                b"#001P1700T0300!",
                b"#002P1300T0300!",
                b"#003P1700T0300!",
                b"#004P1300T0300!",
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
            commands_for_motion(Motion.FORWARD, 300, 1000),
        )
        controller.close()

    def test_turn_strength_grows_toward_image_edge(self) -> None:
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
            commands_for_motion(Motion.TURN_RIGHT, 200, 300),
        )
        self.assertEqual(
            edge_transport.writes,
            commands_for_motion(Motion.TURN_RIGHT, 300, 1000),
        )
        near_controller.close()
        edge_controller.close()

    def test_lost_search_waits_ten_seconds_before_turning(self) -> None:
        clock = FakeClock()
        transport = MemoryTransport()
        controller = MotorController(
            MotorConfig(enabled=True),
            transport=transport,
            clock=clock,
        )
        transport.writes.clear()

        controller.update("LOST")
        clock.advance(9.99)
        controller.update("LOST")

        self.assertEqual(transport.writes, [])
        self.assertEqual(controller.search_phase, SearchPhase.WAITING)

        clock.advance(0.01)
        controller.update("LOST")

        self.assertEqual(
            transport.writes,
            commands_for_motion(Motion.TURN_LEFT, 250, 350),
        )
        self.assertEqual(controller.search_phase, SearchPhase.LEFT_SCAN)
        self.assertEqual(controller.search_status, "LEFT SCAN 1/3")
        controller.close()

    def test_lost_search_turns_back_before_opposite_scan(self) -> None:
        clock = FakeClock()
        transport = MemoryTransport()
        controller = MotorController(
            MotorConfig(enabled=True),
            transport=transport,
            clock=clock,
        )
        transport.writes.clear()

        controller.update("LOST")
        clock.advance(10.0)
        controller.update("LOST")

        for _ in range(3):
            clock.advance(0.351)
            controller.update("LOST")
            clock.advance(0.501)
            controller.update("LOST")

        for step in range(3):
            clock.advance(0.351)
            controller.update("LOST")
            if step < 2:
                clock.advance(0.151)
                controller.update("LOST")

        clock.advance(0.301)
        controller.update("LOST")

        for _ in range(3):
            clock.advance(0.351)
            controller.update("LOST")
            clock.advance(0.501)
            controller.update("LOST")

        for step in range(3):
            clock.advance(0.351)
            controller.update("LOST")
            if step < 2:
                clock.advance(0.151)
                controller.update("LOST")

        stop_command = commands_for_motion(Motion.STOP, 0, 0)
        expected = []
        for motion in (
            Motion.TURN_LEFT,
            Motion.TURN_RIGHT,
            Motion.TURN_RIGHT,
            Motion.TURN_LEFT,
        ):
            for _ in range(3):
                expected.extend(commands_for_motion(motion, 250, 350))
                expected.extend(stop_command)
        self.assertEqual(transport.writes, expected)
        self.assertEqual(controller.search_phase, SearchPhase.WAITING)
        self.assertTrue(controller.search_status.startswith("WAIT "))
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
        clock.advance(10.0)
        controller.update("LOST")
        controller.update("CENTER", area_ratio=0.10, target_x=0.50)

        expected = [
            *commands_for_motion(Motion.TURN_LEFT, 250, 350),
            *commands_for_motion(Motion.STOP, 0, 0),
            *commands_for_motion(Motion.FORWARD, 280, 850),
        ]
        self.assertEqual(transport.writes, expected)
        self.assertEqual(controller.search_phase, SearchPhase.IDLE)
        self.assertEqual(controller.search_status, "TRACKING")
        self.assertEqual(controller.motion, Motion.FORWARD)
        controller.close()


if __name__ == "__main__":
    unittest.main()
