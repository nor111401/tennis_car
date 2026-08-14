export const PROTOCOL_VERSION = 1;

export const RobotMode = Object.freeze({
  AUTO: "AUTO",
  MANUAL: "MANUAL",
  PAUSED: "PAUSED",
  MANUAL_LOST: "MANUAL_LOST",
  EMERGENCY_STOP: "EMERGENCY_STOP",
});

export const Motion = Object.freeze({
  STOP: "STOP",
  FORWARD: "FORWARD",
  REVERSE: "REVERSE",
  TURN_LEFT: "TURN_LEFT",
  TURN_RIGHT: "TURN_RIGHT",
});

const ALLOWED_MODES = new Set(Object.values(RobotMode));
const ALLOWED_MOTIONS = new Set(Object.values(Motion));

export class MessageFactory {
  constructor(terminalId, clock = () => Date.now()) {
    if (!terminalId) {
      throw new Error("terminalId is required");
    }
    this.terminalId = terminalId;
    this.clock = clock;
    this.sequence = 0;
  }

  create(type, payload = {}) {
    if (typeof type !== "string" || type.length === 0) {
      throw new Error("message type is required");
    }
    return {
      version: PROTOCOL_VERSION,
      type,
      sequence: ++this.sequence,
      terminalId: this.terminalId,
      sentAt: this.clock(),
      payload,
    };
  }
}

export function clampSpeed(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return 0;
  }
  return Math.max(0, Math.min(1, numeric));
}

export function createDrivePayload({ direction, speed, leaseId, pressed = true }) {
  if (!ALLOWED_MOTIONS.has(direction)) {
    throw new Error(`unsupported direction: ${direction}`);
  }
  return {
    direction,
    speed: direction === Motion.STOP ? 0 : clampSpeed(speed),
    leaseId: leaseId || null,
    pressed: Boolean(pressed),
  };
}

export function createModePayload(mode, leaseId) {
  if (!ALLOWED_MODES.has(mode)) {
    throw new Error(`unsupported mode: ${mode}`);
  }
  return { mode, leaseId: leaseId || null };
}

export function parseIncoming(raw) {
  const message = typeof raw === "string" ? JSON.parse(raw) : raw;
  if (!message || typeof message !== "object") {
    throw new Error("message must be an object");
  }
  if (message.version !== PROTOCOL_VERSION) {
    throw new Error(`unsupported protocol version: ${message.version}`);
  }
  if (typeof message.type !== "string" || !message.type) {
    throw new Error("message type is missing");
  }
  return {
    ...message,
    payload: message.payload && typeof message.payload === "object"
      ? message.payload
      : {},
  };
}

export function isControllableMode(mode) {
  return mode === RobotMode.AUTO
    || mode === RobotMode.MANUAL
    || mode === RobotMode.PAUSED;
}
