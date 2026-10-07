import { Motion, RobotMode } from "./protocol.js";

export const ConnectionStatus = Object.freeze({
  OFFLINE: "OFFLINE",
  CONNECTING: "CONNECTING",
  ONLINE: "ONLINE",
  ERROR: "ERROR",
});

const CONTROL_LEASE_ERRORS = new Set([
  "CONTROL_LEASE_REQUIRED",
  "INVALID_CONTROL_LEASE",
]);

export function isControlLeaseError(reason) {
  return CONTROL_LEASE_ERRORS.has(reason);
}

export function createInitialState() {
  return {
    connection: ConnectionStatus.OFFLINE,
    connectionDetail: "尚未连接",
    mode: RobotMode.AUTO,
    taskMode: "TRACKING",
    modeGpioEnabled: false,
    modeGpioPin: 17,
    modeGpioOnline: false,
    modeGpioLevel: null,
    modeGpioError: null,
    motion: Motion.STOP,
    emergencyStop: false,
    hasControl: false,
    leaseId: null,
    controllerName: "无人接管",
    ballDetected: false,
    confidence: 0,
    ballX: null,
    ballY: null,
    ballWidth: null,
    ballHeight: null,
    searchPhase: "IDLE",
    cameraFps: 0,
    inferenceMs: 0,
    latencyMs: null,
    motorOnline: false,
    uartOnline: false,
    lastTelemetryAt: null,
  };
}

export function reduceState(state, event) {
  switch (event.type) {
    case "connection":
      return {
        ...state,
        connection: event.status,
        connectionDetail: event.detail || state.connectionDetail,
        ...(event.status === ConnectionStatus.OFFLINE
          || event.status === ConnectionStatus.ERROR
          ? {
              motion: Motion.STOP,
              hasControl: false,
              leaseId: null,
              controllerName: "无人接管",
            }
          : {}),
      };
    case "control.granted":
      return {
        ...state,
        hasControl: true,
        leaseId: event.leaseId,
        controllerName: event.controllerName || "本终端",
      };
    case "control.released":
    case "control.lost":
      return {
        ...state,
        hasControl: false,
        leaseId: null,
        controllerName: event.controllerName || "无人接管",
        motion: Motion.STOP,
      };
    case "telemetry":
      return {
        ...state,
        ...event.payload,
        lastTelemetryAt: event.receivedAt || Date.now(),
      };
    case "mode":
      return {
        ...state,
        mode: event.mode,
        motion: Motion.STOP,
      };
    case "task-mode":
      return {
        ...state,
        taskMode: event.taskMode,
      };
    case "estop":
      return {
        ...state,
        emergencyStop: event.active,
        mode: event.active ? RobotMode.EMERGENCY_STOP : RobotMode.PAUSED,
        motion: Motion.STOP,
      };
    default:
      return state;
  }
}

export function canSendManualDrive(state) {
  return state.connection !== ConnectionStatus.OFFLINE
    && state.connection !== ConnectionStatus.ERROR
    && state.mode === RobotMode.MANUAL
    && state.hasControl
    && !state.emergencyStop;
}
