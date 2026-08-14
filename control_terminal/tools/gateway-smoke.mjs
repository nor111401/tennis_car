import { MessageFactory } from "../src/protocol.js";

const gatewayUrl = process.argv[2]
  || process.env.TENNIS_GATEWAY_URL
  || "ws://127.0.0.1:8765/ws";
const terminalId = `gateway-smoke-${Date.now()}`;
const factory = new MessageFactory(terminalId);
const socket = new WebSocket(gatewayUrl);

let leaseId = null;
let heartbeatTimer = null;
let sawForward = false;
let sawFinalStop = false;

const timeout = setTimeout(() => finish(new Error("gateway smoke test timed out")), 8_000);

function send(type, payload = {}) {
  socket.send(JSON.stringify(factory.create(type, payload)));
}

function finish(error = null) {
  clearTimeout(timeout);
  clearInterval(heartbeatTimer);
  if (socket.readyState === WebSocket.OPEN) {
    socket.close(1000, error ? "smoke test failed" : "smoke test passed");
  }
  if (error) {
    console.error(`FAIL ${error.message}`);
    process.exitCode = 1;
  } else {
    console.log("PASS live gateway handshake, lease, manual drive, stop, pause, release");
  }
}

socket.addEventListener("open", () => {
  send("session.hello", {
    terminalName: "Gateway smoke test",
    client: "gateway-smoke",
    capabilities: ["manual-control", "telemetry"],
  });
});

socket.addEventListener("message", (event) => {
  const message = JSON.parse(event.data);
  const payload = message.payload || {};

  if (message.type === "session.welcome") {
    if (!payload.gatewayDryRun || payload.motorOutputEnabled !== false) {
      finish(new Error("gateway did not report safe dry-run state"));
      return;
    }
    send("control.request", { terminalName: "Gateway smoke test" });
    return;
  }

  if (message.type === "control.granted") {
    leaseId = payload.leaseId;
    heartbeatTimer = setInterval(() => {
      send("control.heartbeat", { leaseId });
    }, 200);
    send("mode.set", { mode: "MANUAL", leaseId });
    return;
  }

  if (message.type === "mode.changed" && payload.mode === "MANUAL") {
    send("control.command", {
      direction: "FORWARD",
      speed: 0.6,
      pressed: true,
      leaseId,
    });
    return;
  }

  if (message.type === "state.telemetry" && payload.mode === "MANUAL"
      && payload.motion === "FORWARD") {
    sawForward = true;
    send("control.command", {
      direction: "STOP",
      speed: 0,
      pressed: false,
      leaseId,
    });
    return;
  }

  if (message.type === "state.telemetry" && sawForward
      && payload.mode === "MANUAL" && payload.motion === "STOP") {
    sawFinalStop = true;
    send("mode.set", { mode: "PAUSED", leaseId });
    return;
  }

  if (message.type === "mode.changed" && payload.mode === "PAUSED") {
    if (!sawForward || !sawFinalStop) {
      finish(new Error("manual motion state was not observed"));
      return;
    }
    send("control.release", { leaseId });
    return;
  }

  if (message.type === "control.released") {
    finish();
    return;
  }

  if (message.type === "command.rejected") {
    finish(new Error(`command rejected: ${payload.reason || "unknown"}`));
  }
});

socket.addEventListener("error", () => finish(new Error(`cannot connect to ${gatewayUrl}`)));
