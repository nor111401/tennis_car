function resolveVideoEndpoint(controlUrl, endpoint) {
  const resolved = new URL(endpoint || "/video", controlUrl);
  resolved.protocol = controlUrl.startsWith("wss://") ? "wss:" : "ws:";
  return resolved.toString();
}

export class RobotVideoSession {
  constructor(imageElement, sendSignal, onStatus, onFrame) {
    this.imageElement = imageElement;
    this.sendSignal = sendSignal;
    this.onStatus = onStatus;
    this.onFrame = onFrame;
    this.socket = null;
    this.currentUrl = null;
    this.loadingUrl = null;
    this.pendingBlob = null;
    this.decoding = false;
    this.connected = false;
    this.active = false;
    this.connectionContext = null;
    this.retryTimer = null;
    this.watchdogTimer = null;
    this.retryAttempt = 0;
    this.lastFrameAt = 0;
  }

  request() {
    this.sendSignal("video.request", {
      preferredTransport: "websocket-jpeg",
      maxWidth: 1280,
      maxHeight: 720,
      maxFps: 30,
    });
  }

  connect(payload, { controlUrl, token, terminalId }) {
    this.close();
    if (payload.transport !== "websocket-jpeg") {
      this.onStatus(`不支持的视频通道：${payload.transport || "unknown"}`);
      return;
    }

    this.active = true;
    this.connectionContext = {
      endpoint: resolveVideoEndpoint(controlUrl, payload.endpoint),
      token,
      terminalId,
    };
    this.retryAttempt = 0;
    this.openSocket();
  }

  openSocket() {
    if (!this.active || !this.connectionContext) {
      return;
    }
    const { endpoint, token, terminalId } = this.connectionContext;
    const socket = new WebSocket(endpoint);
    socket.binaryType = "blob";
    this.socket = socket;
    this.onStatus("正在连接实时画面");

    socket.addEventListener("open", () => {
      if (this.socket !== socket || !this.active) {
        return;
      }
      this.retryAttempt = 0;
      this.lastFrameAt = Date.now();
      socket.send(JSON.stringify({ token, terminalId }));
    });
    socket.addEventListener("message", (event) => {
      if (event.data instanceof Blob && event.data.size > 0) {
        this.lastFrameAt = Date.now();
        this.enqueueFrame(event.data);
      }
    });
    socket.addEventListener("close", (event) => {
      if (this.socket === socket) {
        this.socket = null;
        if (this.active) {
          this.scheduleReconnect(
            event.code === 1000 ? "实时画面已关闭，正在重连" : `视频已断开（${event.code}），正在重连`,
          );
        }
      }
    });
    socket.addEventListener("error", () => {
      if (this.socket === socket && this.active) {
        this.onStatus("视频连接异常，正在重连");
      }
    });

    this.startWatchdog(socket);
  }

  startWatchdog(socket) {
    clearInterval(this.watchdogTimer);
    this.watchdogTimer = setInterval(() => {
      if (this.socket !== socket || !this.active) {
        return;
      }
      if (Date.now() - this.lastFrameAt <= 3000) {
        return;
      }
      this.onStatus("视频帧超时，正在重连");
      socket.close(4000, "video frame timeout");
    }, 1000);
  }

  scheduleReconnect(status) {
    clearInterval(this.watchdogTimer);
    clearTimeout(this.retryTimer);
    this.retryTimer = null;
    this.connected = false;
    this.onStatus(status);
    const delay = Math.min(5000, 500 * (2 ** this.retryAttempt));
    this.retryAttempt += 1;
    this.retryTimer = setTimeout(() => {
      this.retryTimer = null;
      this.openSocket();
    }, delay);
  }

  enqueueFrame(blob) {
    if (this.decoding) {
      this.pendingBlob = blob;
      return;
    }
    this.displayFrame(blob);
  }

  displayFrame(blob) {
    this.decoding = true;
    const nextUrl = URL.createObjectURL(blob);
    this.loadingUrl = nextUrl;
    this.imageElement.onload = () => {
      if (this.loadingUrl !== nextUrl) {
        return;
      }
      this.loadingUrl = null;
      if (this.currentUrl) {
        URL.revokeObjectURL(this.currentUrl);
      }
      this.currentUrl = nextUrl;
      this.decoding = false;
      if (!this.connected) {
        this.connected = true;
        this.onStatus("实时画面已连接");
      }
      this.onFrame();
      const pending = this.pendingBlob;
      this.pendingBlob = null;
      if (pending) {
        this.displayFrame(pending);
      }
    };
    this.imageElement.onerror = () => {
      if (this.loadingUrl !== nextUrl) {
        return;
      }
      this.loadingUrl = null;
      URL.revokeObjectURL(nextUrl);
      this.decoding = false;
      this.onStatus("视频帧解码失败");
    };
    this.imageElement.src = nextUrl;
  }

  close() {
    this.active = false;
    this.connectionContext = null;
    clearTimeout(this.retryTimer);
    clearInterval(this.watchdogTimer);
    this.retryTimer = null;
    this.watchdogTimer = null;
    if (this.socket) {
      this.socket.close(1000, "video session closed");
      this.socket = null;
    }
    this.pendingBlob = null;
    this.decoding = false;
    this.connected = false;
    this.lastFrameAt = 0;
    this.imageElement.onload = null;
    this.imageElement.onerror = null;
    this.imageElement.removeAttribute("src");
    if (this.currentUrl) {
      URL.revokeObjectURL(this.currentUrl);
      this.currentUrl = null;
    }
    if (this.loadingUrl) {
      URL.revokeObjectURL(this.loadingUrl);
      this.loadingUrl = null;
    }
  }
}

export { resolveVideoEndpoint };
