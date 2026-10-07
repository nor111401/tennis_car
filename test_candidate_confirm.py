"""Bounded provisional-target stops, without hardware or physical movement."""
from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from zmotord_uart import MotorConfig, MotorController, Motion, commands_for_motion
from test_zmotord_uart import FakeClock, MemoryTransport
from test_robot_gateway import envelope
from robot_gateway.core import GatewayMode, GatewayMotion, RobotGatewayCore
from robot_gateway.runtime import RobotRuntime, RuntimeSettings, TrackingObservation


class CandidateConfirmationTests(unittest.TestCase):
    def create(self, **config):
        clock = FakeClock()
        transport = MemoryTransport()
        controller = MotorController(MotorConfig(enabled=True, **config), transport, clock)
        controller.update("LOST")
        clock.advance(2)
        controller.update("LOST")
        transport.writes.clear()
        return controller, clock, transport

    def candidate(self, controller, clock, visible=True):
        return controller.update("LOST", observation_time=clock.now,
                                 candidate_visible=visible)

    def test_candidate_interrupts_search_with_stop_not_pickup(self):
        controller, clock, transport = self.create()
        self.assertEqual(controller.motion, Motion.TURN_LEFT)
        self.assertEqual(self.candidate(controller, clock), Motion.STOP)
        self.assertEqual(transport.writes, commands_for_motion(Motion.STOP, 0, 0))
        self.assertEqual(controller.search_status, "TARGET VERIFY 1.0s")
        self.assertFalse(controller.pickup_active)

    def test_repeated_frames_and_missing_frames_do_not_extend_deadline(self):
        controller, clock, _ = self.create()
        self.candidate(controller, clock)
        deadline = controller._candidate_deadline
        for visible in (True, False, True, False):
            clock.advance(0.2)
            self.assertEqual(self.candidate(controller, clock, visible), Motion.STOP)
            self.assertEqual(controller._candidate_deadline, deadline)
        clock.now = deadline
        self.assertEqual(self.candidate(controller, clock), Motion.TURN_LEFT)
        self.assertIsNone(controller._candidate_deadline)
        self.assertEqual(controller._search_step, 2)

    def test_confirmed_target_waits_for_settling_and_a_fresh_frame(self):
        controller, clock, _ = self.create()
        self.candidate(controller, clock)
        def confirmed(stamp):
            return controller.update("CENTER", 0.05, 0.5, 0.6,
                                     observation_time=stamp, candidate_visible=True)
        clock.advance(0.1)
        self.assertEqual(confirmed(clock.now), Motion.STOP)
        clock.advance(0.1)
        self.assertEqual(confirmed(clock.now - 0.1), Motion.STOP)
        self.assertEqual(confirmed(clock.now), Motion.FORWARD)
        self.assertFalse(controller.pickup_active)
        self.assertEqual(controller.search_status, "TRACKING")

    def test_same_unconfirmed_candidate_cannot_park_each_search_step(self):
        controller, clock, _ = self.create()
        self.candidate(controller, clock)
        clock.advance(1)
        self.candidate(controller, clock)
        for _ in range(30):
            clock.advance(0.1)
            self.candidate(controller, clock)
            self.assertIsNone(controller._candidate_deadline)
        self.assertGreaterEqual(controller._search_step, 3)
        self.assertFalse(controller.pickup_active)
        # Genuine confirmation is still accepted while provisional stops are blocked.
        self.assertEqual(controller.update("CENTER", 0.05, 0.5, 0.6,
                                           observation_time=clock.now), Motion.FORWARD)

    def test_retry_needs_fresh_absence_after_search_cooldown(self):
        controller, clock, _ = self.create()
        self.candidate(controller, clock)
        clock.advance(1)
        self.candidate(controller, clock)
        retry_after = controller._candidate_retry_after
        clock.now = retry_after + 0.1
        controller.update("LOST", observation_time=retry_after - 0.1)
        self.assertTrue(controller._candidate_blocked)
        self.candidate(controller, clock, visible=False)
        self.assertFalse(controller._candidate_blocked)
        self.assertEqual(self.candidate(controller, clock), Motion.STOP)
        self.assertIsNotNone(controller._candidate_deadline)

    def test_stop_manual_and_obstacle_clear_confirmation(self):
        for action in (lambda c: c.stop(),
                       lambda c: c.drive_manual(Motion.STOP, 0),
                       lambda c: c.drive_obstacle_turn()):
            controller, clock, _ = self.create()
            self.candidate(controller, clock)
            action(controller)
            self.assertIsNone(controller._candidate_deadline)
            self.assertFalse(controller._candidate_blocked)
            self.assertFalse(controller.pickup_active)

    def test_too_close_is_stop_and_collection_keeps_three_second_priority(self):
        controller, clock, _ = self.create()
        self.candidate(controller, clock)
        self.assertEqual(controller.update("CENTER", 1.0, 0.5), Motion.STOP)
        self.assertIsNone(controller._candidate_deadline)
        self.assertFalse(controller.pickup_active)
        controller.update("CENTER", 0.05, 0.5, 0.80, observation_time=clock.now)
        deadline = clock.now + 3
        clock.advance(0.1)
        self.assertEqual(self.candidate(controller, clock), Motion.FORWARD)
        self.assertEqual(controller._bottom_exit_deadline, deadline)
        self.assertIsNone(controller._candidate_deadline)
        clock.now = deadline
        self.assertEqual(self.candidate(controller, clock), Motion.STOP)
        self.assertFalse(controller.pickup_active)

    def test_disabled_search_does_not_create_confirmation_wait(self):
        controller, clock, _ = self.create(lost_search_enabled=False)
        self.assertEqual(self.candidate(controller, clock), Motion.STOP)
        self.assertIsNone(controller._candidate_deadline)


class CandidateConfirmationRuntimeTests(unittest.TestCase):
    def test_gateway_passes_candidate_and_higher_priority_safety_clears_it(self):
        for guard in ("paused", "emergency", "stale", "invalid", "obstacle"):
            with self.subTest(guard=guard):
                clock = FakeClock()
                clock.now = 100
                controller = MotorController(MotorConfig(enabled=True), MemoryTransport(), clock)
                controller.update("LOST")
                clock.advance(2)
                controller.update("LOST")
                core = RobotGatewayCore(clock=clock)
                runtime = RobotRuntime(core, RuntimeSettings(boot_mode=GatewayMode.AUTO))
                core.state.camera_online = True
                core.open_session("test", "test", 1)
                core.handle(envelope("test", 2, "control.request", {"terminalName": "test"}))
                runtime._set_observation(TrackingObservation(
                    captured_at=clock.now, valid=True, candidate_visible=True))
                records = []
                def step(_):
                    records.append(controller._candidate_deadline)
                    self.assertEqual(core.state.motion, GatewayMotion.STOP)
                    if len(records) == 1:
                        self.assertTrue(core.state.search_phase.startswith("TARGET VERIFY"))
                        clock.advance(0.1)
                        if guard == "paused":
                            core.handle(envelope("test", 3, "mode.set", {
                                "mode": "PAUSED", "leaseId": core.lease.lease_id}))
                        elif guard == "emergency":
                            core.handle(envelope("test", 3, "safety.estop", {"active": True}))
                        elif guard in ("stale", "invalid"):
                            runtime._set_observation(TrackingObservation(
                                captured_at=clock.now - (1 if guard == "stale" else 0),
                                valid=guard != "invalid", candidate_visible=True))
                        else:
                            runtime._obstacle_sampler = Mock()
                            runtime._obstacle_guard.step = Mock(return_value=("STOP", "OBSTACLE STOP"))
                    else:
                        runtime._stop_event.set()
                with patch("zmotord_uart.MotorController.from_environment", return_value=controller), \
                     patch("robot_gateway.runtime.time.monotonic", side_effect=clock), \
                     patch.object(runtime._stop_event, "wait", side_effect=step):
                    runtime._motor_loop()
                self.assertEqual(len(records), 2)
                self.assertIsNotNone(records[0])
                self.assertIsNone(records[1])
                self.assertIsNone(core.state.runtime_error)


class CandidateConfirmationVisionTests(unittest.TestCase):
    def test_pending_is_yellow_then_confirmed_red_with_unchanged_three_frames(self):
        import cv2
        import numpy as np
        from tennis_candidate_filter import CandidateFilterConfig, TargetConfirmation, MultiBallTracker
        from tennis_candidate_filter import find_color_candidate_boxes
        from tennis_ball_rpi import process_bounding_boxes
        image = np.zeros((200, 200, 3), dtype=np.uint8)
        cv2.circle(image, (100, 130), 24, (210, 255, 40), -1)
        boxes = find_color_candidate_boxes(image, CandidateFilterConfig(), 100)
        tracker, confirmation = MultiBallTracker(smoothing_alpha=1.0), TargetConfirmation(3, 0.20)
        clock = FakeClock()
        controller = MotorController(MotorConfig(), clock=clock)
        for i in range(3):
            display, position, area, x, details = process_bounding_boxes(
                {"result": {"bounding_boxes": boxes}}, image, 100, 100,
                confirmation, tracker, log_events=False)
            self.assertTrue(details["candidate_visible"])
            self.assertEqual(details["detected"], i == 2)
            self.assertEqual(position == "LOST", i < 2)
            self.assertEqual(x is None, i < 2)
            bottom = min(1.0, details["ball_y"] + details["ball_height"] / 2) if details["detected"] else None
            motion = controller.update(position, area, x, bottom,
                                       observation_time=clock.now,
                                       candidate_visible=details["candidate_visible"])
            self.assertEqual(motion, Motion.FORWARD if i == 2 else Motion.STOP)
            self.assertFalse(controller.pickup_active)
            target = tracker.current_target()
            pixel = display[int(target.center_y * display.shape[0]),
                            int(target.center_x * display.shape[1])]
            self.assertTupleEqual(tuple(pixel), (0, 0, 255) if i == 2 else (0, 255, 255))
            clock.advance(0.1)
        _, _, _, _, details = process_bounding_boxes(
            {"result": {"bounding_boxes": []}}, np.zeros_like(image), 100, 100,
            confirmation, tracker, log_events=False)
        self.assertFalse(details["candidate_visible"])
        self.assertFalse(details["detected"])

    def test_rejected_empty_and_too_close_are_not_candidates(self):
        import numpy as np
        from tennis_candidate_filter import TargetConfirmation, MultiBallTracker
        from tennis_ball_rpi import process_bounding_boxes
        from test_tennis_candidate_filter import DETECTION
        for boxes, close in (([], False), ([DETECTION], False), ([], True)):
            with patch("tennis_ball_rpi.tennis_color_coverage", return_value=0.8 if close else 0):
                *_, details = process_bounding_boxes(
                    {"result": {"bounding_boxes": boxes}},
                    np.zeros((200, 200, 3), dtype=np.uint8), 100, 100,
                    TargetConfirmation(3, 0.20), MultiBallTracker(), log_events=False)
            self.assertFalse(details["candidate_visible"])
            self.assertFalse(details["detected"])


if __name__ == "__main__":
    unittest.main()
