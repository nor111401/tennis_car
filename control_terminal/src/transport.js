import {
  MessageFactory,
  Motion,
  RobotMode,
  parseIncoming,
} from "./protocol.js";

export class RobotTransport {
  constructor({ terminalId, onMessage, onStatus }) {
    this.factory = new MessageFactory(terminalId);
    this.onMessage = onMessage;
    this.onStatus = onStatus;
    this.socket = null;
  }

  connect(url, token = "") {
    this.close(false);
    this.onStatus("CONNECTING", `正在连接 ${url}`);

    return new Promise((resolve, reject) => {
      const socket = new WebSocket(url);
      this.socket = socket;

      socket.addEventListener("open", () => {
        this.onStatus("ONLINE", "控制通道已连接");
        this.send("session.hello", {
          token,
          client: "tennis-control-terminal",
          capabilities: ["manual-control", "telemetry", "webrtc-video"],
        });
        resolve();
      }, { once: true });

      socket.addEventListener("message", (event) => {
        try {
          this.onMessage(parseIncoming(event.data));
        } catch (error) {
          this.onStatus("ERROR", `协议错误：${error.message}`);
        }
      });

      socket.addEventListener("close", () => {
        if (this.socket === socket) {
          this.socket = null;
          this.onStatus("OFFLINE", "连接已断开，小车应由服务端安全停车");
        }
      });

      socket.addEventListener("error", () => {
        this.onStatus("ERROR", "无法连接树莓派控制服务");
        reject(new Error("WebSocket connection failed"));
      }, { once: true });
    });
  }

  send(type, payload = {}) {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
      return false;
    }
    this.socket.send(JSON.stringify(this.factory.create(type, payload)));
    return true;
  }

  close(sendRelease = true) {
    if (!this.socket) {
      return;
    }
    if (sendRelease && this.socket.readyState === WebSocket.OPEN) {
      this.send("control.command", {
        direction: Motion.STOP,
        speed: 0,
        pressed: false,
      });
      this.send("control.release", {});
    }
    this.socket.close(1000, "terminal closed");
    this.socket = null;
  }
}

export class DemoTransport {
  constructor({ terminalId, onMessage, onStatus }) {
    this.factory = new MessageFactory(terminalId);
    this.onMessage = onMessage;
    this.onStatus = onStatus;
    this.timer = null;
    this.startedAt = Date.now();
    this.mode = RobotMode.AUTO;
    this.motion = Motion.FORWARD;
    this.hasControl = false;
    this.emergencyStop = false;
    this.speed = 0.6;
  }

  async connect() {
    this.onStatus("DEMO", "演示模式：未连接真实小车");
    this.onMessage(this.factory.create("session.welcome", {
      robotName: "Tennis Rover Demo",
    }));
    this.timer = window.setInterval(() => this.emitTelemetry(), 100);
  }

  send(type, payload = {}) {
    if (type === "control.request") {
      this.hasControl = true;
      this.onMessage(this.factory.create("control.granted", {
        leaseId: "demo-lease",
        controllerName: "本终端（演示）",
      }));
    } else if (type === "control.release") {
      this.hasControl = false;
      this.motion = Motion.STOP;
      this.onMessage(this.factory.create("control.released", {}));
    } else if (type === "mode.set") {
      this.mode = payload.mode;
      this.motion = Motion.STOP;
      this.onMessage(this.factory.create("mode.changed", {
        mode: this.mode,
      }));
    } else if (type === "control.command" && this.mode === RobotMode.MANUAL) {
      this.motion = payload.direction || Motion.STOP;
      this.speed = payload.speed || 0;
    } else if (type === "safety.estop") {
      this.emergencyStop = Boolean(payload.active);
      this.mode = this.emergencyStop
        ? RobotMode.EMERGENCY_STOP
        : RobotMode.PAUSED;
      this.motion = Motion.STOP;
      this.onMessage(this.factory.create("safety.estop", {
        active: this.emergencyStop,
      }));
    }
    return true;
  }

  emitTelemetry() {
    const elapsed = (Date.now() - this.startedAt) / 1000;
    const detected = Math.sin(elapsed * 0.55) > -0.35;
    const ballX = 0.5 + Math.sin(elapsed * 0.8) * 0.28;
    const ballY = 0.58 + Math.cos(elapsed * 0.4) * 0.10;
    this.onMessage(this.factory.create("state.telemetry", {
      mode: this.mode,
      motion: this.emergencyStop ? Motion.STOP : this.motion,
      emergencyStop: this.emergencyStop,
      controllerName: this.hasControl ? "本终端（演示）" : "无人接管",
      ballDetected: detected,
      confidence: detected ? 0.82 + Math.sin(elapsed) * 0.12 : 0,
      ballX: detected ? ballX : null,
      ballY: detected ? ballY : null,
      ballWidth: detected ? 0.12 : null,
      ballHeight: detected ? 0.12 : null,
      searchPhase: detected ? "TRACKING" : "WAITING",
      cameraFps: 39.6,
      inferenceMs: 18,
      latencyMs: 42,
      motorOnline: true,
      uartOnline: true,
    }));
  }

  close() {
    if (this.timer !== null) {
      window.clearInterval(this.timer);
      this.timer = null;
    }
    this.onStatus("OFFLINE", "演示模式已关闭");
  }
}
