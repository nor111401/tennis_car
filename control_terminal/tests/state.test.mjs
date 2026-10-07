import test from "node:test";
import assert from "node:assert/strict";

import { Motion, RobotMode } from "../src/protocol.js";
import {
  ConnectionStatus,
  canSendManualDrive,
  createInitialState,
  isControlLeaseError,
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

test("expired server lease clears stale local control state", () => {
  const stale = {
    ...createInitialState(),
    connection: ConnectionStatus.ONLINE,
    mode: RobotMode.EMERGENCY_STOP,
    emergencyStop: true,
    hasControl: true,
    leaseId: "expired-lease",
    controllerName: "本终端",
  };
  const recovered = reduceState(stale, {
    type: "control.lost",
    controllerName: "无人接管",
  });
  assert.equal(recovered.hasControl, false);
  assert.equal(recovered.leaseId, null);
  assert.equal(recovered.controllerName, "无人接管");
  assert.equal(recovered.motion, Motion.STOP);
  assert.equal(recovered.emergencyStop, true);
});

test("server lease rejection reasons are recognized", () => {
  assert.equal(isControlLeaseError("CONTROL_LEASE_REQUIRED"), true);
  assert.equal(isControlLeaseError("INVALID_CONTROL_LEASE"), true);
  assert.equal(isControlLeaseError("EMERGENCY_STOP_LATCHED"), false);
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
