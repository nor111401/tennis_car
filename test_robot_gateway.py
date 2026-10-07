from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from robot_gateway.core import (
    GatewayMode,
    GatewayMotion,
    RobotGatewayCore,
    TaskMode,
)
from robot_gateway.protocol import ClientEnvelope, ProtocolError
from robot_gateway.runtime import LatestJpegFrame, RuntimeSettings


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def envelope(
    terminal_id: str,
    sequence: int,
    message_type: str,
    payload: dict | None = None,
) -> ClientEnvelope:
    return ClientEnvelope(
        version=1,
        type=message_type,
        sequence=sequence,
        terminal_id=terminal_id,
        sent_at=1_000,
        payload=payload or {},
    )


def reply_reason(result) -> str | None:
    for message_type, payload in result.replies:
        if message_type == "command.rejected":
            return payload["reason"]
    return None


class ProtocolTests(unittest.TestCase):
    def test_valid_json_envelope_is_parsed(self) -> None:
        parsed = ClientEnvelope.parse(json.dumps({
            "version": 1,
            "type": "session.hello",
            "sequence": 1,
            "terminalId": "windows-1",
            "sentAt": 1234,
            "payload": {},
        }))
        self.assertEqual(parsed.terminal_id, "windows-1")
        self.assertEqual(parsed.sequence, 1)

    def test_invalid_protocol_version_is_rejected(self) -> None:
        with self.assertRaises(ProtocolError):
            ClientEnvelope.parse({
                "version": 2,
                "type": "session.hello",
                "sequence": 1,
                "terminalId": "windows-1",
                "sentAt": 1234,
                "payload": {},
            })


class GatewayCoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FakeClock()
        self.core = RobotGatewayCore(clock=self.clock)
        self.core.open_session("windows-1", "Windows终端", 1)

    def request_control(self, sequence: int = 2) -> str:
        result = self.core.handle(envelope(
            "windows-1",
            sequence,
            "control.request",
            {"terminalName": "Windows终端"},
        ))
        self.assertIsNone(reply_reason(result))
        self.assertIsNotNone(self.core.lease)
        return self.core.lease.lease_id

    def test_manual_drive_requires_lease_and_mode(self) -> None:
        rejected = self.core.handle(envelope(
            "windows-1",
            2,
            "control.command",
            {"direction": "FORWARD", "speed": 0.5},
        ))
        self.assertEqual(reply_reason(rejected), "CONTROL_LEASE_REQUIRED")

        lease_id = self.request_control(3)
        self.core.handle(envelope(
            "windows-1",
            4,
            "mode.set",
            {"mode": "MANUAL", "leaseId": lease_id},
        ))
        accepted = self.core.handle(envelope(
            "windows-1",
            5,
            "control.command",
            {
                "direction": "FORWARD",
                "speed": 0.6,
                "pressed": True,
                "leaseId": lease_id,
            },
        ))
        self.assertIsNone(reply_reason(accepted))
        self.assertEqual(self.core.state.mode, GatewayMode.MANUAL)
        self.assertEqual(self.core.state.motion, GatewayMotion.FORWARD)
        self.assertEqual(self.core.state.manual_speed, 0.6)

    def test_mode_transition_forces_stop(self) -> None:
        lease_id = self.request_control()
        self.core.handle(envelope(
            "windows-1", 3, "mode.set", {"mode": "MANUAL", "leaseId": lease_id}
        ))
        self.core.handle(envelope(
            "windows-1",
            4,
            "control.command",
            {
                "direction": "TURN_LEFT",
                "speed": 0.5,
                "leaseId": lease_id,
            },
        ))
        result = self.core.handle(envelope(
            "windows-1", 5, "mode.set", {"mode": "AUTO", "leaseId": lease_id}
        ))
        self.assertTrue(result.state_changed)
        self.assertEqual(self.core.state.mode, GatewayMode.AUTO)
        self.assertEqual(self.core.state.motion, GatewayMotion.STOP)

    def test_second_terminal_cannot_take_control(self) -> None:
        self.request_control()
        self.core.open_session("android-1", "安卓终端", 1)
        denied = self.core.handle(envelope(
            "android-1", 2, "control.request", {"terminalName": "安卓终端"}
        ))
        self.assertEqual(denied.replies[0][0], "control.denied")
        self.assertEqual(self.core.lease.terminal_id, "windows-1")

    def test_stale_sequence_is_rejected(self) -> None:
        self.request_control(2)
        stale = self.core.handle(envelope("windows-1", 2, "control.request"))
        self.assertEqual(reply_reason(stale), "STALE_SEQUENCE")

    def test_heartbeat_timeout_stops_and_enters_manual_lost(self) -> None:
        lease_id = self.request_control()
        self.core.handle(envelope(
            "windows-1", 3, "mode.set", {"mode": "MANUAL", "leaseId": lease_id}
        ))
        self.core.handle(envelope(
            "windows-1",
            4,
            "control.command",
            {
                "direction": "FORWARD",
                "speed": 0.8,
                "leaseId": lease_id,
            },
        ))
        self.clock.advance(0.61)
        self.assertTrue(self.core.tick())
        self.assertIsNone(self.core.lease)
        self.assertEqual(self.core.state.mode, GatewayMode.MANUAL_LOST)
        self.assertEqual(self.core.state.motion, GatewayMotion.STOP)

    def test_disconnect_in_manual_stops_without_auto_resume(self) -> None:
        lease_id = self.request_control()
        self.core.handle(envelope(
            "windows-1", 3, "mode.set", {"mode": "MANUAL", "leaseId": lease_id}
        ))
        self.assertTrue(self.core.disconnect("windows-1"))
        self.assertEqual(self.core.state.mode, GatewayMode.MANUAL_LOST)
        self.assertEqual(self.core.state.motion, GatewayMotion.STOP)

    def test_emergency_stop_is_latched_and_reset_requires_controller(self) -> None:
        activated = self.core.handle(envelope(
            "windows-1", 2, "safety.estop", {"active": True}
        ))
        self.assertTrue(activated.state_changed)
        self.assertTrue(self.core.state.emergency_stop)
        self.assertEqual(self.core.state.mode, GatewayMode.EMERGENCY_STOP)

        denied = self.core.handle(envelope(
            "windows-1", 3, "safety.estop", {"active": False}
        ))
        self.assertEqual(reply_reason(denied), "CONTROL_LEASE_REQUIRED")

        self.request_control(4)
        reset = self.core.handle(envelope(
            "windows-1", 5, "safety.estop", {"active": False}
        ))
        self.assertTrue(reset.state_changed)
        self.assertFalse(self.core.state.emergency_stop)
        self.assertEqual(self.core.state.mode, GatewayMode.PAUSED)

    def test_reverse_is_accepted_in_manual_mode(self) -> None:
        lease_id = self.request_control()
        self.core.handle(envelope(
            "windows-1", 3, "mode.set", {"mode": "MANUAL", "leaseId": lease_id}
        ))
        result = self.core.handle(envelope(
            "windows-1",
            4,
            "control.command",
            {"direction": "REVERSE", "speed": 0.4, "leaseId": lease_id},
        ))
        self.assertIsNone(reply_reason(result))
        self.assertEqual(self.core.state.motion, GatewayMotion.REVERSE)
        self.assertEqual(self.core.state.manual_speed, 0.4)

    def test_dry_run_telemetry_never_claims_motor_online(self) -> None:
        telemetry = self.core.telemetry()
        self.assertTrue(telemetry["gatewayDryRun"])
        self.assertFalse(telemetry["motorOnline"])
        self.assertFalse(telemetry["uartOnline"])

    def test_video_request_returns_authenticated_stream_descriptor(self) -> None:
        self.core.configure_runtime(
            video_available=True,
            motor_output_enabled=False,
        )
        result = self.core.handle(envelope(
            "windows-1",
            2,
            "video.request",
        ))
        self.assertEqual(result.replies[0][0], "video.ready")
        self.assertEqual(result.replies[0][1]["endpoint"], "/video")
        self.assertEqual(result.replies[0][1]["transport"], "websocket-jpeg")

    def test_runtime_telemetry_reports_camera_and_detection(self) -> None:
        self.core.configure_runtime(
            video_available=True,
            motor_output_enabled=False,
        )
        self.core.update_perception(
            detected=True,
            confidence=0.83,
            ball_x=0.4,
            ball_y=0.6,
            ball_width=0.1,
            ball_height=0.12,
            camera_fps=22.0,
            inference_ms=18.0,
        )
        telemetry = self.core.telemetry()
        self.assertTrue(telemetry["cameraOnline"])
        self.assertTrue(telemetry["videoReady"])
        self.assertTrue(telemetry["ballDetected"])
        self.assertEqual(telemetry["confidence"], 0.83)

    def test_runtime_boot_mode_paused_forces_safe_stop(self) -> None:
        self.core.state.mode = GatewayMode.AUTO
        self.core.state.motion = GatewayMotion.FORWARD

        self.core.configure_runtime(
            video_available=True,
            motor_output_enabled=False,
            boot_mode=GatewayMode.PAUSED,
        )

        self.assertEqual(self.core.state.mode, GatewayMode.PAUSED)
        self.assertEqual(self.core.state.motion, GatewayMotion.STOP)

    def test_auto_pickup_only_during_near_ball_forward(self) -> None:
        self.core.configure_runtime(
            video_available=True,
            motor_output_enabled=True,
            mode_gpio_enabled=True,
            boot_mode=GatewayMode.AUTO,
        )
        self.core.update_perception(
            detected=False, confidence=0.0, ball_x=None, ball_y=None,
            ball_width=None, ball_height=None, camera_fps=20.0,
            inference_ms=10.0,
        )

        def motion(value: GatewayMotion, pickup: bool) -> None:
            self.core.update_runtime_motion(
                value, search_phase="PICKUP" if pickup else "TRACKING",
                motor_online=True, uart_online=True, auto_pickup=pickup,
            )

        motion(GatewayMotion.FORWARD, False)
        self.assertEqual(self.core.state.task_mode, TaskMode.TRACKING)
        motion(GatewayMotion.TURN_LEFT, False)
        self.assertEqual(self.core.state.task_mode, TaskMode.TRACKING)
        motion(GatewayMotion.FORWARD, True)
        self.assertEqual(self.core.state.task_mode, TaskMode.PICKUP)
        self.assertEqual(self.core.telemetry()["taskMode"], "PICKUP")
        motion(GatewayMotion.STOP, True)
        self.assertEqual(self.core.state.task_mode, TaskMode.PICKUP)
        motion(GatewayMotion.TURN_LEFT, True)
        self.assertEqual(self.core.state.task_mode, TaskMode.TRACKING)
        motion(GatewayMotion.STOP, False)
        self.assertEqual(self.core.state.task_mode, TaskMode.TRACKING)

        self.core.update_perception(
            detected=False, confidence=0.0, ball_x=None, ball_y=None,
            ball_width=None, ball_height=None, camera_fps=0.0,
            inference_ms=0.0, camera_online=False,
        )
        motion(GatewayMotion.FORWARD, True)
        self.assertEqual(self.core.state.task_mode, TaskMode.TRACKING)

        self.core.configure_runtime(
            video_available=True, motor_output_enabled=False,
            mode_gpio_enabled=True, boot_mode=GatewayMode.AUTO,
        )
        self.core.update_perception(
            detected=False, confidence=0.0, ball_x=None, ball_y=None,
            ball_width=None, ball_height=None, camera_fps=20.0,
            inference_ms=10.0,
        )
        motion(GatewayMotion.FORWARD, True)
        self.assertEqual(self.core.state.task_mode, TaskMode.TRACKING)

    def test_auto_task_mode_rejects_manual_override_and_mode_change_resets(self) -> None:
        self.core.configure_runtime(
            video_available=True, motor_output_enabled=True,
            mode_gpio_enabled=True, boot_mode=GatewayMode.AUTO,
        )
        lease_id = self.request_control()
        rejected = self.core.handle(envelope(
            "windows-1", 3, "task_mode.set",
            {"taskMode": "PICKUP", "leaseId": lease_id},
        ))
        self.assertEqual(reply_reason(rejected), "AUTO_TASK_MODE_MANAGED")
        self.assertEqual(self.core.state.task_mode, TaskMode.TRACKING)

        self.core.handle(envelope(
            "windows-1", 4, "mode.set",
            {"mode": "MANUAL", "leaseId": lease_id},
        ))
        accepted = self.core.handle(envelope(
            "windows-1", 5, "task_mode.set",
            {"taskMode": "PICKUP", "leaseId": lease_id},
        ))
        self.assertIsNone(reply_reason(accepted))
        self.assertEqual(self.core.state.task_mode, TaskMode.PICKUP)
        self.core.handle(envelope(
            "windows-1", 6, "mode.set",
            {"mode": "AUTO", "leaseId": lease_id},
        ))
        self.assertEqual(self.core.state.task_mode, TaskMode.TRACKING)

    def test_manual_disconnect_releases_pickup_gpio(self) -> None:
        self.core.configure_runtime(
            video_available=True, motor_output_enabled=True,
            mode_gpio_enabled=True, boot_mode=GatewayMode.MANUAL,
        )
        lease_id = self.request_control()
        self.core.handle(envelope(
            "windows-1", 3, "task_mode.set",
            {"taskMode": "PICKUP", "leaseId": lease_id},
        ))
        self.assertEqual(self.core.state.task_mode, TaskMode.PICKUP)
        self.core.disconnect("windows-1")
        self.assertEqual(self.core.state.task_mode, TaskMode.TRACKING)


class RuntimeSettingsTests(unittest.TestCase):
    def test_environment_defaults_to_auto_boot_mode(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = RuntimeSettings.from_environment()

        self.assertEqual(settings.boot_mode, GatewayMode.AUTO)
        self.assertEqual(settings.camera_width, 960)
        self.assertEqual(settings.camera_height, 720)
        self.assertEqual(settings.camera_fps, 30.0)

    def test_camera_settings_can_be_overridden(self) -> None:
        with patch.dict(
            os.environ,
            {
                "TENNIS_GATEWAY_CAMERA_WIDTH": "800",
                "TENNIS_GATEWAY_CAMERA_HEIGHT": "600",
                "TENNIS_GATEWAY_CAMERA_FPS": "24",
            },
            clear=True,
        ):
            settings = RuntimeSettings.from_environment()

        self.assertEqual(settings.camera_width, 800)
        self.assertEqual(settings.camera_height, 600)
        self.assertEqual(settings.camera_fps, 24.0)

    def test_odd_camera_dimension_is_rejected(self) -> None:
        with patch.dict(
            os.environ,
            {"TENNIS_GATEWAY_CAMERA_WIDTH": "865"},
            clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "must be even"):
                RuntimeSettings.from_environment()

    def test_manual_boot_mode_is_rejected(self) -> None:
        with patch.dict(
            os.environ,
            {"TENNIS_GATEWAY_BOOT_MODE": GatewayMode.MANUAL.value},
            clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "AUTO or PAUSED"):
                RuntimeSettings.from_environment()

    def test_obstacle_is_disabled_by_default_and_uses_reserved_pins(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = RuntimeSettings.from_environment()
        self.assertFalse(settings.obstacle_enabled)
        self.assertEqual((settings.obstacle_trigger_pin, settings.obstacle_echo_pin), (23, 24))
        self.assertEqual((settings.obstacle_enter_cm, settings.obstacle_clear_cm), (20, 30))

    def test_vehicle_persistent_override_disables_obstacle_but_keeps_paused_boot(self) -> None:
        config_path = (
            Path(__file__).resolve().parent
            / "deploy"
            / "tennis-robot-gateway-obstacle-commissioning.conf"
        )
        environment = dict(
            line.removeprefix("Environment=").split("=", 1)
            for line in config_path.read_text(encoding="utf-8").splitlines()
            if line.startswith("Environment=")
        )
        with patch.dict(os.environ, environment, clear=True):
            settings = RuntimeSettings.from_environment()
        self.assertFalse(settings.obstacle_enabled)
        self.assertEqual(settings.boot_mode, GatewayMode.PAUSED)

    def test_obstacle_pin_collision_and_thresholds_are_rejected(self) -> None:
        with patch.dict(os.environ, {"TENNIS_OBSTACLE_ECHO_PIN": "17"}, clear=True):
            with self.assertRaisesRegex(ValueError, "must differ"):
                RuntimeSettings.from_environment()
        with patch.dict(os.environ, {"TENNIS_OBSTACLE_CLEAR_CM": "20"}, clear=True):
            with self.assertRaisesRegex(ValueError, "thresholds"):
                RuntimeSettings.from_environment()


class LatestJpegFrameTests(unittest.TestCase):
    def test_slow_reader_gets_latest_frame(self) -> None:
        frames = LatestJpegFrame()
        frames.publish(b"first", 1.0)
        frames.publish(b"latest", 2.0)

        sequence, jpeg, captured_at = frames.wait_after(0, timeout=0.0)

        self.assertEqual(sequence, 2)
        self.assertEqual(jpeg, b"latest")
        self.assertEqual(captured_at, 2.0)
        frames.close()

    def test_closed_frame_buffer_wakes_without_data(self) -> None:
        frames = LatestJpegFrame()
        frames.close()
        self.assertIsNone(frames.wait_after(0, timeout=0.0))


if __name__ == "__main__":
    unittest.main()
