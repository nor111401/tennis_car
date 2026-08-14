"""Versioned WebSocket protocol shared with the control terminal."""

from __future__ import annotations

from dataclasses import dataclass
import json
import time
from typing import Any, Callable


PROTOCOL_VERSION = 1


class ProtocolError(ValueError):
    """Raised when a client envelope is invalid or unsupported."""


@dataclass(frozen=True)
class ClientEnvelope:
    version: int
    type: str
    sequence: int
    terminal_id: str
    sent_at: int
    payload: dict[str, Any]

    @classmethod
    def parse(cls, raw: str | bytes | dict[str, Any]) -> "ClientEnvelope":
        try:
            value = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ProtocolError("invalid JSON") from exc

        if not isinstance(value, dict):
            raise ProtocolError("message must be a JSON object")
        if value.get("version") != PROTOCOL_VERSION:
            raise ProtocolError("unsupported protocol version")

        message_type = value.get("type")
        if not isinstance(message_type, str) or not message_type:
            raise ProtocolError("message type is required")

        sequence = value.get("sequence")
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1:
            raise ProtocolError("sequence must be a positive integer")

        terminal_id = value.get("terminalId")
        if not isinstance(terminal_id, str) or not terminal_id.strip():
            raise ProtocolError("terminalId is required")
        if len(terminal_id) > 128:
            raise ProtocolError("terminalId is too long")

        sent_at = value.get("sentAt")
        if not isinstance(sent_at, int) or isinstance(sent_at, bool) or sent_at < 0:
            raise ProtocolError("sentAt must be a non-negative integer")

        payload = value.get("payload", {})
        if not isinstance(payload, dict):
            raise ProtocolError("payload must be an object")

        return cls(
            version=PROTOCOL_VERSION,
            type=message_type,
            sequence=sequence,
            terminal_id=terminal_id.strip(),
            sent_at=sent_at,
            payload=payload,
        )


class ServerMessageFactory:
    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._sequence = 0

    def create(self, message_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._sequence += 1
        return {
            "version": PROTOCOL_VERSION,
            "type": message_type,
            "sequence": self._sequence,
            "terminalId": "tennis-robot",
            "sentAt": int(self._clock() * 1000),
            "payload": payload,
        }
