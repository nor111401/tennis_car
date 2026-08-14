import { MessageFactory } from "../src/protocol.js";
import { resolveVideoEndpoint } from "../src/video.js";

const controlUrl = process.argv[2]
  || process.env.TENNIS_GATEWAY_URL
  || "ws://127.0.0.1:8765/ws";
const token = process.env.TENNIS_GATEWAY_TOKEN || "";
const terminalId = `video-smoke-${Date.now()}`;
const factory = new MessageFactory(terminalId);
const control = new WebSocket(controlUrl);

let finished = false;
let video = null;
let videoBytes = 0;
let cameraFps = 0;
const timeout = setTimeout(
  () => finish(new Error("video smoke test timed out")),
  12_000,
);

function finish(error = null) {
  if (finished) {
    return;
  }
  finished = true;
  clearTimeout(timeout);
  if (video?.readyState === WebSocket.OPEN) {
    video.close(1000, "test complete");
  }
  if (control.readyState === WebSocket.OPEN) {
    control.close(1000, "test complete");
  }
  if (error) {
    console.error(`FAIL ${error.message}`);
    process.exitCode = 1;
  }
}

function maybeFinish() {
  if (videoBytes > 0 && cameraFps > 0) {
    console.log(
      `PASS authenticated live video (${videoBytes} bytes, ${cameraFps.toFixed(1)} FPS telemetry)`,
    );
    finish();
  }
}

control.addEventListener("open", () => {
  control.send(JSON.stringify(factory.create("session.hello", {
    token,
    terminalName: "Video smoke test",
    capabilities: ["telemetry", "websocket-jpeg-video"],
  })));
});

control.addEventListener("message", (event) => {
  const message = JSON.parse(event.data);
  if (message.type === "session.welcome") {
    control.send(JSON.stringify(factory.create("video.request", {
      preferredTransport: "websocket-jpeg",
    })));
    return;
  }
  if (message.type === "state.telemetry" && message.payload.cameraOnline) {
    cameraFps = Number(message.payload.cameraFps) || 0;
    maybeFinish();
    return;
  }
  if (message.type === "video.ready") {
    const endpoint = resolveVideoEndpoint(controlUrl, message.payload.endpoint);
    video = new WebSocket(endpoint);
    video.binaryType = "arraybuffer";
    video.addEventListener("open", () => {
      video.send(JSON.stringify({ token, terminalId }));
    });
    video.addEventListener("message", (videoEvent) => {
      const bytes = new Uint8Array(videoEvent.data);
      if (bytes.length < 1_000 || bytes[0] !== 0xff || bytes[1] !== 0xd8) {
        finish(new Error("received payload is not a valid JPEG frame"));
        return;
      }
      videoBytes = bytes.length;
      maybeFinish();
    });
    video.addEventListener("error", () => finish(new Error("video websocket failed")));
    video.addEventListener("close", (closeEvent) => {
      if (!finished) {
        finish(new Error(`video closed (${closeEvent.code}: ${closeEvent.reason})`));
      }
    });
  }
  if (message.type === "command.rejected") {
    finish(new Error(`video request rejected: ${message.payload.reason}`));
  }
});

control.addEventListener("error", () => finish(new Error("control websocket failed")));
control.addEventListener("close", (event) => {
  if (!finished) {
    finish(new Error(`control closed (${event.code}: ${event.reason})`));
  }
});
