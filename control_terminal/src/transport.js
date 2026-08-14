import {
  MessageFactory,
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
    this.close();
    this.onStatus("CONNECTING", `正在连接 ${url}`);

    return new Promise((resolve, reject) => {
      const socket = new WebSocket(url);
      this.socket = socket;

      socket.addEventListener("open", () => {
        this.onStatus("ONLINE", "控制通道已连接");
        this.send("session.hello", {
          token,
          client: "tennis-control-terminal",
          capabilities: ["manual-control", "telemetry", "websocket-jpeg-video"],
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

  close() {
    if (!this.socket) {
      return;
    }
    this.socket.close(1000, "terminal closed");
    this.socket = null;
  }
}
