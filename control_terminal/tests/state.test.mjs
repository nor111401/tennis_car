import test from "node:test";
import assert from "node:assert/strict";

import { Motion, RobotMode } from "../src/protocol.js";
import {
  ConnectionStatus,
  canSendManualDrive,
  createInitialState,
  reduceState,
} from "../src/state.js";

test("manual drive requires connection, control lease and manual mode", () => {
  let state = createInitialState();
  assert.equal(canSendManualDrive(state), false);
  state = reduceState(state, {
    type: "connection",
    status: ConnectionStatus.ONLINE,
  });
  state = reduceState(state, {
    type: "control.granted",
    leaseId: "lease-1",
  });
  state = reduceState(state, { type: "mode", mode: RobotMode.MANUAL });
  assert.equal(canSendManualDrive(state), true);
});

test("disconnect clears control and motion", () => {
  const active = {
    ...createInitialState(),
    connection: ConnectionStatus.ONLINE,
    mode: RobotMode.MANUAL,
    motion: Motion.FORWARD,
    hasControl: true,
    leaseId: "lease-1",
  };
  const disconnected = reduceState(active, {
    type: "connection",
    status: ConnectionStatus.OFFLINE,
  });
  assert.equal(disconnected.motion, Motion.STOP);
  assert.equal(disconnected.hasControl, false);
  assert.equal(disconnected.leaseId, null);
});

test("emergency stop latches stop and blocks manual driving", () => {
  const manual = {
    ...createInitialState(),
    connection: ConnectionStatus.ONLINE,
    mode: RobotMode.MANUAL,
    hasControl: true,
    leaseId: "lease-1",
  };
  const stopped = reduceState(manual, { type: "estop", active: true });
  assert.equal(stopped.mode, RobotMode.EMERGENCY_STOP);
  assert.equal(stopped.motion, Motion.STOP);
  assert.equal(canSendManualDrive(stopped), false);
});
