from __future__ import annotations

import json
import unittest

from robot_gateway.core import (
    GatewayMode,
    GatewayMotion,
    RobotGatewayCore,
)
from robot_gateway.protocol import ClientEnvelope, ProtocolError


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

    def test_reverse_is_explicitly_rejected(self) -> None:
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
        self.assertEqual(reply_reason(result), "REVERSE_NOT_IMPLEMENTED")
        self.assertEqual(self.core.state.motion, GatewayMotion.STOP)

    def test_dry_run_telemetry_never_claims_motor_online(self) -> None:
        telemetry = self.core.telemetry()
        self.assertTrue(telemetry["gatewayDryRun"])
        self.assertFalse(telemetry["motorOnline"])
        self.assertFalse(telemetry["uartOnline"])


if __name__ == "__main__":
    unittest.main()
