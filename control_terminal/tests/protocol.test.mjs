import test from "node:test";
import assert from "node:assert/strict";

import {
  MessageFactory,
  Motion,
  PROTOCOL_VERSION,
  RobotMode,
  clampSpeed,
  createDrivePayload,
  createModePayload,
  parseIncoming,
} from "../src/protocol.js";

test("message factory adds monotonic sequence and timestamp", () => {
  const factory = new MessageFactory("terminal-1", () => 1234);
  const first = factory.create("session.hello", {});
  const second = factory.create("control.heartbeat", {});
  assert.equal(first.version, PROTOCOL_VERSION);
  assert.equal(first.sequence, 1);
  assert.equal(second.sequence, 2);
  assert.equal(second.sentAt, 1234);
  assert.equal(second.terminalId, "terminal-1");
});

test("drive payload clamps speed and forces stop speed to zero", () => {
  assert.deepEqual(
    createDrivePayload({ direction: Motion.FORWARD, speed: 1.7, leaseId: "x" }),
    { direction: Motion.FORWARD, speed: 1, leaseId: "x", pressed: true },
  );
  assert.equal(
    createDrivePayload({ direction: Motion.STOP, speed: 0.8 }).speed,
    0,
  );
  assert.equal(clampSpeed(-2), 0);
});

test("unsupported motion and mode are rejected", () => {
  assert.throws(() => createDrivePayload({ direction: "FLY", speed: 1 }));
  assert.throws(() => createModePayload("UNKNOWN"));
  assert.equal(createModePayload(RobotMode.MANUAL, "lease").mode, "MANUAL");
});

test("incoming protocol version is validated", () => {
  const parsed = parseIncoming(JSON.stringify({
    version: PROTOCOL_VERSION,
    type: "state.telemetry",
    payload: { mode: "AUTO" },
  }));
  assert.equal(parsed.payload.mode, "AUTO");
  assert.throws(() => parseIncoming({ version: 99, type: "bad" }));
});
