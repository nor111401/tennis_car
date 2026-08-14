"""Pure safety and mode-arbitration core for the network gateway.

This first gateway phase is deliberately dry-run only. It never opens UART and
never calls MotorController. The pure core is kept independent of FastAPI so
all safety transitions can be tested without network or vehicle hardware.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import secrets
import time
from typing import Any, Callable

from .protocol import ClientEnvelope


class GatewayMode(str, Enum):
    AUTO = "AUTO"
    MANUAL = "MANUAL"
    PAUSED = "PAUSED"
    MANUAL_LOST = "MANUAL_LOST"
    EMERGENCY_STOP = "EMERGENCY_STOP"


class GatewayMotion(str, Enum):
    STOP = "STOP"
    FORWARD = "FORWARD"
    TURN_LEFT = "TURN_LEFT"
    TURN_RIGHT = "TURN_RIGHT"


@dataclass
class ClientSession:
    terminal_id: str
    name: str
    last_sequence: int


@dataclass
class ControlLease:
    terminal_id: str
    lease_id: str
    last_heartbeat: float


@dataclass
class GatewayState:
    mode: GatewayMode = GatewayMode.AUTO
    motion: GatewayMotion = GatewayMotion.STOP
    emergency_stop: bool = False
    controller_name: str = "无人接管"
    ball_detected: bool = False
    confidence: float = 0.0
    ball_x: float | None = None
    ball_y: float | None = None
    ball_width: float | None = None
    ball_height: float | None = None
    search_phase: str = "GATEWAY_DRY_RUN"
    camera_fps: float = 0.0
    inference_ms: float = 0.0
    latency_ms: float | None = None
    motor_online: bool = False
    uart_online: bool = False
    manual_speed: float = 0.0

    def telemetry(self, connected_clients: int) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "motion": self.motion.value,
            "emergencyStop": self.emergency_stop,
            "controllerName": self.controller_name,
            "ballDetected": self.ball_detected,
            "confidence": self.confidence,
            "ballX": self.ball_x,
            "ballY": self.ball_y,
            "ballWidth": self.ball_width,
            "ballHeight": self.ball_height,
            "searchPhase": self.search_phase,
            "cameraFps": self.camera_fps,
            "inferenceMs": self.inference_ms,
            "latencyMs": self.latency_ms,
            "motorOnline": self.motor_online,
            "uartOnline": self.uart_online,
            "connectedClients": connected_clients,
            "gatewayDryRun": True,
        }


@dataclass(frozen=True)
class CoreResult:
    replies: tuple[tuple[str, dict[str, Any]], ...] = field(default_factory=tuple)
    state_changed: bool = False


class RobotGatewayCore:
    LEASE_TIMEOUT_SECONDS = 0.60
    SUPPORTED_MANUAL_MOTIONS = {
        GatewayMotion.STOP.value,
        GatewayMotion.FORWARD.value,
        GatewayMotion.TURN_LEFT.value,
        GatewayMotion.TURN_RIGHT.value,
    }

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self.state = GatewayState()
        self.sessions: dict[str, ClientSession] = {}
        self.lease: ControlLease | None = None

    def open_session(
        self,
        terminal_id: str,
        terminal_name: str,
        first_sequence: int,
    ) -> dict[str, Any]:
        self.sessions[terminal_id] = ClientSession(
            terminal_id=terminal_id,
            name=terminal_name[:80] or "未命名终端",
            last_sequence=first_sequence,
        )
        return {
            "robotName": "Tennis Rover",
            "protocolVersion": 1,
            "gatewayDryRun": True,
            "videoReady": False,
            "motorOutputEnabled": False,
            "supportedModes": ["AUTO", "MANUAL", "PAUSED"],
            "supportedManualMotions": sorted(self.SUPPORTED_MANUAL_MOTIONS),
        }

    def disconnect(self, terminal_id: str) -> bool:
        self.sessions.pop(terminal_id, None)
        if self.lease is None or self.lease.terminal_id != terminal_id:
            return False
        manual_was_active = self.state.mode is GatewayMode.MANUAL
        self._release_lease()
        if manual_was_active:
            self.state.mode = GatewayMode.MANUAL_LOST
            self._force_stop()
        return True

    def handle(self, envelope: ClientEnvelope) -> CoreResult:
        session = self.sessions.get(envelope.terminal_id)
        if session is None:
            return self._rejected("SESSION_NOT_ESTABLISHED")
        if envelope.sequence <= session.last_sequence:
            return self._rejected("STALE_SEQUENCE")
        session.last_sequence = envelope.sequence

        handlers = {
            "control.request": self._handle_control_request,
            "control.release": self._handle_control_release,
            "control.heartbeat": self._handle_heartbeat,
            "mode.set": self._handle_mode_set,
            "control.command": self._handle_control_command,
            "safety.estop": self._handle_estop,
            "video.request": self._handle_video_request,
        }
        handler = handlers.get(envelope.type)
        if handler is None:
            return self._rejected("UNSUPPORTED_MESSAGE_TYPE")
        return handler(session, envelope.payload)

    def tick(self) -> bool:
        if self.lease is None:
            return False
        if self.clock() - self.lease.last_heartbeat <= self.LEASE_TIMEOUT_SECONDS:
            return False

        manual_was_active = self.state.mode is GatewayMode.MANUAL
        self._release_lease()
        if manual_was_active:
            self.state.mode = GatewayMode.MANUAL_LOST
            self._force_stop()
        return True

    def telemetry(self) -> dict[str, Any]:
        return self.state.telemetry(len(self.sessions))

    def _handle_control_request(
        self,
        session: ClientSession,
        payload: dict[str, Any],
    ) -> CoreResult:
        self.tick()
        requested_name = payload.get("terminalName")
        if isinstance(requested_name, str) and requested_name.strip():
            session.name = requested_name.strip()[:80]
        if self.lease is not None and self.lease.terminal_id != session.terminal_id:
            holder = self.sessions.get(self.lease.terminal_id)
            return CoreResult((
                ("control.denied", {
                    "reason": "CONTROL_ALREADY_HELD",
                    "controllerName": holder.name if holder else "其他终端",
                }),
            ))

        if self.lease is None:
            self.lease = ControlLease(
                terminal_id=session.terminal_id,
                lease_id=secrets.token_urlsafe(18),
                last_heartbeat=self.clock(),
            )
        else:
            self.lease.last_heartbeat = self.clock()
        self.state.controller_name = session.name
        return CoreResult((
            ("control.granted", {
                "leaseId": self.lease.lease_id,
                "controllerName": session.name,
                "heartbeatIntervalMs": 250,
                "timeoutMs": int(self.LEASE_TIMEOUT_SECONDS * 1000),
            }),
        ), True)

    def _handle_control_release(
        self,
        session: ClientSession,
        payload: dict[str, Any],
    ) -> CoreResult:
        rejected = self._validate_lease(session, payload)
        if rejected is not None:
            return rejected
        if self.state.mode is GatewayMode.MANUAL:
            self.state.mode = GatewayMode.PAUSED
        self._force_stop()
        self._release_lease()
        return CoreResult((("control.released", {}),), True)

    def _handle_heartbeat(
        self,
        session: ClientSession,
        payload: dict[str, Any],
    ) -> CoreResult:
        rejected = self._validate_lease(session, payload)
        if rejected is not None:
            return rejected
        self.lease.last_heartbeat = self.clock()
        return CoreResult()

    def _handle_mode_set(
        self,
        session: ClientSession,
        payload: dict[str, Any],
    ) -> CoreResult:
        rejected = self._validate_lease(session, payload)
        if rejected is not None:
            return rejected
        if self.state.emergency_stop:
            return self._rejected("EMERGENCY_STOP_LATCHED")

        raw_mode = payload.get("mode")
        if raw_mode not in {"AUTO", "MANUAL", "PAUSED"}:
            return self._rejected("UNSUPPORTED_MODE")
        self._force_stop()
        self.state.mode = GatewayMode(raw_mode)
        self.lease.last_heartbeat = self.clock()
        return CoreResult((("mode.changed", {"mode": raw_mode}),), True)

    def _handle_control_command(
        self,
        session: ClientSession,
        payload: dict[str, Any],
    ) -> CoreResult:
        rejected = self._validate_lease(session, payload)
        if rejected is not None:
            return rejected
        if self.state.emergency_stop:
            return self._rejected("EMERGENCY_STOP_LATCHED")
        if self.state.mode is not GatewayMode.MANUAL:
            return self._rejected("MANUAL_MODE_REQUIRED")

        raw_motion = payload.get("direction")
        if raw_motion == "REVERSE":
            return self._rejected("REVERSE_NOT_IMPLEMENTED")
        if raw_motion not in self.SUPPORTED_MANUAL_MOTIONS:
            return self._rejected("UNSUPPORTED_MOTION")

        speed = payload.get("speed", 0.0)
        if not isinstance(speed, (int, float)) or isinstance(speed, bool):
            return self._rejected("INVALID_SPEED")
        if not 0.0 <= float(speed) <= 1.0:
            return self._rejected("INVALID_SPEED")

        pressed = bool(payload.get("pressed", True))
        motion = GatewayMotion(raw_motion)
        if not pressed or motion is GatewayMotion.STOP:
            self._force_stop()
        else:
            self.state.motion = motion
            self.state.manual_speed = float(speed)
        self.lease.last_heartbeat = self.clock()
        return CoreResult(state_changed=True)

    def _handle_estop(
        self,
        session: ClientSession,
        payload: dict[str, Any],
    ) -> CoreResult:
        active = payload.get("active")
        if not isinstance(active, bool):
            return self._rejected("INVALID_ESTOP_STATE")
        if active:
            self.state.emergency_stop = True
            self.state.mode = GatewayMode.EMERGENCY_STOP
            self._force_stop()
            return CoreResult((("safety.estop", {"active": True}),), True)

        rejected = self._validate_lease(session, payload, require_id=False)
        if rejected is not None:
            return rejected
        self.state.emergency_stop = False
        self.state.mode = GatewayMode.PAUSED
        self._force_stop()
        self.lease.last_heartbeat = self.clock()
        return CoreResult((("safety.estop", {"active": False}),), True)

    def _handle_video_request(
        self,
        session: ClientSession,
        payload: dict[str, Any],
    ) -> CoreResult:
        return self._rejected("VIDEO_NOT_READY")

    def _validate_lease(
        self,
        session: ClientSession,
        payload: dict[str, Any],
        *,
        require_id: bool = True,
    ) -> CoreResult | None:
        self.tick()
        if self.lease is None or self.lease.terminal_id != session.terminal_id:
            return self._rejected("CONTROL_LEASE_REQUIRED")
        if require_id and payload.get("leaseId") != self.lease.lease_id:
            return self._rejected("INVALID_CONTROL_LEASE")
        return None

    def _release_lease(self) -> None:
        self.lease = None
        self.state.controller_name = "无人接管"

    def _force_stop(self) -> None:
        self.state.motion = GatewayMotion.STOP
        self.state.manual_speed = 0.0

    @staticmethod
    def _rejected(reason: str) -> CoreResult:
        return CoreResult((("command.rejected", {"reason": reason}),))
