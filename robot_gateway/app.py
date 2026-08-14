"""FastAPI WebSocket entry point for the dry-run robot gateway."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
import hmac
import os
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from .core import RobotGatewayCore
from .protocol import ClientEnvelope, ProtocolError, ServerMessageFactory


@dataclass(frozen=True)
class GatewaySettings:
    token: str = ""
    telemetry_interval: float = 0.10

    @classmethod
    def from_environment(cls) -> "GatewaySettings":
        interval = float(os.environ.get("TENNIS_GATEWAY_TELEMETRY_SECONDS", "0.10"))
        if not 0.05 <= interval <= 2.0:
            raise ValueError("TENNIS_GATEWAY_TELEMETRY_SECONDS must be within [0.05, 2.0]")
        return cls(
            token=os.environ.get("TENNIS_GATEWAY_TOKEN", ""),
            telemetry_interval=interval,
        )


@dataclass
class ClientConnection:
    websocket: WebSocket
    send_lock: asyncio.Lock


class ConnectionManager:
    def __init__(self) -> None:
        self.clients: dict[str, ClientConnection] = {}
        self.factory = ServerMessageFactory()
        self._clients_lock = asyncio.Lock()

    async def add(self, terminal_id: str, websocket: WebSocket) -> bool:
        async with self._clients_lock:
            if terminal_id in self.clients:
                return False
            self.clients[terminal_id] = ClientConnection(websocket, asyncio.Lock())
            return True

    async def remove(self, terminal_id: str) -> None:
        async with self._clients_lock:
            self.clients.pop(terminal_id, None)

    async def send(
        self,
        terminal_id: str,
        message_type: str,
        payload: dict[str, Any],
    ) -> None:
        connection = self.clients.get(terminal_id)
        if connection is None:
            return
        message = self.factory.create(message_type, payload)
        async with connection.send_lock:
            await connection.websocket.send_json(message)

    async def broadcast_telemetry(self, payload: dict[str, Any]) -> None:
        terminal_ids = list(self.clients)
        if not terminal_ids:
            return
        await asyncio.gather(
            *(self._safe_send(terminal_id, "state.telemetry", payload)
              for terminal_id in terminal_ids),
        )

    async def _safe_send(
        self,
        terminal_id: str,
        message_type: str,
        payload: dict[str, Any],
    ) -> None:
        try:
            await self.send(terminal_id, message_type, payload)
        except (RuntimeError, WebSocketDisconnect):
            await self.remove(terminal_id)


def create_app(
    core: RobotGatewayCore | None = None,
    settings: GatewaySettings | None = None,
) -> FastAPI:
    gateway_core = core or RobotGatewayCore()
    gateway_settings = settings or GatewaySettings.from_environment()
    manager = ConnectionManager()

    async def telemetry_loop() -> None:
        while True:
            await asyncio.sleep(gateway_settings.telemetry_interval)
            gateway_core.tick()
            await manager.broadcast_telemetry(gateway_core.telemetry())

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        task = asyncio.create_task(telemetry_loop(), name="gateway-telemetry")
        try:
            yield
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    application = FastAPI(
        title="Tennis Robot Gateway",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.state.gateway_core = gateway_core
    application.state.connection_manager = manager

    @application.get("/")
    async def root() -> dict[str, Any]:
        return {
            "service": "tennis-robot-gateway",
            "version": "0.1.0",
            "dryRun": True,
            "websocket": "/ws",
        }

    @application.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "dryRun": True,
            "motorOutputEnabled": False,
            "connectedClients": len(gateway_core.sessions),
            "mode": gateway_core.state.mode.value,
        }

    @application.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await websocket.accept()
        terminal_id: str | None = None
        try:
            raw = await asyncio.wait_for(websocket.receive_text(), timeout=5.0)
            hello = ClientEnvelope.parse(raw)
            if hello.type != "session.hello":
                await websocket.close(code=1008, reason="session.hello required")
                return
            supplied_token = str(hello.payload.get("token", ""))
            if gateway_settings.token and not hmac.compare_digest(
                supplied_token,
                gateway_settings.token,
            ):
                await websocket.close(code=1008, reason="authentication failed")
                return

            terminal_id = hello.terminal_id
            if not await manager.add(terminal_id, websocket):
                await websocket.close(code=1008, reason="terminal already connected")
                terminal_id = None
                return

            terminal_name = str(hello.payload.get("terminalName", "控制终端"))
            welcome = gateway_core.open_session(
                terminal_id,
                terminal_name,
                hello.sequence,
            )
            await manager.send(terminal_id, "session.welcome", welcome)
            await manager.send(terminal_id, "state.telemetry", gateway_core.telemetry())

            while True:
                raw = await websocket.receive_text()
                envelope = ClientEnvelope.parse(raw)
                if envelope.terminal_id != terminal_id:
                    await manager.send(
                        terminal_id,
                        "command.rejected",
                        {"reason": "TERMINAL_ID_CHANGED"},
                    )
                    continue
                result = gateway_core.handle(envelope)
                for message_type, payload in result.replies:
                    await manager.send(terminal_id, message_type, payload)
                if result.state_changed:
                    await manager.broadcast_telemetry(gateway_core.telemetry())

        except asyncio.TimeoutError:
            await websocket.close(code=1008, reason="hello timeout")
        except ProtocolError as exc:
            if terminal_id is not None:
                await manager.send(
                    terminal_id,
                    "command.rejected",
                    {"reason": "INVALID_PROTOCOL", "detail": str(exc)},
                )
            else:
                await websocket.close(code=1008, reason="invalid protocol")
        except WebSocketDisconnect:
            pass
        finally:
            if terminal_id is not None:
                await manager.remove(terminal_id)
                if gateway_core.disconnect(terminal_id):
                    await manager.broadcast_telemetry(gateway_core.telemetry())

    return application


app = create_app()
