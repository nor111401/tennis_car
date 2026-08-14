# 控制终端与树莓派网关设计

更新时间：2026-08-14

状态：终端、认证网关、共享摄像头/识别运行时、JPEG视频和统一电机仲裁已实现；
用户以物理总电源开关作为现场启停手段，并已授权当前部署打开真实电机输出。

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
        └─> JPEG最新帧 ─> 视频WS      │
                                         ├─> 模式仲裁 ─> 安全监控 ─> MotorController ─> UART
Windows/Android ─> WebSocket 网关 ─> 控制权 ─┘
                      ^
                      └─ 遥测、确认、错误和视频端点协商
```

树莓派新增模块建议拆分为：

- `RobotStateStore`：当前模式、运动、目标、控制者和设备健康状态的唯一来源。
- `ControlLeaseManager`：只允许一个终端获得运动控制权。
- `ModeArbiter`：在 AUTO、MANUAL、PAUSED、MANUAL_LOST、EMERGENCY_STOP 间切换。
- `SafetySupervisor`：心跳看门狗、过期指令过滤、急停锁存和故障停车。
- `TelemetryPublisher`：以 10～20Hz 发布状态，不阻塞识别主循环。
- `VideoStreamer`：从同一摄像头帧源编码JPEG并保持单槽最新帧，慢客户端不堆积旧画面。
- `ControlGateway`：WebSocket 会话、认证、协议版本和视频端点协商。

## 3. 实时通道

| 通道 | 协议 | 方向 | 用途 |
|---|---|---|---|
| 当前视频 | WebSocket/JPEG | 树莓派到终端 | 认证、单槽最新帧、默认15FPS、低缓存 |
| 未来视频 | WebRTC/H.264 | 树莓派到终端 | 带宽优化目标，1280×720、30FPS |
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
- `video.request`：请求视频能力与独立认证视频端点。

主要服务端消息：

- `session.welcome`：设备身份和服务端能力。
- `control.granted` / `control.denied` / `control.released`。
- `mode.changed`：只有收到该确认，客户端才更新最终模式。
- `state.telemetry`：识别、运动、设备健康和当前控制者。
- `safety.estop`：急停的权威状态。
- `command.rejected` / `server.error`。
- `video.ready`：返回视频传输类型和独立 `/video` WebSocket 端点。

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
600ms未收到有效心跳
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

`control_terminal/` 已包含可运行 PWA、控制/视频 WebSocket 客户端、按住式控制、心跳、
急停界面和协议测试。`robot_gateway/` 已包含 FastAPI WebSocket入口、共享
摄像头与识别运行时、单槽JPEG视频、控制租约、模式仲裁、600ms心跳看门狗、急停锁存、
遥测发布和 `MotorController` 仲裁。当前部署设置 `TENNIS_MOTOR_ENABLE=1`，但服务仍以
`AUTO` 启动并直接使用识别结果追球；终端取得控制权后可切换为 MANUAL 或 PAUSED。

真实链路已经验证：Windows 终端可与树莓派完成握手、取得租约、切换 MANUAL、发送
FORWARD、REVERSE、STOP、切换 PAUSED 并释放租约；独立认证视频通道已收到有效实时JPEG帧。

在真实车辆测试前仍需：

1. 由用户通过电机物理总电源控制现场启停，并在 Windows 终端验证方向、失联停车和急停。
2. 测量JPEG视频端到端延迟和CPU占用，再决定是否升级WebRTC/H.264。
3. 增加命令过期、串口故障和进程退出强制停车的硬件边界测试。
4. 访问令牌认证已部署；跨互联网使用时仍只通过 VPN，不直接暴露控制端口。
