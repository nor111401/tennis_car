import {
  Motion,
  RobotMode,
  createDrivePayload,
  createModePayload,
} from "./protocol.js";
import {
  ConnectionStatus,
  canSendManualDrive,
  createInitialState,
  reduceState,
} from "./state.js";
import { DemoTransport, RobotTransport } from "./transport.js";
import { RobotVideoSession } from "./video.js";

const elements = Object.fromEntries(
  [...document.querySelectorAll("[id]")].map((element) => [element.id, element]),
);
const modeButtons = [...document.querySelectorAll(".mode-button")];
const driveButtons = [...document.querySelectorAll(".drive-button")];

const terminalId = getOrCreateTerminalId();
let state = createInitialState();
let transport = null;
let activeMotion = Motion.STOP;
let driveTimer = null;

const videoSession = new RobotVideoSession(
  elements["robot-video"],
  (type, payload) => transport?.send(type, payload),
  (status) => {
    elements["video-status"].textContent = status;
    logEvent(status);
  },
  () => {
    elements["video-placeholder"].hidden = true;
  },
);

function getOrCreateTerminalId() {
  const stored = localStorage.getItem("tennis-terminal-id");
  if (stored) {
    return stored;
  }
  const generated = globalThis.crypto?.randomUUID?.()
    || `terminal-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  localStorage.setItem("tennis-terminal-id", generated);
  return generated;
}

function dispatch(event) {
  state = reduceState(state, event);
  render();
}

function updateConnection(status, detail) {
  dispatch({ type: "connection", status, detail });
  logEvent(detail);
}

function connectRealRobot() {
  disconnect();
  const endpoint = elements.endpoint.value.trim();
  if (!endpoint.startsWith("ws://") && !endpoint.startsWith("wss://")) {
    updateConnection(ConnectionStatus.ERROR, "地址必须以 ws:// 或 wss:// 开头");
    return;
  }
  localStorage.setItem("tennis-endpoint", endpoint);
  transport = new RobotTransport({
    terminalId,
    onMessage: handleMessage,
    onStatus: updateConnection,
  });
  transport.connect(endpoint, elements.token.value).catch(() => {});
}

function connectDemo() {
  disconnect();
  transport = new DemoTransport({
    terminalId,
    onMessage: handleMessage,
    onStatus: updateConnection,
  });
  transport.connect();
  elements["video-stage"].classList.add("demo");
  elements["video-status"].textContent = "演示画面";
}

function disconnect() {
  stopDrive(true);
  if (transport && state.hasControl) {
    transport.send("control.release", { leaseId: state.leaseId });
  }
  videoSession.close();
  if (transport) {
    const previous = transport;
    transport = null;
    previous.close();
  }
  elements["video-stage"].classList.remove("demo");
  elements["video-placeholder"].hidden = false;
  elements["video-status"].textContent = "等待视频";
}

function handleMessage(message) {
  const payload = message.payload || {};
  switch (message.type) {
    case "session.welcome":
      logEvent(`已连接 ${payload.robotName || "树莓派小车"}`);
      videoSession.request();
      break;
    case "state.telemetry":
      dispatch({ type: "telemetry", payload, receivedAt: Date.now() });
      break;
    case "control.granted":
      dispatch({
        type: "control.granted",
        leaseId: payload.leaseId,
        controllerName: payload.controllerName,
      });
      logEvent("本终端已取得车辆控制权");
      break;
    case "control.released":
      stopDrive(true);
      dispatch({ type: "control.released", controllerName: payload.controllerName });
      logEvent("车辆控制权已释放");
      break;
    case "control.denied":
      logEvent(`接管失败：${payload.reason || "已有其他控制者"}`);
      break;
    case "mode.changed":
      stopDrive(true);
      dispatch({ type: "mode", mode: payload.mode });
      logEvent(`工作模式已切换为 ${payload.mode}`);
      break;
    case "safety.estop":
      stopDrive(true);
      dispatch({ type: "estop", active: Boolean(payload.active) });
      logEvent(payload.active ? "紧急停车已锁定" : "紧急停车已解除，当前保持暂停");
      break;
    case "video.ready":
      videoSession.connect(payload, {
        controlUrl: elements.endpoint.value.trim(),
        token: elements.token.value,
        terminalId,
      });
      break;
    case "command.rejected":
      logEvent(`指令被拒绝：${payload.reason || "未知原因"}`);
      break;
    case "server.error":
      logEvent(`服务端错误：${payload.message || "未知错误"}`);
      break;
    default:
      break;
  }
}

function requestControl() {
  if (!transport) {
    logEvent("请先连接小车");
    return;
  }
  if (state.hasControl) {
    stopDrive(true);
    transport.send("control.release", { leaseId: state.leaseId });
  } else {
    transport.send("control.request", {
      terminalName: "Windows 控制终端",
      requestedTtlMs: 1000,
    });
  }
}

function requestMode(mode) {
  if (!state.hasControl || !transport) {
    logEvent("切换模式前需要申请控制权");
    return;
  }
  if (state.emergencyStop) {
    logEvent("请先解除紧急停车");
    return;
  }
  stopDrive(true);
  transport.send("mode.set", createModePayload(mode, state.leaseId));
}

function toggleEmergencyStop() {
  if (!transport) {
    logEvent("未连接，无法发送紧急停车指令");
    return;
  }
  if (state.emergencyStop
      && !window.confirm("解除紧急停车后车辆仍保持暂停，确定解除吗？")) {
    return;
  }
  stopDrive(true);
  transport.send("safety.estop", {
    active: !state.emergencyStop,
    reason: state.emergencyStop ? "operator-reset" : "operator-button",
  });
}

function currentSpeed() {
  return Number(elements["speed-slider"].value) / 100;
}

function startDrive(motion) {
  if (motion === Motion.STOP) {
    stopDrive(true);
    return;
  }
  if (!canSendManualDrive(state) || !transport) {
    logEvent("手动驾驶未启用");
    return;
  }
  if (activeMotion !== motion) {
    stopDrive(false);
    activeMotion = motion;
    setPressedButton(motion);
  }
  sendDrive(motion, true);
  if (driveTimer === null) {
    driveTimer = window.setInterval(() => sendDrive(activeMotion, true), 100);
  }
}

function sendDrive(motion, pressed) {
  if (!transport || (!canSendManualDrive(state) && motion !== Motion.STOP)) {
    return;
  }
  const payload = createDrivePayload({
    direction: motion,
    speed: currentSpeed(),
    leaseId: state.leaseId,
    pressed,
  });
  transport.send("control.command", payload);
}

function stopDrive(forceSend = false) {
  if (driveTimer !== null) {
    window.clearInterval(driveTimer);
    driveTimer = null;
  }
  const wasMoving = activeMotion !== Motion.STOP;
  activeMotion = Motion.STOP;
  setPressedButton(Motion.STOP);
  if ((wasMoving || forceSend) && transport) {
    sendDrive(Motion.STOP, false);
  }
}

function setPressedButton(motion) {
  for (const button of driveButtons) {
    button.classList.toggle("pressed", button.dataset.motion === motion);
  }
}

function render() {
  const statusClass = state.connection.toLowerCase();
  elements["connection-pill"].className = `status-pill ${statusClass}`;
  elements["connection-text"].textContent = connectionLabel(state.connection);
  elements["connect-button"].textContent = state.connection === ConnectionStatus.ONLINE
    ? "重新连接"
    : "连接小车";

  for (const button of modeButtons) {
    button.classList.toggle("active", button.dataset.mode === state.mode);
    button.disabled = !state.hasControl || state.emergencyStop;
  }

  elements["controller-state"].textContent = state.controllerName;
  elements["lease-title"].textContent = state.hasControl ? "本终端正在接管" : "只读观察";
  elements["lease-detail"].textContent = state.hasControl
    ? "释放前其他终端只能观看"
    : "申请控制权后才能切换模式";
  elements["lease-button"].textContent = state.hasControl ? "释放控制" : "申请接管";

  const manualEnabled = canSendManualDrive(state);
  document.querySelector(".manual-card").classList.toggle("enabled", manualEnabled);
  elements["manual-lock"].textContent = manualEnabled
    ? "手动控制已启用 · 松开方向立即停车"
    : "切换到手动模式并取得控制权后启用";
  for (const button of driveButtons) {
    button.disabled = !manualEnabled;
  }

  elements["speed-value"].textContent = `${elements["speed-slider"].value}%`;
  elements["motion-state"].textContent = state.motion;
  elements["vehicle-motion"].textContent = state.motion;
  elements["mode-badge"].textContent = state.mode;

  elements["estop-button"].classList.toggle("latched", state.emergencyStop);
  elements["estop-button"].querySelector("strong").textContent = state.emergencyStop
    ? "解除紧急停车"
    : "紧急停车";

  const confidencePercent = `${Math.round((state.confidence || 0) * 100)}%`;
  const ballLabel = state.ballDetected ? "已锁定" : "未发现";
  elements["ball-state"].textContent = ballLabel;
  elements["confidence-state"].textContent = confidencePercent;
  elements["inference-state"].textContent = `${Math.round(state.inferenceMs || 0)} ms`;
  elements["search-state"].textContent = state.searchPhase || "IDLE";
  elements["fps-badge"].textContent = `${Number(state.cameraFps || 0).toFixed(1)} FPS`;
  elements["latency-badge"].textContent = state.latencyMs == null ? "-- ms" : `${Math.round(state.latencyMs)} ms`;

  elements["motor-state"].textContent = state.motorOnline ? "在线" : "离线";
  elements["motor-state"].className = state.motorOnline ? "good" : "bad";
  elements["uart-state"].textContent = state.uartOnline ? "正常" : "离线";
  elements["uart-state"].className = state.uartOnline ? "good" : "bad";
  elements["vision-target"].textContent = ballLabel;
  elements["vision-fps"].textContent = `${Number(state.cameraFps || 0).toFixed(1)} FPS`;
  elements["vision-confidence"].textContent = confidencePercent;

  renderTargetBox();
}

function renderTargetBox() {
  const box = elements["target-box"];
  if (!state.ballDetected || state.ballX == null || state.ballY == null) {
    box.hidden = true;
    return;
  }
  const width = Math.max(0.04, Number(state.ballWidth || 0.10));
  const height = Math.max(0.04, Number(state.ballHeight || width));
  const left = Math.max(0, Math.min(1 - width, state.ballX - width / 2));
  const top = Math.max(0, Math.min(1 - height, state.ballY - height / 2));
  box.hidden = false;
  box.style.left = `${left * 100}%`;
  box.style.top = `${top * 100}%`;
  box.style.width = `${width * 100}%`;
  box.style.height = `${height * 100}%`;
  elements["target-label"].textContent = `TENNIS ${Math.round(state.confidence * 100)}%`;
}

function connectionLabel(status) {
  return {
    OFFLINE: "未连接",
    CONNECTING: "连接中",
    ONLINE: "在线",
    DEMO: "演示模式",
    ERROR: "连接错误",
  }[status] || status;
}

function logEvent(message) {
  if (!message) {
    return;
  }
  const item = document.createElement("li");
  const time = document.createElement("time");
  const text = document.createElement("span");
  time.textContent = new Date().toLocaleTimeString("zh-CN", { hour12: false });
  text.textContent = message;
  item.append(time, text);
  elements["event-log"].prepend(item);
  while (elements["event-log"].children.length > 40) {
    elements["event-log"].lastElementChild.remove();
  }
}

elements["connect-button"].addEventListener("click", connectRealRobot);
elements["demo-button"].addEventListener("click", connectDemo);
elements["lease-button"].addEventListener("click", requestControl);
elements["estop-button"].addEventListener("click", toggleEmergencyStop);
elements["clear-log"].addEventListener("click", () => elements["event-log"].replaceChildren());
elements["speed-slider"].addEventListener("input", render);

for (const button of modeButtons) {
  button.addEventListener("click", () => requestMode(button.dataset.mode));
}

for (const button of driveButtons) {
  const motion = button.dataset.motion;
  button.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    button.setPointerCapture?.(event.pointerId);
    startDrive(motion);
  });
  button.addEventListener("pointerup", () => stopDrive(true));
  button.addEventListener("pointercancel", () => stopDrive(true));
  button.addEventListener("lostpointercapture", () => stopDrive(true));
}

const keyMotion = new Map([
  ["KeyW", Motion.FORWARD],
  ["ArrowUp", Motion.FORWARD],
  ["KeyS", Motion.REVERSE],
  ["ArrowDown", Motion.REVERSE],
  ["KeyA", Motion.TURN_LEFT],
  ["ArrowLeft", Motion.TURN_LEFT],
  ["KeyD", Motion.TURN_RIGHT],
  ["ArrowRight", Motion.TURN_RIGHT],
]);

window.addEventListener("keydown", (event) => {
  if (event.target instanceof HTMLInputElement) {
    return;
  }
  if (event.code === "Space") {
    event.preventDefault();
    if (!event.repeat && !state.emergencyStop) {
      toggleEmergencyStop();
    }
    return;
  }
  const motion = keyMotion.get(event.code);
  if (motion) {
    event.preventDefault();
    if (!event.repeat) {
      startDrive(motion);
    }
  }
});

window.addEventListener("keyup", (event) => {
  if (keyMotion.has(event.code)) {
    event.preventDefault();
    stopDrive(true);
  }
});

window.addEventListener("blur", () => stopDrive(true));
document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    stopDrive(true);
  }
});
window.setInterval(() => {
  if (transport && state.hasControl) {
    transport.send("control.heartbeat", {
      leaseId: state.leaseId,
      mode: state.mode,
      activeMotion,
    });
  }
}, 250);

window.addEventListener("beforeunload", () => {
  stopDrive(true);
  transport?.close();
});

const savedEndpoint = localStorage.getItem("tennis-endpoint");
if (savedEndpoint) {
  elements.endpoint.value = savedEndpoint;
}

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("./service-worker.js").catch(() => {});
  });
}

logEvent("终端已就绪，当前处于只读安全状态");
render();

if (new URLSearchParams(window.location.search).get("demo") === "1") {
  connectDemo();
}
