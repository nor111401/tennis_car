# 控制终端与树莓派网关设计

更新时间：2026-08-14

状态：终端第一版已实现；树莓派实时网关待开发。

## 1. 目标和边界

Windows/安卓终端是观察和人工介入界面，不是小车自动算法的运行位置。树莓派在没有任何
客户端连接时仍能执行识别、搜索和追球。客户端不能直接访问 UART，也不能绕过安全层。

控制优先级固定为：

```text
紧急停车 > 失联停车 > 手动控制 > 自动追球 > 丢球搜索
```

## 2. 组件架构

```text
摄像头 ─┬─> 识别管线 ─> 自动状态机 ─┐
        └─> H.264 编码 ─> WebRTC     │
                                         ├─> 模式仲裁 ─> 安全监控 ─> MotorController ─> UART
Windows/Android ─> WebSocket 网关 ─> 控制权 ─┘
                      ^
                      └─ 遥测、确认、错误和 WebRTC 信令
```

树莓派新增模块建议拆分为：

- `RobotStateStore`：当前模式、运动、目标、控制者和设备健康状态的唯一来源。
- `ControlLeaseManager`：只允许一个终端获得运动控制权。
- `ModeArbiter`：在 AUTO、MANUAL、PAUSED、MANUAL_LOST、EMERGENCY_STOP 间切换。
- `SafetySupervisor`：心跳看门狗、过期指令过滤、急停锁存和故障停车。
- `TelemetryPublisher`：以 10～20Hz 发布状态，不阻塞识别主循环。
- `VideoStreamer`：从同一摄像头帧源进行一次 H.264 编码并通过 WebRTC发送。
- `ControlGateway`：WebSocket 会话、认证、协议版本和 WebRTC 信令。

## 3. 实时通道

| 通道 | 协议 | 方向 | 用途 |
|---|---|---|---|
| 视频媒体 | WebRTC/H.264 | 树莓派到终端 | 1280×720、目标30FPS、低缓存 |
| 控制与状态 | WebSocket | 双向 | 模式、方向、心跳、遥测和确认 |
| 初始配置 | HTTP/HTTPS | 双向 | 设备信息、认证和非实时参数 |

识别框不必烧录到视频。树莓派发送归一化目标中心和宽高，终端按时间戳叠加，可以降低
编码开销并允许用户隐藏调试信息。

## 4. 协议外壳

所有 WebSocket 消息使用同一外壳：

```json
{
  "version": 1,
  "type": "control.command",
  "sequence": 1024,
  "terminalId": "持久化终端标识",
  "sentAt": 1786700000000,
  "payload": {}
}
```

服务端必须按每个终端检查递增序号，并拒绝时间戳过旧、控制权不匹配或协议版本不支持的
消息。客户端发送时间仅用于诊断，最终超时判断使用服务端单调时钟。

主要客户端消息：

- `session.hello`：认证和能力协商。
- `control.request` / `control.release`：申请或释放控制权。
- `control.heartbeat`：250ms一次，维持手动控制租约。
- `mode.set`：申请切换 AUTO、MANUAL 或 PAUSED。
- `control.command`：方向、0～1速度、按压状态和租约ID。
- `safety.estop`：紧急停车锁存或申请解除。
- `video.request` / `video.answer` / `video.ice`：WebRTC 信令。

主要服务端消息：

- `session.welcome`：设备身份和服务端能力。
- `control.granted` / `control.denied` / `control.released`。
- `mode.changed`：只有收到该确认，客户端才更新最终模式。
- `state.telemetry`：识别、运动、设备健康和当前控制者。
- `safety.estop`：急停的权威状态。
- `command.rejected` / `server.error`。
- `video.offer` / `video.ice`。

## 5. 模式切换时序

AUTO 转 MANUAL：

```text
终端申请控制权
→ 服务端授权租约
→ 终端申请 MANUAL
→ 服务端输出 STOP
→ 清除自动控制的在途运动
→ 状态切为 MANUAL
→ 返回 mode.changed
→ 接受按住式方向指令
```

MANUAL 转 AUTO：

```text
终端先发送 STOP
→ 申请 AUTO
→ 服务端再次强制 STOP
→ 清除手动指令
→ 确认摄像头、识别和 UART 健康
→ 重置或恢复自动状态机
→ 返回 mode.changed
```

手动控制断线：

```text
500ms未收到有效心跳
→ 立即 STOP
→ 切换 MANUAL_LOST
→ 清除控制租约
→ 不自动恢复 AUTO
→ 等待经过认证的终端明确选择
```

## 6. 遥测字段

第一版终端支持以下驼峰命名字段：

```json
{
  "mode": "AUTO",
  "motion": "FORWARD",
  "emergencyStop": false,
  "controllerName": "无人接管",
  "ballDetected": true,
  "confidence": 0.91,
  "ballX": 0.43,
  "ballY": 0.61,
  "ballWidth": 0.12,
  "ballHeight": 0.12,
  "searchPhase": "TRACKING",
  "cameraFps": 39.2,
  "inferenceMs": 18,
  "latencyMs": 96,
  "motorOnline": true,
  "uartOnline": true
}
```

坐标和尺寸均按0～1归一化。视频和遥测后续都应加入采集时间戳与帧编号，以正确同步
识别框和画面。

## 7. 第一版实现与待办

`control_terminal/` 已包含可运行 PWA、演示传输、WebSocket 客户端、WebRTC 客户端、
按住式控制、心跳、急停界面和协议测试。

在真实车辆测试前仍需：

1. 把现有识别循环重构为可发布帧与遥测、但不改变识别算法的服务。
2. 在树莓派实现上述网关、安全监控和权威状态存储。
3. 给 `MotorController` 增加明确的 REVERSE 手动动作；当前自动程序没有倒车路径。
4. 实现服务端控制租约、500ms失联停车和急停锁存测试。
5. 在车轮悬空条件下测试模式切换，再进行落地低速测试。
6. 测量端到端视频延迟，并调整编码分辨率、码率和缓冲策略。
7. 加入认证；跨互联网使用时只通过 VPN，不直接暴露控制端口。
