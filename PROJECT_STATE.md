# 网球小车项目状态与架构回溯

Last updated：2026-08-14

Repository：`D:\liugensheng\tennis`，Git 分支 `main`，尚未配置远程仓库。

用途：这是项目的长期技术事实来源。以后每次修改代码、模型、参数、协议、部署方式或硬件
假设后，都必须同步更新本文件和末尾变更记录。

## 1. 项目目标与当前阶段

最终目标是让 Raspberry Pi 小车自主搜索、识别、接近并在未来拾取网球，同时允许 Windows
和安卓终端实时观看摄像头、查看识别状态、切换自动/手动/暂停模式，并安全地人工介入。

当前已经具备：

- Raspberry Pi 摄像头采集和本地网球识别。
- 颜色候选、轮廓过滤和轻量训练验证器的两级识别。
- 目标连续帧确认、位置判断、接近停车和丢球分阶段搜索。
- 通过 `/dev/serial0` 控制四路电机。
- Windows/安卓共享 PWA 控制终端第一版及通信协议设计。
- 树莓派认证网关已统一接入摄像头、识别遥测、低延迟 JPEG 视频和电机仲裁；当前部署已按用户授权打开真实电机输出。
- 独立二维车辆仿真项目。

## 2. 已知硬件与系统

- 主控：Raspberry Pi 4。
- 原 SD 卡槽已物理脱落，当前从 USB 3.x U 盘启动；不要依赖 SD 卡恢复方案。
- 系统：Raspberry Pi OS，SSH 标识曾显示 Debian 13/Trixie、OpenSSH 10。
- 用户：`pi`。密码、私钥和访问令牌不得写入仓库。
- 主机地址由 DHCP 分配；最近使用过 `192.168.0.108`，不能作为长期固定地址依赖。
- 项目远端目录：`/home/pi/tennis`。
- 摄像头：Picamera2，当前采集 1296×972、40FPS、Sharpness 2.0。
- UART：`/dev/serial0 -> /dev/ttyS0`，115200 baud；串口登录控制台已关闭，UART已开启，
  `pi` 属于 `dialout`。
- 电机模块必须与树莓派共地，信号必须兼容3.3V；电机使用独立电源。
- 树莓派可无显示屏运行。当前程序只在存在 `DISPLAY` 环境变量时打开 OpenCV 本地窗口。

## 3. 仓库结构

| 路径 | 作用 |
|---|---|
| `tennis_ball_rpi.py` | Raspberry Pi 主循环、摄像头、推理、显示和自动电机调用 |
| `tennis_candidate_filter.py` | 颜色候选、形状过滤、距离覆盖率和连续帧确认 |
| `tennis_ball_verifier.py` | 仅依赖 NumPy 的特征提取和逻辑回归推理 |
| `tennis_ball_verifier.npz` | 当前轻量网球验证模型 |
| `tennis_ball_verifier_report.json` | 训练数据规模、参数选择和验证指标 |
| `zmotord_uart.py` | 四路电机协议、动态速度、自动追球和丢球搜索状态机 |
| `train_tennis_verifier.py` | 训练并导出轻量模型 |
| `collect_tennis_training_frames.py` | Raspberry Pi 采集正/负训练画面 |
| `make_training_contact_sheet.py` | 生成训练数据接触表以便人工检查 |
| `test_*.py` | 识别、过滤器和电机状态机测试 |
| `training_data/` | 本地训练素材，不纳入 Git，但禁止当作缓存删除 |
| `control_terminal/` | Windows/安卓共享 PWA 控制终端第一版 |
| `robot_gateway/` | 树莓派认证网关、共享摄像头/识别运行时、视频、控制租约、电机仲裁和看门狗 |
| `requirements-gateway.txt` | 独立网关 Python 依赖，不修改系统 Python 环境 |
| `deploy/` | 已部署的网关 systemd 服务模板和访问令牌说明 |
| `docs/CONTROL_TERMINAL_ARCHITECTURE.md` | 终端协议、模式仲裁和树莓派网关设计 |
| `tennis_robot_sim/tennis_robot_sim/` | 独立二维运动与拾球仿真平台 |
| `configure_rpi_uart.sh` | Raspberry Pi UART 配置脚本 |
| `小车指令.docx`、驱动模块 PDF | 电机命令和硬件协议原始资料 |
| `树莓派串口小车说明.md` | UART 接线及安全说明 |

已清除且不应恢复进 Git 的内容：SSH排查脚本、一次性启动脚本、调试截图、缓存、日志、
本地虚拟环境、临时口令辅助文件及重复模拟器压缩包。

## 4. 当前识别信息流

```text
Picamera2 RGB888画面
→ 可选中心数字变焦
→ 正方形中心裁剪
→ HSV颜色候选框
→ 扩展候选裁剪
→ HOG/颜色/纹理特征逻辑回归验证
→ 颜色和轮廓保守过滤
→ 连续3帧位置确认
→ LEFT / CENTER / RIGHT / LOST
→ MotorController
```

模型选择顺序：

1. 程序目录存在 `.eim` 时使用 Edge Impulse runner。
2. 否则存在 `tennis_ball_verifier.npz` 时使用本地轻量验证器。
3. 两者都不存在时退化为颜色和形状过滤。

目前正式使用第2种路径，不依赖 `.eim`。

## 5. 识别默认参数

`CandidateFilterConfig` 当前默认值：

| 参数 | 当前值 | 含义 |
|---|---:|---|
| confidence_threshold | 0.70 | 训练验证器最低置信度 |
| hue_min / hue_max | 28 / 60 | OpenCV HSV网球色相范围 |
| saturation_min | 70 | 排除灰白和低饱和背景 |
| value_min | 45 | 最低亮度 |
| color_ratio_min | 0.08 | 候选内最低网球色覆盖率 |
| circularity_min | 0.42 | 普通候选最低圆度 |
| trained_confidence_relax | 0.90 | 高置信度轮廓放宽门槛 |
| trained_circularity_min | 0.16 | 地面反射/不完整轮廓的放宽圆度 |
| extent_min / extent_max | 0.30 / 0.92 | 候选填充范围 |
| solidity_min | 0.72 | 最低实心度 |
| aspect_max | 1.85 | 最大长宽比 |
| object_area_min | 0.0005 | 排除像素噪点 |
| crop_expansion | 2.50 | 验证器候选上下文扩展 |
| close_color_coverage | 0.60 | 网球色覆盖达到60%视为太近 |
| confirm_frames | 3 | 连续确认帧数 |
| confirm_max_jump | 0.20 | 相邻确认点最大归一化跳变 |

所有参数可通过同名 `TENNIS_*` 环境变量覆盖，具体名称以
`CandidateFilterConfig.from_environment()` 为准。

## 6. 当前模型和训练数据

- 模型：`tennis_ball_verifier.npz`，特征版本1，32×32输入，3092个特征。
- 算法：HOG、HSV/颜色统计和纹理特征，加线性逻辑回归；推理只依赖 NumPy。
- 训练选择：C=0.003，部署阈值0.70。
- 报告中的训练样本7345、验证样本1187。
- 报告中的时间分段验证：正样本152/152、负样本1035/1035；正样本最低概率0.890，
  负样本最高概率0.249。
- 上述满分仅代表已有采集批次，不能替代跨日期、跨场地、跨光照的独立测试。

本地原始训练素材共：

- 正面三批：201 + 226 + 176 = 603帧。
- 负面三批：125 + 81 + 176 = 382帧。
- 已包含远距离地面网球和橙/黄色足球等困难负样本。

后续每次现场误识别或漏识别都应保存为新批次，并按拍摄批次划分训练/验证，禁止将同一
视频的相邻帧随机拆分造成数据泄漏。

## 7. 电机协议和自动控制

PWM中值1500，合法范围500～2500。当前仅支持：

- `STOP`：广播 `#255P1500T0000!`。
- `FORWARD`：001/003高于1500，002/004低于1500。
- `REVERSE`：001/003低于1500，002/004高于1500，仅供手动控制。
- `TURN_LEFT`：四路均低于1500。
- `TURN_RIGHT`：四路均高于1500。

自动运动默认值：

- 最低运动 PWM：1700/1300，即 speed delta 200。
- 最大正常 PWM：1800/1200，即 speed delta 300。
- 指令持续时间动态范围：300～1000ms；`T1000` 代表1秒。
- 根据目标距图像中心的偏差和目标面积动态插值速度与时间。
- `close_area_ratio=0.44`，目标轮廓面积达到画面44%时停车。
- UART只在 `TENNIS_MOTOR_ENABLE=1` 时打开；默认是安全干运行。

## 8. 丢球分阶段搜索

连续10秒未识别到目标后：

1. 以1900/1100、T250向左转一小步，停车观察0.8秒，共3步。
2. 向右分3步返回中心，每步之间停车0.25秒。
3. 中心稳定0.5秒。
4. 向右分3步搜索，每步停车观察0.8秒。
5. 向左分3步返回中心，再重新等待10秒。

任何搜索阶段确认目标后都会取消搜索；若当时正在旋转，先强制发送 STOP，再进入正常
追球。界面状态包含阶段和 `1/3` 等步数。

## 9. Windows/安卓控制终端第一版

技术形式：无第三方运行依赖的响应式 PWA，Windows 可通过 Edge 安装为独立应用窗口，
安卓以后复用同一终端。源码位于 `control_terminal/`。

已实现：

- 自动、手动、暂停模式界面。
- 控制权申请/释放，客户端不连接时保持只读。
- W/A/S/D、方向按钮和触摸按住式驾驶，松开/失焦/隐藏页面时发 STOP。
- 速度滑块、250ms心跳、紧急停车入口。
- WebSocket控制客户端和认证JPEG视频客户端。
- 识别框、置信度、FPS、延迟、电机和UART状态。
- 演示传输，可在没有树莓派网关时验证完整UI交互。
- Node内置测试，无需安装npm第三方包。

树莓派认证网关已在 `192.168.0.108:8765` 完成真实链路验证：握手、控制租约、
AUTO/MANUAL/PAUSED、安全心跳、急停锁存和手动方向均由唯一权威状态管理。网关后台线程
独占 Picamera2，复用现有轻量验证模型和候选过滤器，并通过独立认证 WebSocket 发送最新
JPEG 帧；慢终端自动丢弃旧帧。识别框已经绘制到当前视频帧，同时发布归一化目标遥测。

`MotorController` 已接入同一仲裁层：AUTO 使用识别观察，MANUAL 使用终端方向和速度，
PAUSED/MANUAL_LOST/EMERGENCY_STOP 强制 STOP。当前 systemd 明确设置
`TENNIS_GATEWAY_BOOT_MODE=AUTO` 和 `TENNIS_MOTOR_ENABLE=1`。重启后直接根据识别结果
自动追球，UART 同时打开；终端取得控制权后可切换 MANUAL 或 PAUSED。用户以电机物理
总电源开关作为现场启停手段。

未实现：WebRTC/H.264、设备发现，以及真实电机的车轮悬空验证。

## 10. 必须保持的安全约束

1. 树莓派是状态和电机命令唯一权威，终端不得直接控制UART。
2. 打开终端不会自动进入手动模式；控制权和模式切换必须明确申请。
3. AUTO/MANUAL切换必须先强制停车并清除旧模式的在途命令。
4. 手动模式超过600ms没有服务端认可的心跳必须停车并进入MANUAL_LOST。
5. 手动断线后不得自动恢复AUTO，必须人工确认。
6. 急停状态在服务端锁存，优先于全部自动和手动指令。
7. 代码层电机输出默认关闭；当前 systemd 部署仅因用户明确授权而设置为开启。
8. 当前现场操作按用户方案由电机物理总电源开关控制启停，用户选择跳过车轮悬空测试。

## 11. 测试和部署

Python测试：

- `test_zmotord_uart.py`：17项电机协议、动态控制、手动倒车和分阶段搜索测试。
- `test_tennis_candidate_filter.py`：颜色/轮廓、困难负样本、连续帧和距离判断测试。
- `test_tennis_ball_verifier.py`：特征、裁剪和导出模型加载测试。
- 本机默认 Python 缺少 `cv2`，因此完整Python测试需在安装OpenCV的环境或树莓派运行。

终端测试：

```powershell
cd control_terminal
npm run check
npm test
npm start
```

2026-08-14实际验证结果：JavaScript语法检查通过；Node协议/安全状态测试8/8通过；首页和
PWA清单本地HTTP烟雾测试通过；Windows Edge 1440×1000无头渲染视觉检查通过；现有
电机、网关和轻量验证器Python测试36/36在Windows和树莓派均通过。Windows到树莓派的
认证控制链路通过；认证视频链路收到有效实时JPEG帧，最近抽样帧大小44729字节、识别遥测
22.2 FPS。候选过滤器
测试因本机默认Python缺少`cv2`未运行，该限制不是此次终端修改造成的。
切换为 AUTO 默认启动后，本机上述 Python 测试36/36再次通过，树莓派
`RuntimeSettingsTests` 2/2通过。
增加手动倒车后，本机和树莓派 Python 测试均38/38通过，Node测试8/8通过；测试使用内存
串口，未向实车自动发送倒车命令。

网关部署状态：树莓派 `/home/pi/tennis/.venv-gateway` 已安装 FastAPI、Uvicorn 和 WebSockets；
`tennis-robot-gateway.service` 已启用并正在运行，开机自动启动。访问令牌仅保存在树莓派
`/etc/tennis-robot-gateway.env`，权限为 `root:root 600`；无令牌 WebSocket 连接已验证会被拒绝。
服务监听局域网 TCP 8765。2026-08-14 用户确认电机具备物理总电源开关并授权跳过悬空
测试，当前 systemd 模板已切换为 `TENNIS_MOTOR_ENABLE=1` 并以 `AUTO` 启动。重启后实测
`mode=AUTO`、`motorOutputEnabled=true`、`cameraOnline=true`、`videoReady=true`、
`runtimeError=null`、`UART_FD_OPEN`、`throttled=0x0`。

树莓派安全干运行：

```bash
cd /home/pi/tennis
TENNIS_MOTOR_ENABLE=0 python3 tennis_ball_rpi.py
```

真实电机运行只在硬件安全确认后使用：

```bash
cd /home/pi/tennis
TENNIS_MOTOR_ENABLE=1 python3 tennis_ball_rpi.py
```

## 12. 已知问题与下一步

1. 用户通过 Windows 终端验证真实手动方向、STOP、心跳失联停车和模式切换；现场启停由
   电机物理总电源开关控制。
2. 测量当前 JPEG WebSocket 的端到端延迟和CPU占用；需要更低带宽时升级为WebRTC/H.264。
3. 增加命令发送时间过期、串口写故障和进程退出强制停车的硬件边界测试。
4. 增加设备发现，避免依赖DHCP IP；互联网访问仍只允许走VPN。
5. 为自动拾球机构扩展对准、拾取、确认和失败恢复状态。

## 13. 变更记录

- 2026-08-10 `019d658`：保存当前网球识别、电机控制、训练和模拟器基线。
- 2026-08-10 `a91dcd2`：丢球搜索从整段旋转改为每侧3次、每次350ms的分阶段扫描。
- 2026-08-14：清除缓存、调试截图、过时SSH脚本、一次性启动脚本、本地虚拟环境、日志、
  临时凭据辅助文件和重复模拟器压缩包；保留训练数据、模型和协议资料。
- 2026-08-14：新增 `control_terminal/` PWA第一版、演示模式、WebSocket/WebRTC客户端、
  安全交互、协议测试和 `docs/CONTROL_TERMINAL_ARCHITECTURE.md`。树莓派网关尚未实现。
- 2026-08-14：新增 `robot_gateway/` WebSocket干运行网关、11项安全核心测试、独立依赖和
  systemd模板；部署到树莓派虚拟环境并通过真实Windows到树莓派控制链路测试。真实视频、
  识别和电机未接入，常驻开机服务等待认证与明确授权。
- 2026-08-14：用户批准带访问令牌的局域网常驻网关；令牌仅保存在树莓派 root 权限环境
  文件中。systemd 启动前以特权检查令牌文件，网关进程仍以普通 `pi` 用户运行。服务已
  `enabled + active`；真实验证无令牌连接被拒绝、带令牌的完整干运行控制链路通过。
- 2026-08-14：网关统一接入 Picamera2、现有识别模型、遥测、单槽低缓存 JPEG 视频和
  `MotorController` 仲裁；Windows终端显示真实画面。树莓派健康检查和认证视频/控制链路
  均通过，真实电机保持关闭，等待车轮悬空验证。
- 2026-08-14：用户说明电机具备物理总电源开关并明确授权跳过悬空测试；systemd 部署切换
  为 `TENNIS_MOTOR_ENABLE=1` 和 `TENNIS_GATEWAY_BOOT_MODE=AUTO`，启动后直接自动追球，
  并允许用户从 Windows 终端接管。
- 2026-08-14：增加手动 `REVERSE` 全链路；001/003使用低PWM、002/004使用高PWM，复用
  手动速度滑块和600ms心跳看门狗。自动追球不使用倒车，测试未向实车发送运动命令。
- 2026-08-14：针对地面摩擦导致搜索旋转轮子偶发不动，将丢球搜索提高为1900/1100、
  单步缩短为T250、观察延长为0.8秒、返回暂停0.25秒、中心稳定0.5秒。

## 14. 每次修改后的更新检查

- 本文件日期和变更记录是否更新。
- 当前参数、模式、协议字段和部署命令是否仍与代码一致。
- 新增或删除文件是否反映在仓库结构中。
- 真实通过的测试及未运行原因是否记录。
- 树莓派与终端的已完成/未完成边界是否清楚。
- 是否意外写入密码、私钥、令牌、固定Wi-Fi信息或其他秘密。
