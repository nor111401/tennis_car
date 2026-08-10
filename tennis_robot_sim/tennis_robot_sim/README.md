# 自动网球捡球小车 —— 二维仿真平台（第一阶段）

面向树莓派 + STM32 差速小车的**第一阶段二维软件仿真底座**。在普通 Windows
电脑上即可运行，用于在真实小车到位前验证运动学、摄像头视野、目标可见性与
简化收集等核心逻辑，并为后续路径规划、目标记忆、状态机与真实接口接入预留接口。

> 本阶段**不包含**：YOLO/神经网络、图像采集、ROS、SLAM、路径规划算法、
> 多目标数据关联、卡尔曼滤波、串口/CAN/RS485、STM32 固件、树莓派 GPIO、
> 物理碰撞与收集机构动力学等。这些仅预留抽象接口，不实现具体算法。

## 1. 环境要求

- Python 3.10+（本工程在 Python 3.13 下验证）
- Windows / Linux / macOS 均可运行

## 2. 安装

建议使用虚拟环境：

```bash
cd tennis_robot_sim
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

依赖仅三个：`numpy`（数值计算）、`pygame`（显示/输入）、`pytest`（测试）。

## 3. 运行

```bash
python main.py
```

- 弹出 1200×800 的窗口，显示二维网球场、小车、网球与摄像头扇形视野；
- 左侧为仿真画面，右侧为实时状态面板，底部为操作提示；
- 按 `ESC` 或关闭窗口退出。

无显示器 / CI 冒烟测试：

```bash
SDL_VIDEODRIVER=dummy TENNIS_SIM_AUTOQUIT_FRAMES=60 python main.py
```

（渲染 60 帧后自动退出，用于验证主循环可正常初始化与运行。）

## 4. 键盘操作

| 按键 | 功能 |
| ---- | ---- |
| `W` | 前进 |
| `S` | 后退 |
| `A` | 左转 |
| `D` | 右转 |
| `空格` | 立即停止 |
| `R` | 重置小车与网球 |
| `B` | 重新随机生成网球 |
| `C` | 手动收集当前满足条件的网球 |
| `P` | 暂停 / 继续仿真 |
| `V` | 显示 / 隐藏摄像头视野 |
| `G` | 显示 / 隐藏网格 |
| `T` | 在可见网球间循环切换选中目标 |
| `F1` | 演示模式：小车自动绕圈（用于诊断输入/仿真是否正常） |
| `ESC` / `Q` | 退出程序 |

支持多键组合：`W + A` 前进左转、`W + D` 前进右转 等。

> 持续按键通过 KEYDOWN/KEYUP 事件追踪实现（`pygame.key.get_pressed()`
> 返回按扫描码索引的数组，不能直接用 `K_*` 常量索引），并带
> `get_pressed` 物理扫描码兜底，与键盘布局无关。

### 键盘无法控制？——界面自带诊断

窗口打开后，右侧状态面板会实时显示三行输入诊断：

| 项目 | 含义 |
| ---- | ---- |
| `窗口焦点` | 有 / 无 —— 窗口是否拥有键盘焦点 |
| `键盘事件` | 收到按键事件的累计次数（0 = 从未收到） |
| `按键` | `W A S D SP` 的实时状态（大写=按下，小写=未按） |

排查步骤：
1. **看窗口标题**是否为 `v1.2`（确认运行的是最新代码）；
2. 按一次 `W`，若状态面板“键盘事件”次数增长、`按键` 中 `W` 变为大写，说明
   事件已送达，小车应会前进；
3. 若“键盘事件”始终为 0，说明窗口未获得键盘焦点 —— **点击窗口后再操作**
   （或按 `Alt+Tab` 切换回来）；窗口顶部也会出现红色提示横幅；
4. 按 `F1` 开启演示模式，小车应自动绕圈：若演示能转、WASD 不响应，则问题
   仅在键盘事件送达环节。

## 5. 配置说明

所有参数位于 `config/default_config.json`，修改后重启程序生效。

| 配置段 | 关键参数 | 说明 |
| ------ | -------- | ---- |
| `simulation` | `fixed_dt` / `time_scale` | 固定仿真步长（秒）/ 时间倍速 |
| `window` | `width` / `height` / `fps` / `panel_width` | 窗口尺寸、目标帧率、右侧面板宽度 |
| `court` | `width_m` / `height_m` / `grid_step_m` | 场地长宽（米）、网格间距 |
| `robot` | `initial_x/y/theta_deg` / `wheel_base` / `wheel_radius` / `length` / `width` / `max_linear_speed` / `max_angular_speed` | 小车初始位姿与运动学参数 |
| `camera` | `field_of_view_deg` / `max_detection_distance` / `min_detection_distance` / `camera_offset_x/y` | 视野角、检测距离范围、摄像头在车体系中的偏移 |
| `balls` | `count` / `radius_m` / `random_seed` / `spawn_margin_m` | 网球数量、半径、随机种子、生成边距 |
| `collection` | `distance_m` / `angle_deg` / `auto_collect` | 收集半径、收集锥角、是否自动收集 |
| `logging` | `dir` / `console_level` / `file_level` | 日志目录与级别 |

配置加载时会做合法性检查（长度 > 0、视场角在 `(0,180)`、最大检测距离大于最小
检测距离、小车初始位置位于场地内等），不合法时给出明确错误信息。

## 6. 单位与坐标约定

- 长度统一为**米**，角度统一为**弧度**（theta 逆时针为正，范围 `[-pi, pi)`）；
- 世界坐标系：原点在场地左下角，x 向右，y 向上；
- 屏幕坐标系：原点在窗口左上角，x 向右，y 向下（Pygame 约定）；
- 世界↔屏幕坐标转换由 `utils/coordinate_transform.py` 负责（保持纵横比居中）。

### 左右轮速度单位

`left_wheel_speed` / `right_wheel_speed` 单位为**米/秒（车轮线速度）**。
需要车轮角速度（rad/s）时调用 `robot.wheel_angular_speeds()`。

### 摄像头方位角（bearing）符号约定

- `bearing` 单位为弧度，取值 `[-pi, pi)`；
- **正号 = 目标在机器人前进方向的左侧（逆时针）**，负号 = 右侧；
- 与 theta 逆时针为正的数学约定保持一致。

### 收集锥角约定

`collection.angle_deg` 为**完整锥角**：网球方位角满足
`|bearing| <= angle_deg / 2` 且距离 `<= distance_m` 时才可收集。

## 7. 网球状态与显示规则

`Ball.status` 取值为 `BallStatus` 枚举：

| 状态 | 含义 | 画面显示 |
| ---- | ---- | -------- |
| `UNSEEN` | 从未进入过视野 | 普通浅色实心圆 |
| `VISIBLE` | 当前在摄像头视野内 | 黄色高亮 + 白色外圈 |
| `HIDDEN` | 曾经进入过视野、当前不在视野内 | 灰色轮廓 + 中心点 |
| `COLLECTED` | 已被收集 | 隐藏 |

- `Ball.was_seen` 记录“历史是否进入过视野”（用于“历史已发现”统计）；
- 选中的测试目标（`T` 键切换）用洋红色圆环 + 编号突出显示；
- 网球的真实状态与可见性、是否被收集是分开维护的。

## 8. 目录结构

```text
tennis_robot_sim/
├── main.py                     # 程序入口：主循环、固定步长推进、按键分发
├── requirements.txt
├── pyproject.toml              # pytest 配置
├── config/
│   └── default_config.json     # 全部仿真参数
├── simulator/                  # 核心仿真（不依赖 pygame，可单测）
│   ├── config.py               # 配置加载与合法性校验
│   ├── types.py                # 共享数据类型（Pose/RobotState/BallDetection/…）
│   ├── court.py                # 二维网球场
│   ├── ball.py                 # 网球模型与随机生成
│   ├── robot.py                # 差速小车运动学
│   ├── camera.py               # 扇形视野摄像头（numpy 矢量化）
│   ├── collection.py           # 简化收集判定
│   ├── controller.py           # BaseController 抽象 + KeyboardController
│   ├── world.py                # 世界状态、可见性维护、收集、统计
│   └── simulation.py           # 固定步长仿真推进
├── ui/                         # Pygame 显示与输入
│   ├── renderer.py             # 画面绘制
│   ├── input_handler.py        # 键盘输入 -> FrameInput
│   └── status_panel.py         # 右侧状态面板
├── utils/
│   ├── geometry.py             # 角度归一化、clamp、向量旋转
│   ├── coordinate_transform.py # 世界/屏幕坐标互转
│   └── logger.py               # 控制台 + 文件日志
└── tests/                      # pytest 单元测试（无界面）
    ├── test_robot_kinematics.py
    ├── test_camera_visibility.py
    ├── test_coordinate_transform.py
    ├── test_collection.py
    ├── test_world.py
    └── test_config.py
```

## 9. 单元测试

```bash
pytest
```

覆盖：差速运动学（直线/原地转向/曲线/零速度/限幅/角度归一化/边界）、
摄像头视野（正前方/视场角外/最大最小距离/旋转变化/边界角度/bearing 符号）、
坐标转换（正反变换/四角映射/往返一致）、收集判定（距离+角度/重复收集/自动收集）、
世界状态（生成范围与避让/可复现/可见性流转/重置/仿真推进）与配置校验。

## 10. 接口预留

为后续阶段预留的抽象层（本阶段仅实现键盘控制）：

```python
class BaseController:
    def update(self, observation, dt): ...   # 观测 -> 目标速度

robot.set_velocity(v, omega)     # 线速度 + 角速度控制
robot.set_wheel_speeds(l, r)     # 左右轮速度控制
robot.stop()
robot.get_pose()

camera.detect(robot_pose, world_balls)   # 预留检测接口（= get_visible_balls）

world.get_active_balls()
world.get_visible_balls()
world.collect_ball(ball_id)
world.reset()
```

后续可平滑接入：`TargetFollowingController`、`PathPlanningController`、
`RealMotorController`，以及目标记忆、识别误差模拟、状态机控制等模块。

## 11. 本阶段未实现（后续阶段）

- 多网球目标记忆与数据关联（仅保留 `was_seen` 历史标志）；
- 路径规划（A* / RRT / 遗传算法等）；
- 识别误差模拟（漏检、误检、噪声、置信度）；
- 状态机控制；
- 真实树莓派程序 / 摄像头 / 电机驱动接口接入。
