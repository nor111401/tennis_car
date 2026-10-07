"""The visible 80%-bottom trigger commits one bounded 3.0-second pickup."""
from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from zmotord_uart import MotorConfig, MotorController, Motion, SearchPhase, commands_for_motion
from test_zmotord_uart import FakeClock, MemoryTransport
from test_robot_gateway import envelope, reply_reason
from robot_gateway.core import GatewayMode, GatewayMotion, RobotGatewayCore, TaskMode
from robot_gateway.runtime import RobotRuntime, RuntimeSettings, TrackingObservation


class CommittedPickupTests(unittest.TestCase):
    def create(self, config=None):
        clock = FakeClock()
        transport = MemoryTransport()
        controller = MotorController(config or MotorConfig(enabled=True), transport, clock)
        transport.writes.clear()
        return controller, clock, transport

    def start(self, controller, clock, x=0.5, bottom=0.80):
        return controller.update("CENTER", 0.05, x, bottom, observation_time=clock.now)

    def test_exact_eighty_percent_and_fifteen_percent_boundaries_start_now(self):
        for x in (0.35, 0.40, 0.5, 0.60, 0.65):
            with self.subTest(x=x):
                controller, clock, transport = self.create()
                self.assertEqual(self.start(controller, clock, x), Motion.FORWARD)
                self.assertTrue(controller.pickup_active)
                self.assertEqual(controller._bottom_exit_deadline, 3.0)
                self.assertEqual(controller._pickup_open_deadline, 3.0)
                self.assertEqual(transport.writes, commands_for_motion(Motion.FORWARD, 1000, 300))

    def test_below_threshold_off_center_or_missing_geometry_cannot_start(self):
        for x, bottom in ((0.5, 0.799), (0.349, 0.80), (0.651, 0.80),
                          (None, 0.9), (0.5, None)):
            with self.subTest(x=x, bottom=bottom):
                controller, clock, _ = self.create()
                self.start(controller, clock, x, bottom)
                self.assertFalse(controller.pickup_active)

    def test_far_small_error_still_turns_but_near_small_error_collects(self):
        for x, bottom, expected in ((0.40, 0.79, Motion.TURN_LEFT),
                                    (0.60, 0.79, Motion.TURN_RIGHT),
                                    (0.40, 0.80, Motion.FORWARD),
                                    (0.60, 0.80, Motion.FORWARD)):
            controller, clock, _ = self.create()
            self.assertEqual(self.start(controller, clock, x, bottom), expected)
            self.assertEqual(controller.pickup_active, expected is Motion.FORWARD)

    def test_empty_rejected_verifying_and_reacquired_ball_do_not_cancel_or_extend(self):
        controller, clock, _ = self.create()
        self.start(controller, clock)
        for args, kwargs in (
            (("LOST",), {"allow_bottom_exit": True}),
            (("LOST",), {"allow_bottom_exit": False}),
            (("LOST", 0.01), {}),
            (("RIGHT", 0.2, 0.95, 0.90), {}),
            (("LEFT", 0.2, 0.1, 0.50), {}),
            (("CENTER", 1.0, 0.5), {}),
            (("CENTER", 0.01, 0.5, 0.40), {}),
        ):
            clock.advance(0.4)
            self.assertEqual(controller.update(*args, **kwargs), Motion.FORWARD)
            self.assertTrue(controller.pickup_active)
            self.assertEqual(controller._bottom_exit_deadline, 3.0)
            self.assertEqual(controller._pickup_open_deadline, 3.0)
            self.assertIsNone(controller._aim_turn_deadline)
            self.assertEqual(controller.search_phase, SearchPhase.IDLE)

    def test_full_three_seconds_and_remaining_uart_pulse_are_bounded(self):
        controller, clock, transport = self.create()
        self.start(controller, clock)
        clock.now = 2.90
        self.assertEqual(controller.update("LOST"), Motion.FORWARD)
        self.assertGreater(controller.active_command_time_ms, 0)
        self.assertLessEqual(controller.active_command_time_ms, 100)
        self.assertTrue(controller.pickup_active)
        clock.now = 3.0
        self.assertEqual(controller.update("RIGHT", 0.1, 0.9, 0.9), Motion.STOP)
        self.assertFalse(controller.pickup_active)
        self.assertFalse(controller.bottom_exit_active)
        self.assertEqual(transport.writes[-1], b"#255P1500T0000!")
        self.assertEqual(controller.search_status, "PICKUP COMPLETE")

    def test_late_motor_tick_stops_without_restarting(self):
        controller, clock, _ = self.create()
        self.start(controller, clock)
        clock.now = 8.0
        self.assertEqual(self.start(controller, clock), Motion.STOP)
        self.assertFalse(controller.pickup_active)
        self.assertEqual(self.start(controller, clock), Motion.STOP)

    def test_same_near_ball_does_not_repeat_until_new_upper_frame(self):
        controller, clock, _ = self.create()
        self.start(controller, clock)
        clock.now = 3.0
        controller.update("LOST")
        for _ in range(4):
            clock.advance(0.1)
            self.assertEqual(self.start(controller, clock), Motion.STOP)
        # An upper frame captured before completion cannot rearm the window.
        controller.update("CENTER", 0.05, 0.5, 0.6, observation_time=2.5)
        self.assertTrue(controller._pickup_consumed)
        self.assertEqual(self.start(controller, clock), Motion.STOP)
        controller.update("CENTER", 0.05, 0.5, 0.6, observation_time=clock.now)
        self.assertFalse(controller._pickup_consumed)
        clock.advance(0.1)
        self.assertEqual(self.start(controller, clock), Motion.FORWARD)
        self.assertEqual(controller._bottom_exit_deadline, clock.now + 3.0)

    def test_empty_after_completion_waits_two_seconds_before_search(self):
        controller, clock, _ = self.create()
        self.start(controller, clock)
        clock.now = 3.0
        controller.update("LOST")
        self.assertEqual(controller.update("LOST"), Motion.STOP)
        clock.advance(1.99)
        self.assertEqual(controller.update("LOST"), Motion.STOP)
        clock.advance(0.02)
        self.assertEqual(controller.update("LOST"), Motion.TURN_LEFT)
        self.assertFalse(controller.pickup_active)

    def test_external_stop_close_manual_and_obstacle_cancel_and_clear_window(self):
        for action in ("stop", "close", "manual", "obstacle"):
            with self.subTest(action=action):
                controller, clock, transport = self.create()
                self.start(controller, clock)
                clock.advance(1)
                transport.writes.clear()
                if action == "stop":
                    controller.stop(force=True)
                elif action == "close":
                    controller.close()
                elif action == "manual":
                    controller.drive_manual(Motion.REVERSE, 1.0)
                else:
                    controller.drive_obstacle_turn()
                self.assertEqual(transport.writes[0], b"#255P1500T0000!")
                self.assertFalse(controller.pickup_active)
                self.assertFalse(controller.bottom_exit_active)
                self.assertFalse(controller._pickup_consumed)

    def test_too_close_before_entry_stops_but_during_window_is_visual_only(self):
        controller, clock, _ = self.create()
        self.assertEqual(controller.update("CENTER", 0.44, 0.5, 0.9), Motion.STOP)
        self.assertFalse(controller.pickup_active)
        self.start(controller, clock)
        self.assertEqual(controller.update("CENTER", 1.0, 0.5), Motion.FORWARD)
        self.assertTrue(controller.pickup_active)

    def test_turn_must_settle_and_receive_fresh_frame_before_entry(self):
        controller, clock, _ = self.create()
        controller.update("RIGHT", 0.1, 0.8, 0.6, observation_time=clock.now)
        clock.advance(0.05)
        self.assertEqual(controller.update("CENTER", 0.1, 0.6, 0.8,
                                          observation_time=0), Motion.TURN_RIGHT)
        self.assertEqual(controller.update("CENTER", 0.1, 0.6, 0.8,
                                          observation_time=clock.now), Motion.STOP)
        self.assertFalse(controller.pickup_active)
        clock.advance(0.16)
        self.assertEqual(controller.update("CENTER", 0.1, 0.6, 0.8,
                                          observation_time=0.05), Motion.STOP)
        self.assertFalse(controller.pickup_active)
        self.assertEqual(controller.update("CENTER", 0.1, 0.6, 0.8,
                                          observation_time=clock.now), Motion.FORWARD)
        self.assertTrue(controller.pickup_active)

    def test_disabled_pickup_does_not_start_on_visible_or_empty(self):
        controller, clock, _ = self.create(MotorConfig(bottom_exit_forward_seconds=0))
        self.start(controller, clock)
        self.assertFalse(controller.pickup_active)
        self.assertEqual(controller.update("LOST", allow_bottom_exit=True), Motion.STOP)

    def test_drive_duration_range_and_environment_override(self):
        for duration in (-0.1, 5.1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                MotorConfig(bottom_exit_forward_seconds=duration).validate()
        with patch.dict("os.environ", {"TENNIS_BOTTOM_EXIT_FORWARD_SECONDS": "4",
                                      "TENNIS_PICKUP_OPEN_SECONDS": "5"}, clear=True):
            config = MotorConfig.from_environment()
        self.assertEqual(config.bottom_exit_forward_seconds, 4)
        self.assertEqual(config.pickup_open_seconds, 5)

    def test_shorter_configured_drive_holds_collector_without_visual_restart(self):
        controller, clock, _ = self.create(MotorConfig(bottom_exit_forward_seconds=2))
        self.start(controller, clock)
        clock.now = 2.0
        self.assertEqual(controller.update("RIGHT", 0.1, 0.9, 0.9), Motion.STOP)
        self.assertTrue(controller.pickup_active)
        clock.now = 3.0
        controller.update("LOST")
        self.assertFalse(controller.pickup_active)


class CommittedPickupRuntimeTests(unittest.TestCase):
    def test_gateway_ignores_visual_changes_but_safety_wins(self):
        for case in ("empty", "reject", "too_close", "off_center", "camera_wait",
                     "invalid_camera", "paused", "emergency", "manual", "obstacle"):
            with self.subTest(case=case):
                clock = FakeClock()
                clock.now = 100.0
                core = RobotGatewayCore(clock=clock)
                runtime = RobotRuntime(core, RuntimeSettings(
                    motor_output_enabled=True, mode_gpio_enabled=True, boot_mode=GatewayMode.AUTO,
                ))
                core.state.camera_online = True
                core.open_session("test", "test", 1)
                core.handle(envelope("test", 2, "control.request", {"terminalName": "test"}))
                lease_id = core.lease.lease_id
                controller = MotorController(MotorConfig(enabled=True), MemoryTransport(), clock)
                records = []
                runtime._set_observation(TrackingObservation(
                    position="CENTER", area_ratio=0.05, target_x=0.5, target_bottom=0.8,
                    captured_at=clock.now, valid=True,
                ))
                def step(_):
                    records.append((core.control_snapshot(), controller.pickup_active))
                    if len(records) == 1:
                        clock.advance(0.1)
                        runtime._set_observation(TrackingObservation(
                            position="RIGHT" if case == "off_center" else "LOST",
                            area_ratio=1.0 if case == "too_close" else 0.01,
                            target_x=0.9 if case == "off_center" else None,
                            target_bottom=0.9 if case == "off_center" else None,
                            bottom_exit_loss=case == "empty", valid=case != "invalid_camera",
                            captured_at=clock.now - (1.0 if case == "camera_wait" else 0),
                        ))
                        if case in ("paused", "manual"):
                            result = core.handle(envelope("test", 3, "mode.set", {
                                "mode": "PAUSED" if case == "paused" else "MANUAL",
                                "leaseId": lease_id,
                            }))
                            self.assertIsNone(reply_reason(result))
                        elif case == "emergency":
                            core.handle(envelope("test", 3, "safety.estop", {"active": True}))
                        elif case == "obstacle":
                            runtime._obstacle_sampler = Mock()
                            runtime._obstacle_guard.step = Mock(return_value=("STOP", "OBSTACLE STOP"))
                    else:
                        runtime._stop_event.set()
                with patch("zmotord_uart.MotorController.from_environment", return_value=controller), \
                     patch("robot_gateway.runtime.time.monotonic", side_effect=clock), \
                     patch.object(runtime._stop_event, "wait", side_effect=step):
                    runtime._motor_loop()
                self.assertEqual(len(records), 2)
                self.assertEqual(records[0][0]["task_mode"], TaskMode.PICKUP)
                keep = case in ("empty", "reject", "too_close", "off_center")
                self.assertEqual(records[1][1], keep)
                self.assertEqual(records[1][0]["motion"],
                                 GatewayMotion.FORWARD if keep else GatewayMotion.STOP)
                self.assertEqual(records[1][0]["task_mode"],
                                 TaskMode.PICKUP if keep else TaskMode.TRACKING)
                self.assertIsNone(core.state.runtime_error)
                self.assertFalse(controller.pickup_active)

    def test_gateway_too_close_without_window_does_not_search(self):
        core = RobotGatewayCore()
        runtime = RobotRuntime(core, RuntimeSettings(boot_mode=GatewayMode.AUTO))
        controller = MotorController(MotorConfig(), clock=lambda: 100.0)
        runtime._set_observation(TrackingObservation(area_ratio=1.0, captured_at=100.0, valid=True))
        def finish(_):
            self.assertEqual(core.state.motion, GatewayMotion.STOP)
            self.assertEqual(core.state.search_phase, "TOO_CLOSE")
            self.assertIsNone(controller._lost_since)
            runtime._stop_event.set()
        with patch("zmotord_uart.MotorController.from_environment", return_value=controller), \
             patch("robot_gateway.runtime.time.monotonic", return_value=100.0), \
             patch.object(runtime._stop_event, "wait", side_effect=finish):
            runtime._motor_loop()
        self.assertIsNone(core.state.runtime_error)


class CommittedPickupVisionTests(unittest.TestCase):
    def test_confirmed_visible_trigger_then_half_ball_and_empty_keep_original_deadline(self):
        import cv2
        import numpy as np
        from tennis_candidate_filter import CandidateFilterConfig, TargetConfirmation, MultiBallTracker
        from tennis_candidate_filter import find_color_candidate_boxes
        from tennis_ball_rpi import process_bounding_boxes
        clock = FakeClock()
        controller = MotorController(MotorConfig(), clock=clock)
        confirmation = TargetConfirmation(3, 0.20)
        tracker = MultiBallTracker(smoothing_alpha=1.0)
        def observe(y):
            image = np.zeros((200, 200, 3), dtype=np.uint8)
            if y is not None:
                cv2.circle(image, (100, y), 24, (210, 255, 40), -1)
            boxes = find_color_candidate_boxes(image, CandidateFilterConfig(), 100)
            _, position, area, x, details = process_bounding_boxes(
                {"result": {"bounding_boxes": boxes}}, image, 100, 100,
                confirmation, tracker, log_events=False,
            )
            bottom = min(1.0, details["ball_y"] + details["ball_height"] / 2) if details["detected"] else None
            motion = controller.update(position, area, x, bottom, details["bottom_exit_loss"], clock.now)
            return motion, details
        for i in range(3):
            _, details = observe(174)
            self.assertEqual(controller.pickup_active, i == 2)
            clock.advance(0.1)
        deadline = controller._bottom_exit_deadline
        motion, details = observe(208)
        self.assertIn("shape_aspect", details["vision_status"])
        self.assertFalse(details["bottom_exit_loss"])
        self.assertEqual(motion, Motion.FORWARD)
        clock.advance(0.1)
        motion, details = observe(None)
        self.assertEqual(details["vision_status"], "EMPTY")
        self.assertEqual(motion, Motion.FORWARD)
        self.assertEqual(controller._bottom_exit_deadline, deadline)
        clock.now = deadline
        self.assertEqual(observe(None)[0], Motion.STOP)
        self.assertFalse(controller.pickup_active)


if __name__ == "__main__":
    unittest.main()
