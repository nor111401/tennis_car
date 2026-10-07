# 网球小车项目状态与架构回溯

Last updated：2026-10-07（Asia/Shanghai；midtest_stable版本快照）

Repository：`D:\code\python\tennis`，Git 分支 `main`；远程`origin`为
`https://github.com/nor111401/tennis_car.git`（用户2026-10-07指定）。

本轮版本快照标签：`midtest_stable`，用于保存方向记忆搜索实现前的当前基线。
包含正式模型、源代码、终端、部署模板、测试和技术说明；训练原图、缓存、本地虚拟环境和
候选模型保持忽略且不删除。上传只推送`main`和此指定标签，不强制覆盖历史，不上传其他标签；
成功须以Git推送结果及远端分支/标签对象核对为准，不能把本地提交说成已上传。

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
- 树莓派认证网关已统一接入摄像头、识别遥测、低延迟 JPEG 视频和电机仲裁；当前真实电机
  输出已开启，持久systemd覆盖使服务以PAUSED启动；已接线的HC-SR04现按用户要求关闭，
  AUTO不再使用超声波避障。实车避障转向尚未验证。
- 独立二维车辆仿真项目。

## 2. 已知硬件与系统

- 主控：Raspberry Pi 4。
- 原 SD 卡槽已物理脱落，当前从 USB 3.x U 盘启动；不要依赖 SD 卡恢复方案。
- 系统：Raspberry Pi OS，SSH 标识曾显示 Debian 13/Trixie、OpenSSH 10。
- 用户：`pi`。密码、私钥和访问令牌不得写入仓库。
- 主机地址由 DHCP 分配；2026-10-05当前地址为`10.23.90.9`，此前使用过
  `10.183.95.9`和`192.168.0.108`，不能作为长期固定地址依赖。
- 项目远端目录：`/home/pi/tennis`。
- 摄像头：Picamera2；独立脚本默认采集1296×972、40FPS，常驻网关当前由硬件缩放直接输出
  960×720、30FPS、Sharpness 2.0，识别使用中间720×720正方形区域并发送最大640像素JPEG。
- UART：`/dev/serial0 -> /dev/ttyS0`，115200 baud；串口登录控制台已关闭，UART已开启，
  `pi` 属于 `dialout`。
- 追踪/捡球信号选用 BCM17（40针排针物理11），与 UART BCM14/15（物理8/10）不冲突；
  追踪输出低电平，捡球输出高电平（约3.3V）。服务账户需要 `gpio` 组权限；此脚仅作逻辑
  信号，外接控制板须共地并兼容3.3V，不能直接驱动电机或其他大电流负载。
- 拟增加用户所给新版 HC-SR04/CS100A 宽电压超声波模块。该资料标称 DC 3–5.5V，接线
  方案为模块 VCC 接树莓派3.3V（物理1或17）、Trig接BCM23（物理16）、Echo接BCM24
  （物理18）、GND接物理6，先断电接线并核对实物。资料原理图显示芯片数字电源接VCC，
  因此仅对该型号按3.3V供电时的Echo直连设计；若改为5V供电，Echo必须先降压。当前
  用户2026-10-05报告已接线；远端真实模块12次静止读数约74.82～74.89cm，另6次复测
  约74.81～74.89cm，后台线程读数约74.83cm且无错误。尚未独立测量VCC/Echo电压、
  用户将障碍物放在自估约15～20cm处后，12次真实读数为21.50～21.54cm，高于
  20cm进入阈值；再移近后12次为16.75～16.79cm，稳定低于进入阈值；再移远后12次
  为40.45～40.49cm，稳定高于30cm退出阈值。测后BCM23/24均恢复输入。
  2026-10-05追球现场出现`OBSTACLE SENSOR WAIT`后，停机检查发现当前空旷场景连续20次
  Echo长脉冲均约46.8ms；旧代码只认60～72ms为超范围，因而误判为故障。现将36～72ms
  长脉冲及完整80ms周期无回波视为无近障碍；实物新代码连续12次返回`inf/NORMAL`。
  尚未独立测量VCC/Echo电压或驱动车轮；车上已安装关闭避障且开机PAUSED的持久配置。
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
| `zmotord_uart.py` | 四路电机协议、自动恒定PWM、可见球小步对准、自动追球和丢球搜索状态机 |
| `robot_gateway/obstacle.py` | HC-SR04内核时间戳测距采样与AUTO避障状态机 |
| `deploy/tennis-robot-gateway-obstacle-commissioning.conf` | 本车持久避障关闭与PAUSED开机覆盖，已部署 |
| `train_tennis_verifier.py` | 训练并导出轻量模型 |
| `collect_tennis_training_frames.py` | Raspberry Pi按光照条件采集正/负训练画面并记录会话元数据 |
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
→ 候选框附近高亮低饱和像素补偿
→ 用线性复杂度距离变换连接邻近高光，避免大球框触发超大形态学卷积核
→ 每帧复用颜色/高光掩膜，疑似强光时低分辨率圆候选
→ 小颜色种子邻近高光区域候选补全
→ 大候选替换其覆盖的小颜色种子，避免同一球产生多个候选
→ 对拉长的合并色块在局部高分辨率ROI内再次执行圆检测
→ 拉长的连通色块内保留多个独立圆候选；至少两个圆通过验证后才替换原色块
→ 颜色和轮廓保守过滤
→ 同一物理球的颜色/强光候选按空间关系合并
→ 每个可见网球建立独立轨迹，逐球关联、平滑和当前帧局部恢复
→ 面积明显更大的轨迹连续3帧后才切换为车辆主追踪目标
→ 连续3帧位置确认
→ LEFT / CENTER / RIGHT / LOST
→ 已确认目标的下沿位置（可见球达到80%触发固定收集窗口；空画面仍用于诊断）
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
| trained_circularity_min | 0.00 | 高置信度模型结果可忽略暗光残缺轮廓圆度 |
| extent_min / extent_max | 0.30 / 0.92 | 候选填充范围 |
| trained_extent_min / trained_extent_max | 0.25 / 0.98 | 高置信度暗光残缺轮廓填充范围 |
| solidity_min | 0.72 | 最低实心度 |
| trained_solidity_min | 0.45 | 高置信度暗光残缺轮廓最低实心度 |
| aspect_max | 1.85 | 最大长宽比 |
| trained_aspect_max | 2.50 | 高置信度暗光横向残缺轮廓最大长宽比 |
| object_area_min | 0.0005 | 排除像素噪点 |
| crop_expansion | 2.50 | 验证器候选上下文扩展 |
| glare_value_min | 180 | 强光高光像素的最低 HSV 明度 |
| glare_saturation_max | 75 | 强光高光像素的最高 HSV 饱和度 |
| glare_search_ratio | 0.45 | 在候选框外搜索相邻高光区域的比例 |
| glare_confidence_threshold | 0.55 | 强光圆候选进入验证的最低模型置信度 |
| glare_coverage_min | 0.35 | 圆候选内颜色或高光证据的最低覆盖率 |
| glare_circle_max_side | 240 | 强光圆检测使用的最大边长，降低每帧 Hough 开销 |
| close_color_coverage | 0.60 | 网球色覆盖达到60%视为太近 |
| confirm_frames | 3 | 连续确认帧数 |
| confirm_max_jump | 0.20 | 相邻确认点最大归一化跳变 |

所有参数可通过同名 `TENNIS_*` 环境变量覆盖，具体名称以
`CandidateFilterConfig.from_environment()` 为准。

## 6. 当前模型和训练数据

- 模型：`tennis_ball_verifier.npz`，特征版本1，32×32输入，3092个特征。
- 算法：HOG、HSV/颜色统计和纹理特征，加线性逻辑回归；推理只依赖 NumPy。
- 训练选择：C=0.03，部署阈值0.70；最终部署模型在参数选择结束后用全部已审核会话重训。
- 训练按完整拍摄会话隔离，不再把同一视频的相邻帧拆到训练集和验证集。当前参数选择阶段
  使用603个正帧、206个负帧和带框样本训练，完整留出最新176个暗光正帧及最新176个困难
  负帧；最终部署训练含19888个增强样本，其中15190个负样本、4698个正样本。
- 光照增强覆盖原图、暗光、过曝、暖色、冷色和局部不均匀光照；困难负样本也同步增强，
  避免模型把单纯亮度或色温当作正类证据。
- 完整会话留出验证共1886个候选裁剪：正样本175/176达到0.70门槛（召回99.4%）；
  负候选1453/1710被正确拒绝，257个达到门槛（候选级误报率15.0%）。这些负候选包含从
  正样本画面提取的背景和随机困难裁剪，不等同于整帧最终误报率，但证明旧的相邻帧100%
  指标过于乐观，也说明仍需更多跨场景困难负样本。最终部署模型重新纳入留出会话后，全部
  已知增强训练样本在0.70门槛下完全分离；该训练分数不能替代新场地独立测试。
- 暗光近地网球批次离线对比：旧模型0/176达到0.70门槛，新模型176/176达到门槛，
  新模型最低概率0.984；部署后的实时遥测置信度0.955、识别耗时38ms。
- 上述结果仅代表已有采集批次；目前尚无足够的跨日期、跨场地、逆光和多色温独立会话，
  不能宣称在所有光照条件下可靠。

本地原始训练素材共：

- 正面四批：201 + 226 + 176 + 176 = 779帧；新增批次为暗光近地网球。
- 负面三批：125 + 81 + 176 = 382帧。
- 带框标注批次`20260917_two_overlapping_balls`：原始双球画面1张及水平镜像1张，每张明确
  标注2个`tennis_ball`，训练器按4个独立目标生成24个增强正样本，不把合并色块标成一个球。
- 已包含远距离地面网球和橙/黄色足球等困难负样本。
- 新采集器使用`--condition normal|low_light|bright|backlight|warm|cool|mixed`把光照标签写入
  会话目录名和`session.json`；旧会话没有元数据，在报告中标记为`unlabeled`。

后续每次现场误识别或漏识别都应保存为新批次，并按拍摄批次划分训练/验证，禁止将同一
视频的相邻帧随机拆分造成数据泄漏。

## 7. 电机协议和自动控制

PWM中值1500，合法范围500～2500。当前仅支持：

- `STOP`：广播 `#255P1500T0000!`。
- `FORWARD`：001～004全部高于1500。
- `REVERSE`：001～004全部低于1500，仅供手动控制。
- `TURN_LEFT`：001/003低于1500，002/004高于1500。
- `TURN_RIGHT`：001/003高于1500，002/004低于1500。

此映射依据2026-09-30当前实车安装方向修正：原前进实际右转、原后退实际左转、原右转实际
前进、原左转实际后退。修正同时作用于手动和自动控制；`STOP`协议保持不变。新映射已通过
串口字节测试，但尚未重新进行真实车轮方向验证。

自动运动默认值：

- 当前帧通过颜色/形状/模型筛选、但尚未连续3帧确认的主候选，不提供前进或收集几何；
  搜索时先强制STOP并进入最多1秒的`TARGET VERIFY`，停稳0.15秒后的新确认帧才恢复追踪。
- 追球前进及左右转向使用与手动100%相同的`speed_delta=1000`，PWM为2500/500；方向组合与
  手动模式共用`commands_for_motion()`。自动模式不使用倒车。
- 前进指令仍根据球面积在300～1000ms间变化；可见球的对准转向改为120～220ms单次脉冲，
  按归一化球心距画面中心的误差线性取值，转完强制STOP、静置0.15秒并等待新画面后才决定
  下一步。远球球心落在中心±0.06内时前进；球框下沿≥0.80的近区放宽到中心±0.15，
  小幅偏差不再转向，超出该范围仍小步对准。新鲜近球观察进入容差时可提前结束正在进行的
  转向，但仍先STOP、静置0.15秒并等待停稳后的新画面，不跳过新帧检查。
  近区是图像位置近似，非厘米测距；可通过`TENNIS_NEAR_AIM_MIN_BOTTOM`（默认0.80，
  范围0.5～收集下沿阈值）及`TENNIS_NEAR_AIM_DEADBAND`（默认0.15，范围普通容差～0.25）调节。
  不再用画面中间1/3宽区直接放行。网关传入画面时间戳，
  同一旧画面不会重复转向。上述默认值可通过`TENNIS_AIM_DEADBAND`、
  `TENNIS_AIM_TURN_MIN_MS`、`TENNIS_AIM_TURN_MAX_MS`和`TENNIS_AIM_SETTLE_SECONDS`调节。
  这些脉冲只影响可见球对准，不改手动驾驶或丢球搜索T500。
- `close_area_ratio=0.44`，尚未收集时目标轮廓面积达到画面44%则停车；收集中视觉过近不打断窗口。
- 已确认的可见球框下沿达到归一化高度0.80、球心在近区中心±0.15内且允许前进时，
  立即进入PICKUP，车辆固定直行3秒、BCM17同时高电平3秒。从近处起步也可触发，
  不依赖远区接近历史，不再等待球消失或空帧。启动前仍要求验证通过、未达到面积停车阈值，
  对准转向后仍先STOP、静置并等待新画面。
  启动后的固定期限优先于视觉追踪：目标重现、消失、半球拒绝、待确认、偏移、视觉过近
  均不会转向、取消或刷新计时。PAUSED、MANUAL、急停、相机异常/观察超时、UART故障
  以及未来重新启用的避障仍优先停车并清除收集。默认3秒到时STOP并拉低BCM17；
  续发UART指令每次最长300ms，按剩余时间截短，不发送一条不可取消的T5000。
  已使用窗口锁存，收集结束后同一仍在近区的球保持STOP/PICKUP COMPLETE，
  不连续重开3秒；需完成后的新确认球回到0.80上方且允许前进，或外部停车/模式切换重置，
  才能再次触发。结束后的空画面仍先等待2秒，再开始原搜索。
  保留兼容环境变量名：`TENNIS_BOTTOM_EXIT_FORWARD_SECONDS`默认3.0、范围0～5秒（0禁用）；
  `TENNIS_PICKUP_OPEN_SECONDS`默认3.0，须不少于前进时间且不超过5秒；
  `TENNIS_BOTTOM_EXIT_MIN_BOTTOM`默认0.80、范围0.5～1.0。若人为配置前进短于装置开启，
  余下时间只保持装置并停车。旧下沿准备/空帧触发/0.5秒裁切等待路径已移除；
  `allow_bottom_exit`调用参数仅兼容旧接口，不参与新收集判定。
- 0.80是图像下沿阈值，不是物理距离或入料证明。无车轮里程/收集反馈，3秒仅是命令窗口；
  尚未达到入口前的拒绝/漏检仍不会启动。固定视觉盲行可能错过球或撞墙，
  特别是当前超声关闭，必须在空旷有人看护的场地验证。
- 日志记录`PICKUP STATE: NEAR_BALL/DRIVE_DONE/COMPLETE/RESET_EXTERNAL`，
  包含启动球心、下沿与两项时长；近球提前结束对准时为`NEAR_AIM_STOP`。
  网关按状态变化记录`VISION STATE: CONFIRMED/VERIFYING/REJECTED:原因/EMPTY/TOO_CLOSE`，
  未全局放宽视觉验证，也不再传递半球裁切容错字段。现场journal只在`/run`保存，
  断电/重启丢失旧日志；本轮未修改系统日志持久策略。
- UART只在 `TENNIS_MOTOR_ENABLE=1` 时打开；默认是安全干运行。
- AUTO可选超声波避障由`TENNIS_OBSTACLE_ENABLE`控制，默认和systemd模板均为0。有效
  前向距离≤20cm先STOP并取消收集；每次左转200ms后停车静置并用新回波重新测距，连续
  两次有限且>30cm的真实读数才解除，随后还要等待转向后的新摄像头画面才恢复寻球。
  未曾测到近障碍时，36～72ms超范围长脉冲或80ms内无反射波视为空旷、允许正常寻球；
  已锁定近障碍后即使无回波也继续STOP，不可仅凭无回波恢复前进。Echo起始持续高电平、
  异常脉宽、采样过期或GPIO初始化失败仍STOP；最多45个短步仍未清障则锁定停车。传感器
  断线也可能表现为“无反射波”，无法仅凭一个Echo引脚区分，因此空旷放行不是故障安全保证。
  MANUAL目前不受该传感器
  仲裁，PAUSED和急停始终优先。阈值与引脚可用`TENNIS_OBSTACLE_*`环境变量调整。
  本车已安装持久`zz-obstacle-commissioning.conf`覆盖，将避障设为0、开机模式设为
  PAUSED。基础service模板仍为避障0/AUTO，不能脱离该覆盖单独启动实车。AUTO现在完全
  忽略前方障碍物。

手动运动默认值：

- 前进、后退和左右转向统一使用独立最大速度`manual_speed_delta=1000`；终端速度滑块100%时
  输出协议满量程2500/500，50%时输出2100/900。可用`TENNIS_MANUAL_SPEED_DELTA`降低该上限；
  旧的`TENNIS_MANUAL_FORWARD_SPEED_DELTA`仍作为兼容回退值。
- `min_speed_delta=200`仍是手动滑块的最低运动档；手动50%仍输出2100/900。
- 控制终端的手动速度初始值为100%；按住才移动、松手停车、250ms心跳、600ms失联停车和
  急停锁存等安全逻辑不变。

## 8. 丢球分阶段搜索

普通丢球连续2秒未识别到目标后（近球收集窗口结束后重新计时），小车以2500/500、
T500向左原地转一小步并停车观察0.8秒；默认同方向重复18步，以覆盖约一整圈。第18步观察
完仍没有目标时，再停车等待2秒后重复。原先左转3步、退回、右转3步的局部扇形搜索已取消。

默认18步是根据现场所述旧搜索约120°覆盖6个探测步而推算的初始值，并未测量单步实际角度。
可用`TENNIS_LOST_SEARCH_DELAY_SECONDS`（默认2）、`TENNIS_SEARCH_TURN_MS`（默认500）、
`TENNIS_SEARCH_STEPS_PER_REVOLUTION`（默认18）和`TENNIS_SEARCH_OBSERVE_SECONDS`（默认0.8）
调整。UART没有编码器/陀螺仪反馈，不能保证精确360°；应在空旷场地测量一圈的实际步数。
任何阶段确认目标后都会取消搜索；若正在旋转，先强制发送STOP，再进入正常追球。
相机画面超时、模式切换、急停等外部停车也清除当前搜索进度，恢复AUTO后重新等待2秒。
界面状态显示`SWEEP TURN`/`SWEEP OBSERVE`和`1/18`等步数。

当前帧主候选通过原有筛选但仍`VERIFYING`时，立即STOP并显示`TARGET VERIFY 1.0s`倒计时。
重复候选、空帧或拒绝帧不刷新这1秒；连续3帧确认、且来自停车静置0.15秒后的新画面时，
进入正常追踪，不直接开启收集。超时保留搜索步数并从下一小步恢复搜索，不续发被打断的
旧转向。持续未确认的同一候选不能反复停车；必须先经过一轮转向/观察时间（默认1.3秒）
并获得新的无主候选帧才允许再次停车确认。封锁期间真正确认的球仍可打断搜索。外部停车、
手动和避障接管清除确认等待。收集窗口内忽略此候选状态，原有安全停车仍最高优先。

## 9. Windows/安卓控制终端第一版

技术形式：无第三方运行依赖的响应式 PWA，Windows 可通过 Edge 安装为独立应用窗口，
安卓以后复用同一终端。源码位于 `control_terminal/`。

已实现：

- 自动、手动、暂停模式界面。
- 追踪/捡球作业模式：MANUAL/PAUSED下取得控制权后可按按钮切换 BCM17 低/高电平；
  AUTO下按钮禁用，由网关在已确认可见球下沿达到0.80并对准时置高，默认
  与固定直行同时持续3秒（配置上限5秒）；其他自动追踪、转向搜索和停车阶段置低。模式切换、急停、运行错误和手动失联
  恢复低电平。
- 控制权申请/释放，客户端不连接时保持只读。
- W/A/S/D、方向按钮和触摸按住式驾驶，松开/失焦/隐藏页面时发 STOP。
- 速度滑块默认100%；手动前进、后退和左右转向满量程均为2500/500；保留250ms心跳和
  紧急停车入口。
- WebSocket控制客户端和认证JPEG视频客户端。
- 识别框、置信度、FPS、延迟、电机和UART状态。
- 响应式布局在窄窗口和手机宽度下仍显示访问令牌输入框，支持直接进行认证连接。
- Node内置测试，无需安装npm第三方包。
- 急停恢复交互：终端可触发服务端锁存急停；解除前必须先取得控制权，使用不阻塞控制心跳
  的网页确认框；解除后网关保持 `PAUSED`，终端需再次明确选择 `AUTO` 或 `MANUAL`。
- 识别框叠加会根据视频原始尺寸和 `object-fit: contain` 后的实际画面区域换算坐标，避免
  正方形识别画面嵌入 4:3 网页容器时产生横向偏移。
- 视频 WebSocket 客户端在连接断开或连续3秒没有新帧时自动重连，并使用递增等待间隔，避免
  页面停留在最后一帧后只能手动重连。
- 控制终端默认连接地址为现场树莓派`ws://10.183.95.9:8765/ws`；首次打开或检测到旧默认地址
  `ws://192.168.0.108:8765/ws`时自动更新，用户自行填写的其他地址保持不变。PWA缓存当前v10。
- 强光补偿只在候选框附近连接高亮、低饱和区域，改善网球局部变白后轮廓不完整导致的漏识别，
  同时避免把全局白色背景加入候选；同一帧的颜色和高光掩膜只计算一次，候选附近没有高光
  时跳过局部连接；邻近判断使用距离变换代替尺寸随候选增长的大核膨胀，圆候选证据只在圆的
  局部ROI内统计；当 Hough 圆检测失败时，小块网球色种子邻近紧凑高光区域也会补出候选，
  并与圆候选去重；大圆候选或局部高光候选会替换其覆盖的小颜色种子，从候选源头保证
  一只球只进入一次验证。
- 普通颜色候选的最终轮廓只使用网球色掩膜，不再吸收邻近白色像素；白色证据只允许进入
  专用圆候选或局部高光候选，避免球旁的白桌面、手部高光或标签被算入球面积。
- 多个网球候选会全部保留，自动追踪目标按已验证轮廓的图像面积选择；面积越大代表
  目标在固定摄像头下看起来越近，置信度只用于面积相同的候选之间破平局。
- 同一物理网球的颜色轮廓和强光圆候选按中心与尺寸做空间关联；默认优先显示颜色轮廓，只有
  连续2帧只剩强光候选才回退，强光模式下连续3帧出现颜色轮廓才恢复。追踪中心、宽高和面积
  使用0.35系数的指数平滑；不同球只有在未匹配或面积至少大35%时才切换，避免强光下同一球
  的准确轮廓与圆候选逐帧跳变。
- 实时视频不绘制任何已识别网球的绿色轮廓或目标文字。已确认主目标显示红色中心点，
  待连续帧确认的当前主候选显示黄色中心点；网页绿色目标框仅在已确认遥测时显示。其余
  已识别但未被选为当前控制目标的球只显示蓝色中心点。颜色轮廓、Hough圆和多圆拆分结果仍
  作为识别、距离判断与追踪的内部数据，`Balls`计数和遥测继续保留。
- 已锁定目标偶发没有普通候选时，上一帧只用于限定下一帧的局部搜索范围；程序必须在当前帧
  重新找到符合颜色/高光、形状和最大15%位移约束的轮廓才继续显示和控制，绝不绘制旧位置框。
  当前证据有效时跟踪置信度最低保持在普通候选0.70、强光候选0.55；当前证据消失则该帧立即
  返回`LOST`，连续3个空帧后清除内部轨迹。短空帧不会增加确认计数，但会暂存已有确认状态，
  使同一位置重新检测后无需从零等待三帧。
- 令牌不会写入网页源码；首次成功认证后只保存在当前浏览器的 `localStorage`，页面启动时
  自动填充，并提供清除本机令牌的按钮。
- 控制租约因浏览器后台节流而在服务端超时，或服务端返回租约无效时，终端会立即清除本地
  `hasControl/leaseId` 并恢复“申请接管”；重新连接也会先清除旧租约状态。急停继续保持锁存，
  必须重新取得控制权后才能解除，解除后仍进入 `PAUSED`。
- 作业模式GPIO由树莓派网关独立线程管理；遥测报告引脚、输出电平、在线状态和错误。服务
  启动默认追踪/低电平，正常关闭或systemd停止后拉低；异常断电时GPIO由树莓派硬件复位。

树莓派认证网关已在 `192.168.0.108:8765` 完成真实链路验证：握手、控制租约、
AUTO/MANUAL/PAUSED、安全心跳、急停锁存和手动方向均由唯一权威状态管理。网关后台线程
独占 Picamera2，复用现有轻量验证模型和候选过滤器，并通过独立认证 WebSocket 发送最新
JPEG 帧；慢终端自动丢弃旧帧。识别框已经绘制到当前视频帧，同时发布归一化目标遥测。

追踪/捡球作业模式：TRACKING时BCM17输出低电平，PICKUP时输出高电平。AUTO驾驶模式
自动管理该引脚：已确认球可见且下沿达到0.80、在近区中心±0.15内允许前进时，
立即进入PICKUP并同时开始3秒直行及3秒高电平，可从近处起步，无需等待消失。
进入后忽略视觉目标变化，固定到时停车并恢复TRACKING低电平，不重复触发同一近球；
暂停、急停、相机异常、UART故障及已启用的避障仍立即取消。
电机干运行或UART
不在线时不自动拉高。MANUAL/PAUSED保留持有控制租约后
的手动切换；AUTO拒绝手动覆盖。
服务的systemd模板启用GPIO输出和`pinctrl`低电平启动/退出钩子；当前网关真实电机输出
已开启，基础模板避障默认关闭；本车持久覆盖已关闭避障并保持PAUSED开机。

`MotorController` 已接入同一仲裁层：AUTO 使用识别观察，MANUAL 使用终端方向和速度，
PAUSED/MANUAL_LOST/EMERGENCY_STOP 强制 STOP。基础systemd模板设置
`TENNIS_GATEWAY_BOOT_MODE=AUTO` 和 `TENNIS_MOTOR_ENABLE=1`，但本车持久覆盖将
启动模式改为PAUSED；超声波开关已设为关闭。重启后不会直接自动
追球，必须人工切换AUTO。
用户以电机物理总电源开关作为现场启停手段。

2026-10-05近球收集部署时，发现此前`/run`临时PAUSED覆盖已消失，虽然当时服务模式为PAUSED，
直接重启仍会按持久配置进入AUTO。先停止服务并确认BCM17低电平，再安装新的仅本次开机有效
的`/run/systemd/system/tennis-robot-gateway.service.d/zz-pickup-deploy-paused.conf`。当前服务
当时加载近球收集与避障代码，但避障开关仍为0。2026-10-05避障部署前再次发现
`/run`覆盖已消失，先停止服务并确认主进程为0及BCM17低电平，再同步并安装新的
`/run/systemd/system/tennis-robot-gateway.service.d/zz-obstacle-deploy-paused.conf`。用户接线
后为真实静止测距再将网关停机，完成16.8cm和40.5cm阈值读数验证。经用户确认后安装
`/etc/systemd/system/tennis-robot-gateway.service.d/zz-obstacle-commissioning.conf`，
使避障启用与PAUSED开机都持久生效；已移除旧`/run`覆盖并仅依靠持久覆盖重启成功。
该次启用后服务`active`、`mode=PAUSED`、摄像头/视频正常、BCM17低，BCM23/24由`lgpio`
分别占用为Trig输出和Echo边沿输入。用户随后自行切换过AUTO，日志显示若干T500
丢球搜索左转命令而非避障T200命令；用户确认是其主动操作。为核对安全短暂停止服务后
已重新启动并恢复PAUSED。后来按用户要求持久关闭超声波，现BCM23/24为输入，开机仍为
PAUSED。尚未验证实车避障T200转向及清障恢复。
现场地址为`10.23.90.9`，不能依赖旧地址。

未实现：WebRTC/H.264、设备发现，以及真实电机的车轮悬空验证。

## 10. 必须保持的安全约束

1. 树莓派是状态和电机命令唯一权威，终端不得直接控制UART。
2. 打开终端不会自动进入手动模式；控制权和模式切换必须明确申请。
3. AUTO/MANUAL切换必须先强制停车并清除旧模式的在途命令。
4. 手动模式超过600ms没有服务端认可的心跳必须停车并进入MANUAL_LOST。
5. 手动断线后不得自动恢复AUTO，必须人工确认。
6. 急停状态在服务端锁存，优先于全部自动和手动指令；解除必须先取得控制权，解除后
   保持 `PAUSED`，不得自动恢复运动。
7. 代码层电机输出默认关闭；当前树莓派的systemd实际配置已开启真实电机输出，但
   持久`zz-obstacle-commissioning.conf`覆盖使其以PAUSED启动并关闭超声波。
   整机重启后仍应保持PAUSED，不自动运动；AUTO不再
   调用避障逻辑。基础service
   模板单独使用时仍为AUTO且避障关闭，不能误删本车持久覆盖。
8. 当前现场操作按用户方案由电机物理总电源开关控制启停，用户选择跳过车轮悬空测试。
9. AUTO收集只在已确认可见球下沿≥0.80、球心在近区中心±0.15内且允许前进时启动；
   启动前验证、面积停车和对准后新帧检查不能绕过。启动后用户授权的固定视觉盲行窗口
   默认3秒、配置上限5秒，BCM17默认3秒、配置上限5秒；视觉丢失/拒绝/重现/偏移/过近均不能刷新或取消计时。
   单次前进UART最长300ms，到时STOP，装置剩余保持期（若配置）不得前进/搜索。
   已使用同一近球不得重开窗口，需结束后新的上方前进观察或外部停车/模式切换重置。
   PAUSED、MANUAL、急停、相机观察超时/异常、UART故障和已启用时的避障始终优先
   停止并取消窗口与收集。当前超声关闭，不保证防撞；3秒不等于真实位移或已收集。
10. BCM17只能输出3.3V逻辑信号，外接控制端必须共地且不能向GPIO回灌高于3.3V的电压；不得
   将GPIO直接接电机、继电器线圈或其他超出引脚能力的负载。systemd启动前和退出后均尝试
   将BCM17设为输出低电平。
11. 可见球小步对准每次转向后必须先停车并用转向结束后的新画面重新测量；新鲜近球观察
    进入放宽方向容差可提前STOP该次转向，但仍须静置并等待新帧。丢球、靠近停车、
    模式切换、相机超时和手动接管均可中断转向。对准脉冲默认不超过220ms，但实际角度未知。
12. 丢球整圈搜索每个转向命令默认最长500ms，必须逐步STOP并观察；发现目标、相机超时、
    模式切换或急停都要中断旋转。默认18步没有角度测量，不能声称已物理转过精确360°。
13. HC-SR04启用前必须确认实物与宽电压资料一致、3.3V供电及Echo安全电平；未接线
    不得启用。AUTO在尚未测到近障碍时允许超范围/无回波继续寻球，但读数过期、Echo持续
    高电平及GPIO异常仍停车；已锁定近障碍后无回波不能解除，必须连续两次测到>30cm的
    有限真实距离。避障左转每步最多200ms，逐步STOP并重新测距，达到45步上限仍无清障
    读数则停车。无回波与断线不能可靠区分，传感器故障可能漏掉墙；单一前向传感器不能
    保证侧后方安全，也可能把近处网球识别为障碍；距离阈值、安装角度和脉冲角度须现场标定。

14. 候选只能请求短时停车，不能伪装为已确认球或绕过收集入口；1秒等待不得由视觉重复续期。
    安全仲裁仍先于确认等待，且退出AUTO/相机异常等必须清除该等待。

## 11. 测试和部署

Python测试：

- `test_candidate_confirm.py`：11项候选打断搜索、1秒期限/非续期、停稳后新帧、超时恢复及
  重试门禁、外部安全取消、收集优先、网关传递、黄/红像素与三帧确认链路回归。
- `test_zmotord_uart.py`：电机协议、自动/手动方向一致性、可见球小步对准与新帧等待、
  手动倒车、整圈搜索及避障中断收集测试。
- `test_pickup_committed.py`：17项可见80%入口/近区方向边界、固定3秒与目标变化不续期、
  单次消费/新帧重置、计时到时、手动/暂停/急停/相机/避障优先及真实合成半球链路回归。
- `test_obstacle.py`：模拟回波脉宽换算、阈值迟滞、逐步转向、清障、故障停车及步数上限。
- `test_tennis_candidate_filter.py`：47项颜色/轮廓、困难负样本、连续帧、距离判断及确认识别
  观测字段完整性测试。
- `test_multi_ball_tracker_core.py`：不依赖OpenCV的多球关联、轨迹隐藏/重获和主目标切换测试。
- `test_tennis_ball_verifier.py`：特征、裁剪和导出模型加载测试。
- `test_train_tennis_verifier.py`：带框多球训练、完整会话隔离和光照增强测试；依赖离线
  SciPy/scikit-learn环境。
- 本机默认 Python 缺少 `cv2`；仓库内忽略的 `.venv` 已安装无界面版OpenCV用于本地测试，
  树莓派仍使用其独立运行环境。

终端测试：

```powershell
cd control_terminal
npm run check
npm test
npm start
```

2026-09-06补充验证：修复窄窗口下响应式 CSS 隐藏访问令牌输入框的问题；修改后直接运行
Node 等价检查通过，JavaScript 语法检查通过，Node 测试 8/8 通过，本地网页 HTTP 烟雾测试
返回 HTTP 200 且确认修复后的令牌样式规则已加载。当前连接测试使用地址
`ws://192.168.0.108:8765/ws` 和用户临时输入的令牌，最终因该地址 TCP 8765 不可达而断开；
令牌未写入仓库或日志。

2026-09-08补充验证：修复上位机急停恢复交互；急停锁定且本终端未取得控制权时，网页禁用
“解除紧急停车”并提示先申请控制权，取得控制权后才允许解除；将同步确认弹窗改为不阻塞
控制心跳的网页确认框；解除后继续保持 `PAUSED`，需再次明确选择 `AUTO`。修改后
`node --check src/app.js`、`node --check service-worker.js`、Node 测试 8/8、本机
`python -m unittest test_robot_gateway.py` 18/18、树莓派 `.venv-gateway/bin/python -m unittest
test_robot_gateway.py` 18/18 及 `git diff --check` 通过；已在真实网关上验证“申请控制权→非阻塞
确认→解除急停”路径，最终进入 `PAUSED`；未在真实电机上触发新的急停或运动命令。

2026-09-08补充验证：修复正方形视频嵌入 4:3 网页容器时识别叠加框的横向偏移；新增
`overlay.test.mjs`，验证正方形画面左右留白和宽画面上下留白的坐标映射。前端语法检查、
Node 测试 10/10 通过；未修改树莓派网关或电机控制代码。

2026-09-08补充验证：增加本机令牌记忆；令牌只在成功认证后写入浏览器 `localStorage`，不
写入源码、仓库或项目状态文件；增加清除令牌按钮，PWA 缓存升级至 v5。前端语法检查、
Node 测试 10/10 和 `git diff --check` 通过。

2026-09-09补充验证：多目标检测保留所有通过筛选的网球候选，并以已验证轮廓面积最大的候选
作为自动追踪目标，置信度仅作为面积相同的破平局条件；新增两个目标选择单元测试。树莓派
`.venv-gateway/bin/python -m unittest` 60/60 通过，本机默认 Python 的 OpenCV 限制仍未改变；
终端 Node 测试 10/10、视频客户端语法检查和 `git diff --check` 通过。网关重启后健康状态
恢复为 `cameraOnline=true`、`videoReady=true`、`runtimeError=null`。

2026-09-09补充验证：针对强光使网球局部变白的问题，在候选验证阶段只对候选框附近的高亮、
低饱和像素做局部补偿，避免把全局白色背景当作球；新增强光白斑模拟测试。随后复用每帧
HSV掩膜、将强光圆检测缩小到最大边长240并限制最多6个圆候选，候选过滤测试 26/26、树莓派
完整 Python 测试 64/64 通过。本机 Python 仅完成语法检查，完整 OpenCV 测试在树莓派运行。

2026-09-09性能复测：树莓派实际网关重启后温度约71.5°C、`throttled=0x0`，没有热降频；
真实浏览器观察到识别耗时约111–122ms、识别帧率约6.7–7.1 FPS，优化前约180–190ms、
4.5–4.7 FPS。972×972合成双球基准的识别耗时约79ms，当前服务恢复为
`cameraOnline=true`、`videoReady=true`、`runtimeError=null`。网关仍按原授权使用
`TENNIS_MOTOR_ENABLE=1`和`AUTO`启动，未增加控制命令。

2026-09-15补充验证：新增局部高光种子候选；即使 Hough 圆检测没有返回结果，只要小块网球色
种子邻近紧凑高光区域即可生成完整候选，并对 Hough 候选去重。树莓派候选过滤测试 27/27、
完整 Python 测试 65/65 通过。本机 Python 完成语法检查，`git diff --check` 通过。真实网页
画面观察到两个网球同时显示识别框，叠加层 `Accepted: 2`，强光球置信度约93%–98%，识别
耗时约114–116ms、帧率约5.2 FPS；网关健康状态正常，未发送人工控制命令。

2026-09-15重复候选修复：定位到小颜色种子与圆/局部高光候选被同时保留，导致单球出现
`Accepted: 1 Rejected: 1`。改为在候选生成阶段用覆盖范围更大的候选替换小种子，不在绘制阶段
强行合并。树莓派候选过滤测试 27/27、完整 Python 测试 65/65 通过；真实单球画面确认
`Accepted: 1 Rejected: 0`，识别耗时约115ms、帧率约5.8 FPS。

2026-09-15底层性能优化：性能剖析确认低帧率并非热降频，而是强光补偿的大核膨胀随候选尺寸
产生非线性耗时；代表性972×972样本单次膨胀约394ms。改用距离变换后，972像素后处理中位
耗时由约424ms降至54ms；720像素代表性样本的分类+后处理+JPEG中位耗时约137ms。网关改为
Picamera2硬件直接输出960×720、30FPS，避免采集1296×972后再缩到640。真实网页无球场景
连续观察为9.8–10.0 FPS、识别耗时81–84ms；优化前真实单球场景约5.8 FPS、115ms，两组现场
画面内容不同，不能当作严格同场景A/B。优化后温度74.0°C、`throttled=0x0`，网关无警告日志，
健康状态正常。最终树莓派完整Python测试67/67（含候选27/27、网关20/20）通过；本机网关
20/20、Python语法检查和`git diff --check`通过。本机默认Python未运行依赖OpenCV的完整候选
测试；本轮网页现场没有球，仍需用户用实际单球、强光球和远球确认新采集分辨率下的现场精度。

2026-09-15邻近白色轮廓与候选源稳定性修复：现场画面观察到球下缘轮廓向白色桌面高光延伸；
合成“网球贴近白色物体”对照中，当前算法把面积从纯颜色轮廓0.072扩大到0.0774。已在本机
改为普通颜色候选只按网球色轮廓计面积，专用强光候选仍保留白色证据，并新增相邻白块不被
吸收的回归测试。在此基础上增加同球颜色/强光候选的时序仲裁、来源迟滞和目标几何平滑，
避免强光背景下准确颜色轮廓与Hough圆候选快速跳变。树莓派候选测试34/34、完整Python测试
74/74通过；本机网关测试20/20、Python语法检查和`git diff --check`通过，本机默认Python因
缺少`cv2`未运行候选测试。代码已同步并重启服务，健康状态为`cameraOnline=true`、
`videoReady=true`、`runtimeError=null`，服务`active/running`；温度75.4°C、`throttled=0x0`。
网页现场抽样约7.8–9.3 FPS、84–106ms，未观察到候选来源逐帧来回跳变；移动球期间出现过
一次完全漏检后重新确认，仍需在固定球和不同强光角度下继续观察漏检率。

2026-09-15识别画面简化：按用户要求隐藏Hough圆候选生成的标准大绿色圆，仅改变视频绘制，
圆候选仍参与强光识别、时序仲裁和自动控制。树莓派候选测试36/36、完整Python测试76/76
通过；本机网关测试20/20、Python语法检查和`git diff --check`通过，本机默认Python因缺少
`cv2`未运行候选测试。服务重启后健康状态正常；网页现场以99%置信度识别桌面网球时，仅显示
外层目标框和中心点，未再显示合成大圆。

2026-09-15远球与单帧漏检稳定性：撤销会在相对运动时留下旧框的盲目多帧保持，改为以前一
目标区域引导当前帧局部重检测；只有当前帧重新通过颜色/高光和严格形状检查才输出新轮廓，
位移上限15%，无当前证据立即撤框。当前证据持续存在时置信度不再机械衰减到阈值以下，普通
目标最低0.70、强光目标最低0.55。树莓派候选测试39/39、完整Python测试79/79通过；本机网关
测试20/20、Python语法检查和`git diff --check`通过，本机默认Python因缺少`cv2`未运行候选
测试。服务重启后健康状态正常；网页现场观察到移动球的恢复轮廓跟随当前球位置，没有旧位置
残留框，远球局部恢复候选可在0.70下继续追踪。视频帧与控制遥测来自独立WebSocket，瞬时显示
可能相差一帧。

2026-09-15多球独立轨迹实现与部署（服务待重启）：修改前已将识别、网关、测试、状态文档和
systemd模板保存到本机`tennis_pre_multiball_20260915_172840.zip`，树莓派原文件另存为
`/home/pi/tennis_backups/tennis_pre_multiball_20260915_1743.tar.gz`。新增逐球空间关联和轨迹ID，同一物理球的颜色/强光
候选先合并，每个球分别平滑并在漏检时从当前帧局部重检测；隐藏状态最多保留3帧用于重获，
但无当前证据的轨迹不绘制，避免旧位置残留。自动控制仍只使用一个主目标；新球必须比当前目标
面积大至少1.35倍并连续3帧才切换，主目标变化时重新执行3帧确认。本机
`test_multi_ball_tracker_core.py` 6/6、`test_robot_gateway.py` 20/20、Python语法检查和
`git diff --check`通过；本机依赖OpenCV的`test_tennis_candidate_filter.py`因缺少`cv2`未运行。
树莓派隔离目录视觉/多球/网关测试66/66、同步后完整Python测试86/86及语法检查通过；测试中的
电机状态使用测试替身，不向真实串口发送运动数据。代码已同步到`/home/pi/tennis`，但常驻服务
仍运行重启前进程，等待明确现场安全确认后再重启；尚未进行真实摄像头多球验证。

2026-09-17控制租约恢复修复：现场出现浏览器后台后服务端租约已超时、页面仍保留旧
`hasControl/leaseId`，导致急停解除和接管操作持续被拒绝。终端现在识别
`CONTROL_LEASE_REQUIRED`和`INVALID_CONTROL_LEASE`，清除失效租约并恢复申请接管；主动
重连也同步清理本地租约。PWA缓存升级至v6。前端语法检查和Node测试12/12、本机网关/电机/
多球核心测试43/43、`git diff --check`及本地浏览器烟雾检查通过，浏览器控制台无错误。
依赖OpenCV的完整候选测试未在本机运行；修复后的真实急停解除链路等待当前终端刷新后复测。

2026-09-17多圆保留：针对两个网球部分重合或外切时HSV轮廓合并成一个色块的问题，在拉长的
颜色父候选内部保留多个彼此独立的Hough圆候选，并延迟到训练验证与形状过滤之后决策；同一
父候选至少有两个子圆通过时才用子圆替换父候选；只有一个子圆通过且父候选也通过时继续使用
父候选，父候选未通过时仍保留唯一通过的子圆，避免单球内部高光或Hough伪峰删掉有效目标。
多球关联明确将同一父候选下的兄弟圆作为不同实例。
Picamera2改为可选导入，使不带树莓派相机库的Windows测试环境可导入纯图像处理函数，实际
启动相机主循环时仍强制要求Picamera2。仓库内`.venv`使用NumPy 2.5.3和
opencv-python-headless 5.0.0.93；`.venv\Scripts\python.exe -m unittest discover -v`
完整Python测试88/88通过（其中候选过滤42/42），新增重合双球保留与单子圆回退测试均通过；
使用当前`tennis_ball_verifier.npz`对半径30像素、圆心距30/40/50/60像素的合成双球做端到端
检查，从50%重合到外切四种情况最终均保留两个子圆；圆心距40像素时父候选置信度0.9520、
两个子圆置信度0.9922/0.9945；
`python -m py_compile tennis_candidate_filter.py tennis_ball_rpi.py test_tennis_candidate_filter.py`
、终端Node测试12/12和`git diff --check`通过。测试中的电机输出使用测试替身，未向真实串口
发送命令。SSH已通过本机现有专用密钥恢复，代码同步前的树莓派备份位于
`/home/pi/tennis_backups/tennis_pre_multicircle_20260917_1345.tar.gz`。代码已同步到
`/home/pi/tennis`，树莓派候选测试42/42、完整Python测试88/88及语法检查通过。常驻服务已
重启加载新代码，并新增`/etc/systemd/system/tennis-robot-gateway.service.d/visual-test-safe.conf`
将`TENNIS_MOTOR_ENABLE=0`、`TENNIS_GATEWAY_BOOT_MODE=PAUSED`作为当前有效配置；重启后健康
状态为`dryRun=true`、`motorOutputEnabled=false`、`mode=PAUSED`、`cameraOnline=true`、
`videoReady=true`、`runtimeError=null`。随后进行的真实双球验证结果记录在下一条。

2026-09-17真实双球标注与模型更新：从网关实时画面确认两个相互遮挡的网球和地面暗色倒影；
为避免视频叠加文字污染训练数据，短暂停止已处于PAUSED/禁用电机状态的服务，用相同960×720
相机配置采集720×720无叠加原图，随后立即恢复服务。原图与水平镜像保存在
`training_data/annotated/20260917_two_overlapping_balls/`，每张JSON分别标注前后两个球框，预览
图仅供人工核对。`train_tennis_verifier.py`新增显式多目标标注读取，每个框独立生成正样本；本批
2帧、4个目标生成24个增强正样本。新模型保持C=0.003和阈值0.70，未见旧验证集回归：1452/
1452正确、假阳性率0；真实原图后球单框概率从0.6835提高到0.9677，镜像两球概率为
0.9920/0.9854。同时在拉长颜色色块的局部高分辨率ROI内执行Hough圆检测，解决全局缩小检测
被背景边缘占满而遗漏真实球的问题；更新后真实原图与镜像均解析为2个独立目标。本机完整
Python测试90/90、候选测试43/43通过；树莓派候选测试43/43、完整Python测试89项通过且训练器
测试因未安装离线SciPy/scikit-learn依赖跳过1项，运行时测试无跳过。树莓派部署前备份位于
`/home/pi/tennis_backups/tennis_pre_two_ball_training_20260917_1405.tar.gz`。新代码、模型、
报告和带框训练素材已同步并重启；现场实时视频显示`Balls: 2 Rejected: 0`，两个目标置信度均
显示1.00。最终健康状态仍为`dryRun=true`、`motorOutputEnabled=false`、`mode=PAUSED`、
`cameraOnline=true`、`videoReady=true`、`runtimeError=null`，未向真实串口发送运动命令。

2026-09-17多圆轮廓显示修复：现场左上角两个球已显示`Balls: 2`但没有绿色边界，原因是此前
隐藏普通Hough辅助圆的显示规则也覆盖了多圆拆分子目标。现在只有经过验证并带有
`circle_split_candidate`标记的子圆恢复绿色轮廓，普通Hough辅助圆继续隐藏，识别、追踪和控制
决策不变。新增显示策略回归测试；本机候选过滤测试44/44、Python语法检查及
`git diff --check`通过。部署前备份位于
`/home/pi/tennis_backups/tennis_pre_split_contour_20260917_1418.tar.gz`；树莓派候选测试
44/44、完整Python测试90项通过，离线训练器测试因缺少SciPy/scikit-learn跳过1项，语法检查
通过。服务重启后的实时帧显示`Balls: 2 Rejected: 0`，两个相接球各自具有绿色圆形边界；
健康状态为`dryRun=true`、`motorOutputEnabled=false`、`mode=PAUSED`、`cameraOnline=true`、
`videoReady=true`、`runtimeError=null`。测试使用串口替身，未向真实串口发送运动命令。

2026-09-17中心点显示策略：按用户现场要求，所有已识别网球（包括单球、普通颜色候选和多圆
拆分子目标）都不再绘制绿色轮廓或球旁文字；当前主追踪球使用红色中心点，其他已识别球使用
蓝色中心点。识别、主目标面积选择、切换迟滞和控制决策不变。新增像素级颜色与位置测试，
本机候选过滤测试45/45、Python语法检查及`git diff --check`通过。部署前备份位于
`/home/pi/tennis_backups/tennis_pre_center_dots_20260917_1426.tar.gz`；树莓派候选测试45/45、
完整Python测试91项通过，离线训练器测试因缺少SciPy/scikit-learn跳过1项，语法检查通过。
服务重启后的真实双球帧显示`Balls: 2 Rejected: 0`，较近主球为红色中心点，右侧较远球为
蓝色中心点，两个球均无绿色轮廓和球旁文字。健康状态保持`dryRun=true`、
`motorOutputEnabled=false`、`mode=PAUSED`、`cameraOnline=true`、`videoReady=true`、
`runtimeError=null`；测试使用串口替身，未向真实串口发送运动命令。

2026-09-30手动前进满速：新增独立`manual_forward_speed_delta=1000`，只在MANUAL前进时使用；
终端滑块默认100%，此时四路PWM为2500/500。倒车、转向和AUTO继续使用300上限。PWA缓存升级
至v9。本机`.venv`电机/网关测试39/39、终端Node测试12/12、全部Node语法检查、Python编译和
`git diff --check`通过；测试使用内存串口，未向真实串口发送运动命令。系统PATH中无npm，
前端测试使用Codex工作区自带Node直接执行等价命令。树莓派同步后电机/网关测试39/39及
Python编译通过；服务通过临时PAUSED覆盖安全重启，确认`manual_forward_speed_delta=1000`、
`auto_speed_delta=300`、`mode=PAUSED`、`motorOutputEnabled=true`、`cameraOnline=true`、
`videoReady=true`、`runtimeError=null`和`throttled=0x0`。没有发送手动运动命令。

2026-09-30手动全方向满速：按用户后续要求将前进专用上限改为统一`manual_speed_delta=1000`；
MANUAL下前进、后退和左右转向均使用同一滑块范围，100%为2500/500、50%为2100/900。旧的
`TENNIS_MANUAL_FORWARD_SPEED_DELTA`仅保留为新环境变量未设置时的兼容回退。AUTO仍使用300
上限。本机电机/网关测试39/39、Node测试12/12、Python编译和`git diff --check`通过；测试使用
内存串口，没有向真实串口发送运动命令。树莓派部署前备份位于
`/home/pi/tennis_backups/tennis_pre_manual_all_directions_20260930_1220.tar.gz`。部署期间树莓派
发生一次整机重启，临时`/run`覆盖随之消失，持久AUTO配置恢复并发出丢球搜索转向命令；发现后
立即停止网关，再在服务停止状态完成同步和测试。树莓派电机/网关测试39/39及Python编译通过；
重新建立临时PAUSED覆盖后启动服务，确认`manual_speed_delta=1000`、`auto_speed_delta=300`、
`mode=PAUSED`、`motorOutputEnabled=true`、`cameraOnline=true`、`videoReady=true`、
`runtimeError=null`和`throttled=0x0`。新代码启动后没有发送手动运动命令。

2026-09-30电机方向映射修正：依据用户实测的“前进→右转、后退→左转、右转→前进、左转→后退”，
调整`commands_for_motion()`中的四路PWM组合，并更新明确的方向字节测试和接线说明；运动日志
改为显示速度差值，避免原来的高/低PWM简写被误解为逐电机输出。本机
`.venv\Scripts\python.exe -m unittest test_zmotord_uart.py test_robot_gateway.py` 39/39通过，
`python -m py_compile zmotord_uart.py test_zmotord_uart.py`和`git diff --check`通过。树莓派
`.venv-gateway/bin/python -m unittest test_zmotord_uart.py test_robot_gateway.py` 39/39及对应Python
编译通过；测试使用内存串口。远端修改前备份位于
`/home/pi/tennis_backups/tennis_pre_direction_mapping_20260930.tar.gz`。同步后服务在原有临时
PAUSED覆盖下启动，`active`、`mode=PAUSED`、`motorOutputEnabled=true`、`cameraOnline=true`、
`videoReady=true`、`runtimeError=null`、`throttled=0x0`。本轮未发送真实方向命令；新映射的
真实车轮动作尚未现场复验。

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
暗光模型更新后，树莓派完整 Python 测试58/58通过，Windows终端语法检查通过、Node测试
8/8通过；正式默认配置回放正样本779/779通过、负样本382/382拒绝，新增暗光批次
176/176通过。实时认证遥测确认`ballDetected=true`、`confidence=0.955`、`inferenceMs=38`、
`mode=AUTO`、`searchPhase=TRACKING`。用户确认本轮训练和验证期间电机物理总电源关闭。
控制终端移除演示入口、演示传输和无连接画面提示后，JavaScript语法检查及Node测试8/8通过。

网关部署状态：树莓派 `/home/pi/tennis/.venv-gateway` 已安装 FastAPI、Uvicorn 和 WebSockets；
`tennis-robot-gateway.service` 已启用并正在运行，开机自动启动。访问令牌仅保存在树莓派
`/etc/tennis-robot-gateway.env`，权限为 `root:root 600`；无令牌 WebSocket 连接已验证会被拒绝。
systemd每次启动都从该持久文件读取同一令牌，不会因普通重启自动重新生成；只有替换环境
文件、重新安装/刷写系统或人工轮换令牌时才会改变。
服务监听局域网 TCP 8765。2026-08-14 用户确认电机具备物理总电源开关并授权跳过悬空
测试，当前 systemd 模板已切换为 `TENNIS_MOTOR_ENABLE=1` 并以 `AUTO` 启动。重启后实测
`mode=AUTO`、`motorOutputEnabled=true`、`cameraOnline=true`、`videoReady=true`、
`runtimeError=null`、`UART_FD_OPEN`、`throttled=0x0`。2026-09-15部署增加
`TENNIS_GATEWAY_CAMERA_WIDTH=960`、`TENNIS_GATEWAY_CAMERA_HEIGHT=720`和
`TENNIS_GATEWAY_CAMERA_FPS=30`；这些参数可通过systemd环境覆盖，并在启动时校验范围和偶数尺寸。

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
6. 当前方向映射按用户实测结果推导并部署；自动模式现为满量程PWM，仍需在空旷场地短时
   验证自动前进、左右转向、丢球搜索及停车，现场可使用电机物理总电源开关。
   本车持久覆盖应使整机重启后保持PAUSED；关闭避障后即使人工切换AUTO也不会检测前方
   墙壁，须在空旷有人看护的场地操作。未来若重新启用避障，仍需实车验证避障转向。
7. 收集改为可见确认球框下沿≥0.80、近区中心±0.15内允许前进即启动，固定3秒前进和
   3秒BCM17输出；进入后不再依赖视觉目标。无车轮里程或入料反馈，3秒是命令窗口，
   不等于真实位移/收集成功；相机超时、急停等安全条件仍可提前取消。须现场标定0.80
   对应的实际距离、收集口容差和3秒位移；满速盲行可能错过球或撞墙，超声关闭时尤其
   需空旷场地和物理总电源/急停看护。入口前面积停车、漏检/拒绝、大偏差仍会阻止收集。
   结束后同一近球保持STOP避免无限重复；没有入料反馈，此时需要新上方确认球或人工
   停车/模式切换才能重新触发。16:30:39旧日志未启动的原因是确认近球后形状拒绝清除
   准备，并非15%边界；旧0.5秒半球STOP容错已按用户要求整体移除。
   丢球搜索转向脉冲现为500ms/步、同方向18步，每步后停车观察0.8秒。现场应先验证
   转向方向、周围空间和单步角度，再标定整圈所需步数；没有角度反馈，不能当作精确360°旋转。
8. 摄像头线程遇到未处理异常会退出，客户端重连不会重启该线程；需诊断并修复根因后重启
   网关。2026-09-30确认识别时缺少观测字段的崩溃已修复，线程通用自动恢复仍未实现。
9. 可见球对准现在按画面误差闭环小步转向，但没有编码器/陀螺仪反馈；120～220ms脉冲在
   不同地面、电压和轮胎载荷下可能转得不够或仍有过冲，必须现场量测最短有效脉冲，不能
   将画面居中视为精确车身角度。丢球搜索的500ms脉冲仍是独立的开环时序。
10. 最多1秒候选停车确认不会提高模型本身的暗光识别率；完全未通过筛选的球不会触发。
    同一持续未确认候选不重复停车，但仍允许其真正确认后追踪；偶发误候选可能造成短停。
    本轮没有实车验证制动距离和弱光成功率，视频与遥测独立传送仍可能瞬时不同步。
    模型完整会话留出验证的正样本召回率为99.4%，但候选级负样本误报率仍为15.0%；应按
    新采集器标签补充无球、黄色/绿色物体、反光地面和网球同场背景在暗光、强光、逆光、
    冷暖色温下的独立负样本，并以从未参与训练的新会话作为最终验收集。
11. 超声波避障代码已用实物模块验证静态近/远阈值，但尚未用实车障碍物和运动角度标定；
    代码及基础服务模板默认关闭，本车持久覆盖也已关闭并保持PAUSED。
    若未来重新启用，实车试验前应
    先在电机物理电源关闭时验证3.3V供电、Echo电平与20/30cm静态测距，再在空旷场地
    低风险试验。现已取得约74.8cm、21.5cm、16.8cm及40.5cm真实静止读数，已跨过
    ≤20cm进入和>30cm退出门槛，但供电/回波电压及实车避障运动尚未核验。
    45步上限按原丢球搜索18×500ms名义总转向时间折算，非实测整圈。空旷场景实际输出
    46.8ms长脉冲，已按超范围处理；真球可能在≤20cm被误判为障碍。若传感器断线表现为
    无回波，现有策略也会放行，故不能把该单传感器当作可靠防撞保险。关闭避障后AUTO
    完全不依据前向距离决策，可能撞墙；务必在空旷有人看护的场地使用。

## 13. 变更记录

- 2026-10-07：按用户请求保存当前完整基线并创建注释标签`midtest_stable`，暂不实现刚讨论的
  方向记忆搜索。保留80%下沿入口、±15%近区容差、3秒前进/装置、1秒候选停车确认及
  超声禁用/本车持久PAUSED，未修改运行逻辑或树莓派服务。本机针对性检查命令
  `.venv\Scripts\python.exe -m unittest -q -b test_candidate_confirm test_pickup_committed
  test_tennis_candidate_filter.CandidateFilterTests.test_primary_center_is_red_and_other_ball_center_is_blue`
  29项通过；`.venv\Scripts\python.exe -m py_compile zmotord_uart.py tennis_ball_rpi.py
  robot_gateway/runtime.py test_candidate_confirm.py`及`git diff --check`通过。
  当前94个跟踪/非忽略文件的路径和文本凭据模式检查未发现需排除项；训练原图、缓存、
  本地环境、候选模型均不提交，也未删除。按此前要求未跑完整Python/Node或实车测试，
  标签名称不代表新增实车安全验收。用户指定GitHub仓库
  `https://github.com/nor111401/tennis_car.git`后配置为origin；上传前
  `git -c credential.interactive=never ls-remote --heads --tags`检查成功且没有远端分支或标签。
  首次提交/注释标签因Git没有作者配置而失败，未生成新提交/标签；沿用现有历史作者Gen，
  仅设置本仓库Git身份，不改全局配置，不保存认证秘密。
  本轮上传目标限定`main`和注释标签`midtest_stable`，采用非强制原子推送并核对远端对象。

- 2026-10-07：修复暗光中主球有中心点但未连续帧确认、车辆仍旋转的问题：将当前有效
  主候选独立传入电机仲裁，先STOP观察最多1秒，停稳后新确认帧才追踪；超时恢复下一
  搜索步，持续未确认候选须冷却及新无候选帧才可再次停车。识别阈值/三帧确认不放宽。
  主候选黄点、确认主球红点、其他球蓝点，网页绿框仍仅用于确认遥测。80%入口、±15%
  近区容差、3秒前进/BCM17窗口、超声禁用及安全最高优先保持不变。新增11项聚焦回归。
  本机`.venv\Scripts\python.exe -m unittest -q -b test_candidate_confirm test_pickup_committed
  test_tennis_candidate_filter.CandidateFilterTests.test_primary_center_is_red_and_other_ball_center_is_blue`
  29项通过；`.venv\Scripts\python.exe -m py_compile zmotord_uart.py tennis_ball_rpi.py
  robot_gateway/runtime.py test_candidate_confirm.py`及`git diff --check`通过。
  复核远端PAUSED、持久PAUSED/避障0及BCM17低后部署；首次备份因远端没有Windows终端
  README而中止，未停服务/改源码。仅备份实际远端文件后成功，完整回滚归档为
  `/home/pi/tennis_backups/candidate_confirm_20261007_1126/previous.tar.gz`。停服务确认
  MainPID=0、BCM17低后同步三份源和新测试，远端`.venv-gateway/bin/python`运行上述
  同样29项及四文件`py_compile`通过；四文件SHA256与本机一致。持久PAUSED/避障0
  门禁通过后重启，MainPID=2113、active/running；健康PAUSED、相机/视频在线、
  runtimeError=null、BCM17低，进程环境避障0/开机PAUSED，无两项收集时长覆盖。
  本机/远端状态与部署、接线说明同步；终端README仅维护本机，未在树莓派新建终端目录。
  按用户要求未跑完整Python/Node测试、没有实车运动测试；未切换AUTO或发送运动命令。
  停车确认不是暗光识别率保证，完全未通过原筛选的球仍不会触发；实际制动、低帧率及
  持续误候选仍需现场观察。视频与遥测独立传送，黄/红点和绿框可短暂不同步。

- 2026-10-07：用户继续将前进和BCM17收集输出从3.5秒同时缩短为3.0秒，环境默认与
  测试期望/当前说明同步。只改时长，80%入口、±15%容差、窗口内忽略视觉变化及安全
  优先级不变。仍按用户要求不跑完整Python/Node或实车运动测试。本机
  `.venv\Scripts\python.exe -m py_compile zmotord_uart.py test_zmotord_uart.py test_pickup_committed.py`
  和`git diff --check`通过；`.venv\Scripts\python.exe -m unittest -q -b
  test_zmotord_uart.CommandTests.test_default_auto_speed_matches_manual_full_speed
  test_zmotord_uart.CommandTests.test_environment_uses_committed_pickup_defaults
  test_pickup_committed.CommittedPickupTests.test_full_three_seconds_and_remaining_uart_pulse_are_bounded`
  3项通过（内存UART/模拟时钟）。初次只读核对PAUSED，但执行部署门禁时已转为MANUAL，
  PAUSED检查未通过，未备份/同步/停服/重启；远端MainPID=1650仍运行3.5秒版、相机正常、
  runtimeError=null。已请求用户切回PAUSED，等待确认后才部署；远端测试尚未运行，
  用户随后确认已暂停，复核PAUSED及持久PAUSED/避障0后，先将远端原文件备份到
  `/home/pi/tennis_backups/pickup_3s_20261007/previous.tar.gz`，停止服务确认MainPID=0、
  BCM17低，再同步三份源/测试及接线、部署说明。远端三文件`py_compile`及
  `MotorConfig.from_environment()`前进/收集均3.0秒断言通过，三文件SHA256与本机一致。
  重启后MainPID=1891、active/running；最终健康状态PAUSED、相机/视频在线、
  runtimeError=null、BCM17低。实际进程环境为避障0/开机PAUSED，无两项时长覆盖。
  本机与远端PROJECT_STATE同步；未切换AUTO，完整Python/Node及实车运动按要求未运行。


- 2026-10-07：按用户要求将前进窗口和BCM17收集输出默认值由5.0秒同时缩短为3.5秒，
  同步环境读取默认值、相关测试期望和当前说明；配置上限仍5秒，80%入口、±15%容差、
  忽略窗口内视觉变化、一次消费及安全优先停车规则均未改。按要求不跑完整Python/Node
  测试和实车运动测试。本机`.venv\Scripts\python.exe -m py_compile zmotord_uart.py
  test_zmotord_uart.py test_pickup_committed.py`和`git diff --check`通过；
  `.venv\Scripts\python.exe -m unittest -q -b
  test_zmotord_uart.CommandTests.test_default_auto_speed_matches_manual_full_speed
  test_zmotord_uart.CommandTests.test_environment_uses_committed_pickup_defaults
  test_pickup_committed.CommittedPickupTests.test_full_three_point_five_seconds_and_remaining_uart_pulse_are_bounded`
  3项通过，仅内存UART和模拟时钟。部署前确认远端PAUSED、避障0/持久PAUSED，原文件先
  备份到`/home/pi/tennis_backups/pickup_3p5_20261007/previous.tar.gz`，再停止网关确认
  MainPID=0、BCM17低。已同步三份源/测试及部署/接线/状态说明；远端三文件`py_compile`
  和`MotorConfig.from_environment()`前进/装置均3.5秒断言通过，SHA256与本机一致。
  恢复服务后MainPID=1650、active/running、健康状态PAUSED、摄像头/视频在线、
  runtimeError=null、BCM17低；实际进程仍为避障0/开机PAUSED，无两项时长环境覆盖。
  未切换AUTO、未发运动指令；完整Python/Node及真实位移/入料测试按要求未运行。


- 2026-10-05：按用户明确选择，确认可见球下沿达到80%、近区±15%允许前进即启动，
  车辆直行和收集装置均持续5秒；启动后视觉目标消失/拒绝/偏移/过近不取消、不续期，
  暂停/手动/急停/相机异常或超时/UART故障/已启用避障仍优先取消。移除旧下沿准备、
  空帧触发及0.5秒半球等待，保留消费锁存防止同一近球重复5秒；远区对准和速度未改，
  近区起点随入口改为0.80，超声仍关闭、持久开机PAUSED不变。
  本机`.venv\Scripts\python.exe -m unittest -q -b test_pickup_committed.py test_zmotord_uart.py
  test_tennis_candidate_filter.py test_robot_gateway.py`119项通过；
  `.venv\Scripts\python.exe -m unittest discover -q -b`137项通过，测试仅用内存UART、
  模拟时钟和合成图像。树莓派17:23只读健康状态PAUSED、摄像头/视频在线、无运行错误，
  持久PAUSED/避障0及无收集参数覆盖已核实。七份源码/测试的本机与树莓派`py_compile`
  及本机`git diff --check`通过；树莓派`.venv-gateway/bin/python -m unittest -q -b
  test_pickup_committed.py test_zmotord_uart.py test_tennis_candidate_filter.py test_robot_gateway.py`
  119项通过；`.venv-gateway/bin/python -m unittest discover -q -b`135项，134通过、
  离线训练SciPy/scikit-learn依赖跳过1项。七文件SHA256与本机一致，默认实读
  下沿/近区/容差/前进/装置为0.80/0.80/0.15/5.0/5.0。
  停机确认MainPID=0、BCM17低、BCM23/24输入。初次备份流程因`pinctrl get 17 23 24`
  不支持多引脚而提前退出，同步先于本轮新备份；随后逐引脚核对并保存同步后快照
  `/home/pi/tennis_backups/pickup_committed_20261005_1726/deployed_snapshot.tar.gz`，
  既有`partial_exit_20261005_1653/`回退备份保留（它是此前裁切修改前版本，不是本轮
  精确前驱）。17:32恢复服务MainPID=2241、active/running、BCM17低；实际进程环境仍为
  开机PAUSED/避障0。17:33随后有已连接终端的AUTO运行，健康状态相机/视频在线、
  runtimeError=null；本助手未发送AUTO或运动控制命令，也未覆盖现场驾驶模式。
  17:34:01.776596球下沿0.82615启动5秒/5秒，期间EMPTY仍继续，到17:34:06.803694
  DRIVE_DONE/COMPLETE，约5.027秒；其他多次约5.02～5.05秒到时，未见视觉取消。
  随后最终只读健康核对已恢复PAUSED、相机/视频在线、runtimeError=null；已提醒用户
  仅在空旷有人看护场地测试。日志证明控制窗口，
  不证明实际位移、BCM17高电平时序或成功入料；前端代码未修改，Node未重跑。

- 2026-10-05：依据16:30:39近球日志修复形状拒绝过渡清除准备的问题。增加单候选下沿
  裁切几何证据（不更改检测成功/空帧语义），严格匹配最后确认的近球心与宽度，仅在
  准备且未开始补行时从最后确认起保留最多0.5秒；期间STOP/BCM17低，后续新空帧才
  启动原2秒前进/3秒装置。旧帧、重复半球不续期，其他拒绝、超时、人工/急停/相机/
  已启用避障接管取消，启动后的窗口不放宽。增加裁切与非裁切负例、真实合成球从完整
  到半球到空帧、计时上限/旧帧/位置尺寸不匹配及网关完整仲裁测试。修改范围仅识别
  观测、电机状态机、网关字段传递、对应测试及文档；未改模型、速度、阈值、超声开关。
  本机`.venv\Scripts\python.exe -m unittest -q -b test_zmotord_uart.py test_tennis_candidate_filter.py
  test_robot_gateway.py` 131项通过；`.venv\Scripts\python.exe -m unittest discover -q -b`
  149项通过；六份源/测试文件`py_compile`及`git diff --check`通过。测试使用内存UART、
  合成图像及模拟网关时钟，未发送真实运动。部署前核实服务PAUSED、持久开机PAUSED/
  避障0，停机确认MainPID=0、BCM17低及BCM23/24输入；六份源码/测试、状态文档与
  部署README原件备份在`/home/pi/tennis_backups/partial_exit_20261005_1653/`。
  同步后树莓派六文件`py_compile`通过；`.venv-gateway/bin/python -m unittest -q -b
  test_zmotord_uart.py test_tennis_candidate_filter.py test_robot_gateway.py` 131项通过；
  `.venv-gateway/bin/python -m unittest discover -q -b`运行147项，146项通过、离线训练
  SciPy/scikit-learn依赖跳过1项；六文件SHA256均与本机一致。16:55核实服务active/running、
  mode=PAUSED、摄像头/视频在线、runtimeError=null、BCM17低、BCM23/24输入，启动后
  日志只有STOP及`VISION STATE: EMPTY ... partial=None`，未切换AUTO或发送真实运动。
  前端代码未改，Node测试未运行；真实裁切过渡、收集口入料及BCM17高电平时序未实测。

- 2026-10-05：用户同意修复近球小偏差转向及近处起步无法准备收集：新增0.85下沿近区
  和±0.15方向容差，远区仍±0.06；大偏差仍对准，新鲜近区小偏差可先STOP进行中的转向，
  仍等待静置后的新帧。移除初次收集需要历史远区居中观察的条件，保留0.92准备、合格
  空帧后才计2秒补行/3秒装置；已启动窗口消费锁存阻止同一近球/空画面无限重触发。
  新增准备/取消几何原因日志和视觉状态变化日志（确认/待确认/拒绝原因/空画面/过近），
  不绕过拒绝候选和面积停车。16:11只读检查仅找到本次16:06启动日志，上一启动无持久
  journal，故无法证实用户上一轮半球是何种拒绝原因；未改系统日志持久配置。
  本机`.venv\Scripts\python.exe -m unittest discover -q -b` 138项通过；
  `.venv\Scripts\python.exe -m unittest -q -b test_zmotord_uart.py test_tennis_candidate_filter.py
  test_robot_gateway.py` 120项通过；`.venv\Scripts\python.exe -m py_compile zmotord_uart.py
  tennis_ball_rpi.py robot_gateway/runtime.py test_zmotord_uart.py test_tennis_candidate_filter.py`
  和`git diff --check`通过。部署前再次确认PAUSED及持久避障0/开机PAUSED，停机确认
  `MainPID=0`、BCM17低、BCM23/24输入，备份在
  `/home/pi/tennis_backups/near_aim_start_20261005_1625/`后同步5份源码/测试、状态文档及
  部署README。树莓派相同5文件`py_compile`通过，`.venv-gateway/bin/python -m unittest
  -q -b test_zmotord_uart.py test_tennis_candidate_filter.py test_robot_gateway.py` 120项通过；
  `.venv-gateway/bin/python -m unittest discover -q -b`共136项，135项通过、离线训练器
  SciPy/scikit-learn依赖跳过1项。5文件SHA256均与本机一致，未发现近区/补行/收集环境覆盖，
  实读默认为0.85/0.15/0.92/2.0/3.0。重启后服务active/running、mode=PAUSED、摄像头/
  视频在线、runtimeError=null、BCM17低、BCM23/24输入；启动日志仅STOP，真实摄像头已
  输出`VISION STATE: EMPTY ... loss_ok=True`，验证新诊断日志链路生效。尚未实测方向容差、
  半球裁切、收集口入料及GPIO高电平时序，未切换AUTO；前端源码未改，Node测试未运行。

- 2026-10-05：按用户要求恢复9月30日收集启动条件：下沿阈值0.92且居中前进仅准备，
  紧接的无候选LOST才启动完整2秒补行和3秒装置输出。取消0.80可见球提前启动、
  PICKUP AIM暂停计时及4秒对准上限；可见球仍按原追踪逻辑运动，不再因收集计时到期
  卡在球前。目标重现/不合格观察、外部停车和模式安全接管继续取消，保持期禁止搜索转向。
  超声仍关闭，持久PAUSED及整圈搜索不变。回归覆盖0.80不启动、0.92准备、可见5秒不耗
  补行、空帧启动后完整2秒/3秒保持、转向后新帧、拒绝候选、重现及安全取消。本机
  `.venv\Scripts\python.exe -m unittest -q -b test_zmotord_uart.py` 41项通过，
  `.venv\Scripts\python.exe -m unittest discover -q -b` 131项通过，
  `.venv\Scripts\python.exe -m py_compile zmotord_uart.py test_zmotord_uart.py`与
  `git diff --check`通过。部署前只读核实树莓派服务PAUSED及持久避障0/开机PAUSED。
  停机确认`MainPID=0`、BCM17低、BCM23/24输入；旧源码、测试、状态文档和部署README
  备份在`/home/pi/tennis_backups/pickup_bottom_exit_restore_20261005_1555/`后同步新文件。
  树莓派`.venv-gateway/bin/python -m py_compile zmotord_uart.py test_zmotord_uart.py`和
  `.venv-gateway/bin/python -m unittest -q -b test_zmotord_uart.py` 41项通过；
  `.venv-gateway/bin/python -m unittest discover -q -b`共129项，128项通过、离线训练器
  SciPy/scikit-learn依赖跳过1项。两份源码SHA256与本机一致；配置默认实读为0.92/2.0/3.0，
  服务重启后`active/running`、`mode=PAUSED`、摄像头/视频在线、`runtimeError=null`，BCM17
  低且BCM23/24输入，启动日志仅STOP。未切换AUTO，未实测真实2秒车轮位移或3秒装置
  电平/入料。前端源码未改，Node测试未运行；两份README已在本机修正3秒说明，部署README
  已同步，树莓派无终端README（终端部署在Windows），未新增远端终端目录内容。

- 2026-10-05：根据14:58现场日志`NEAR_BALL → AIM_PAUSE → AIM_TIMEOUT`且没有`AIM_RESUME`
  的证据，修复转向等待消耗原2秒绝对前进窗口的问题。近球窗口现在对可见球的小步对准
  暂停计时，转向与等新帧期间STOP、BCM17低，重新确认居中后只恢复未用完的前进预算；
  多次对准不重开预算。新增默认4秒、上限5秒的前进/对准墙上时间保护，前进UART单次
  仍最多300ms；收集默认3秒累计高电平计时同步排除对准暂停，受墙上时间上限后保持期
  约束。拒绝候选、过近、相机超时、避障接管、人工/PAUSED仍可取消。新增前进预算、
  迟到重获、硬上限、拒绝候选与配置校验测试。本机`.venv\\Scripts\\python.exe
  -m unittest -q -b test_zmotord_uart.py` 41项通过，`.venv\\Scripts\\python.exe
  -m unittest discover -q -b` 131项通过；相关`py_compile`与`git diff --check`通过。
  用户已确认PAUSED，部署前再通过健康检查核实。远端旧文件备份在
  `/home/pi/tennis_backups/pickup_drive_budget_20261005_1520/`；停机确认`MainPID=0`、BCM17低
  后同步。树莓派`.venv-gateway/bin/python -m py_compile zmotord_uart.py test_zmotord_uart.py`
  通过，`.venv-gateway/bin/python -m unittest discover -q -b`共129项，128项通过、
  离线训练依赖跳过1项。重启后服务`active/running`、`mode=PAUSED`、摄像头/视频在线、
  `runtimeError=null`、BCM17低、BCM23/24输入，超声仍关闭；两份源码SHA256与本机一致。
  未切换AUTO或发送真实运动测试；真实BCM17时序、车轮位移与入料效果尚待现场验证。
  若对准后球已完全退出视野、不能重新确认居中，仍会停车等待直至4秒上限，不能保证拾球。
  前端未改，Node测试未运行。

- 2026-10-05：按用户要求禁用HC-SR04避障，本车持久drop-in改为
  `TENNIS_OBSTACLE_ENABLE=0`，保留`TENNIS_GATEWAY_BOOT_MODE=PAUSED`。AUTO将忽略
  前向障碍物及测距故障，BCM23/24不由网关采样；急停、相机超时、近球及人工
  接管规则不变。新增测试读取本车持久drop-in并校验避障0/开机PAUSED。本机
  `.venv\\Scripts\\python.exe -m unittest discover -q -b` 128项通过；
  `.venv\\Scripts\\python.exe -m py_compile test_robot_gateway.py robot_gateway/runtime.py`
  和`git diff --check`通过。用户重新联网后，先确认服务`mode=PAUSED`；修改前文件备份在
  `/home/pi/tennis_backups/obstacle_disabled_20261005_1410/`。停机确认`MainPID=0`、BCM17低、
  BCM23/24输入；安装持久覆盖后确认systemd最终环境为避障0/开机PAUSED，才启动服务。
  树莓派`.venv-gateway/bin/python -m py_compile test_robot_gateway.py robot_gateway/runtime.py`
  通过，`.venv-gateway/bin/python -m unittest discover -q -b`运行126项，125项通过、
  离线训练依赖跳过1项。重启后服务`active`、`mode=PAUSED`、摄像头/视频在线、
  `runtimeError=null`、BCM17低、BCM23/24输入。未切换AUTO或发送真实运动命令，
  真实车轮/传感器行为未运行；前端未改动，未运行前端Node测试。关闭避障后可能撞墙。
  随后同步更新后的`PROJECT_STATE.md`时SSH在密钥交换阶段两次断开，最终只读复核也因同样
  原因未完成；树莓派上的状态文档仍为旧版，仓库本机文档为准，待SSH恢复后同步。配置、
  服务及GPIO的上述验证均是在SSH断开前完成的，不能把最后一次复核说成已通过。

- 2026-10-05：修复近球收集开始后一次可见球小步对准会取消整个前进窗口、导致车停在球前
  且同一近球无法重触发的问题。改为`PICKUP AIM`暂停：先STOP并关闭BCM17，对准转向后
  静置且等待新画面居中，仅恢复原2秒窗口剩余时间；等待期间丢球不盲行，超时取消收集。
  面积过近、避障、人工接管、PAUSED及相机超时仍取消窗口。增加暂停/恢复/超时/安全接管
  回归和状态日志。本机`.venv\\Scripts\\python.exe -m unittest discover -q -b`：127项通过；
  本机`py_compile`及`git diff --check`通过。树莓派`.venv-gateway/bin/python -m py_compile
  zmotord_uart.py test_zmotord_uart.py`通过，`.venv-gateway/bin/python -m unittest discover -q -b`
  共125项，124项通过、离线训练依赖跳过1项。远端原文件备份在
  `/home/pi/tennis_backups/pickup_aim_resume_20261005_1340/`。部署后服务`active`、
  `mode=PAUSED`、摄像头/视频在线、`runtimeError=null`、BCM17低；未切换AUTO或发送测试
  运动指令。真实车轮位移、BCM17时序及入料效果尚未实测；未运行前端Node测试（未改前端）。

- 2026-10-05：按用户“无反射波继续正常行驶、防止近墙碰撞”要求修正避障。停机原始测量
  当前空旷场景20/20个Echo长脉冲约46.8ms，旧代码误判为无效；扩大超范围长脉冲判别为
  36～72ms，并将完整80ms周期无回波视为无近障碍。未锁定障碍时允许寻球；一旦测到
  ≤20cm，仍需连续两次有限的>30cm真实读数才解除，无回波不解锁。Echo持续高电平、
  异常脉宽、过期或GPIO错误继续STOP。增加46.8ms、66ms、超时、异常脉宽及避障锁存
  回归测试。本机完整Python测试125/125、树莓派完整测试123项（122通过、离线训练器
  依赖跳过1项）、远端`py_compile`通过；停机实物新代码连续12次均为`inf/NORMAL`。
  备份在`/home/pi/tennis_backups/obstacle_noecho_20261005_1312/`。部署后服务
  `active`、`mode=PAUSED`、摄像头/视频在线、`runtimeError=null`、BCM17低。
  未切换AUTO或发送真实运动命令，未用球或墙复测新策略；前端Node测试未运行（未改前端）。
  无回波与断线不可可靠区分，接线故障可能漏检墙，仍需现场低风险标定传感器朝向与球的干扰。

- 2026-10-05：持久PAUSED+避障启用重启后的最后日志核对发现若干T500左转/STOP指令；
  T500属于原有丢球搜索，不是HC-SR04避障T200。为避免未知动作立即停网关并确认
  `MainPID=0`、GPIO17低、BCM23/24输入；用户随后确认这些模式切换由其本人发起。
  按持久配置重新启动，最终`active`、`mode=PAUSED`、摄像头/视频在线、运行错误为空，
  BCM17低、BCM23/24由lgpio占用。没有证据表明已触发T200避障；用户未报告真实车轮
  转角或入料效果，下一步须现场验证障碍≤20cm后的短步左转和>30cm恢复。

- 2026-10-05：经用户明确同意，新增并安装持久
  `deploy/tennis-robot-gateway-obstacle-commissioning.conf`，使本车开机保持PAUSED且
  `TENNIS_OBSTACLE_ENABLE=1`；基础service模板仍以0为安全默认。移除了此前创建的
  `/run/.../zz-obstacle-deploy-paused.conf`临时覆盖（项目内PAUSED模板仍可恢复），
  经`systemctl daemon-reload`后只依赖持久覆盖重启。确认服务`active`、
  `mode=PAUSED`、`cameraOnline=true`、`videoReady=true`、`runtimeError=null`、BCM17
  低电平、BCM23输出低电平及BCM24边沿输入均由`lgpio`占用。未切换AUTO、未发送
  真实避障转向；供电/Echo电压尚未经仪器独立测量。此前本机完整Python测试125/125，
  树莓派123项中122项通过、离线训练依赖跳过1项；本次只改部署配置与文档，未重跑前端。

- 2026-10-05：停机静态近/远阈值复测：用户把障碍物再移近后12次读数16.75～16.79cm，
  随后移至约35～40cm处，12次读数40.45～40.49cm；分别满足≤20cm进入与>30cm退出
  条件。两次测后BCM23/24均为输入，网关保持停机；尚未启用传感器常驻配置、未执行
  实车转向。正在征求用户对“持久PAUSED开机并启用避障”的安全设置意见。

- 2026-10-05：用户放置自估15～20cm的前向平整障碍物后，停机静态测距12次为
  21.50～21.54cm；该位置不会触发代码的≤20cm避障入口，已请求目标再近4～5cm。
  测后BCM23/24均恢复输入，网关保持停机且避障开关为0；尚未测≤20cm和>30cm两侧。

- 2026-10-05：用户报告HC-SR04接线完成后，在树莓派网关停机（`MainPID=0`、BCM17低）
  状态执行真实静止测距：12次读数74.82～74.89cm，后台采样7次的最新结果74.83cm，
  无回波错误。发现首版Reader关闭后BCM23虽保持低电平却仍为输出；改为先写低、释放
  输出，再声明为下拉输入，真实复测6次74.81～74.89cm且结束后BCM23/24均为输入。
  新增GPIO释放回归断言，本机完整Python测试125/125，树莓派123项中122项通过、
  1项离线训练依赖跳过；真实采样未向电机发送命令。当前网关仍停机，避障开关仍为0，
  等待用户放置15～20cm目标，再测>30cm；尚未实测VCC/Echo电压和实车避障运动。

- 2026-10-05：新增可选HC-SR04避障：BCM23/24、3.3V宽电压模块接线假设，AUTO在
  ≤20cm停车并以200ms短步向左转、停稳后重测，连续两次>30cm且有新视觉帧后恢复；
  无回波/故障/过期或45步未清障均停车。避障会清除近球收集窗口，传感器和systemd
  默认关闭。新增模拟回波/状态机/电机取消及摄像头中断测试；本机完整Python测试
  125/125、相关`py_compile`和`git diff --check`通过。树莓派原临时PAUSED覆盖消失，
  发现有效服务配置又为AUTO且电机输出开启后先执行`systemctl stop`，确认`MainPID=0`、
  GPIO17低、GPIO23/24输入。远端修改前项目文件备份为
  `/home/pi/tennis_backups/tennis_pre_obstacle_20261005_1228.tar.gz`，原systemd单位另存为
  同名`.tar`；停机同步后树莓派完整Python测试123项，其中122项通过、离线训练依赖
  跳过1项，相关`py_compile`和`lgpio`导入通过。安装持久`TENNIS_OBSTACLE_ENABLE=0`
  单位及本次开机有效的PAUSED覆盖后重启，确认服务`active`、`mode=PAUSED`、
  `motorOutputEnabled=true`、`cameraOnline=true`、`videoReady=true`、`runtimeError=null`、
  GPIO17低、GPIO23/24输入。测试使用模拟回波和内存UART；未接实物HC-SR04、未运行
  真实GPIO测距/避障转向、未复测实车20/30cm阈值与角度、未运行前端Node测试（未改前端）。
  整机重启会清除临时PAUSED覆盖，持久配置仍为AUTO，且避障仍关闭。

- 2026-10-05：按用户要求将AUTO收集装置的BCM17高电平默认时间从2秒延长到3秒，独立于
  小车最多2秒的近球前进/空画面补行窗口。正常到时先STOP，剩余约1秒保持PICKUP，之后
  恢复TRACKING；急停、模式切换、画面超时、转向或不合格候选仍立即取消。新增
  `TENNIS_PICKUP_OPEN_SECONDS`（默认3、须不少于前进窗口、上限5）及停驶保持/取消测试，
  网关允许AUTO且电机STOP时在该保持期继续输出PICKUP，但转向不能输出高电平。本机
  `.venv\Scripts\python.exe -m unittest discover -q` 116/116、相关`py_compile`和
  `git diff --check`通过；树莓派`.venv-gateway/bin/python -m unittest discover -q`运行114项，
  其中113项通过、离线训练器缺SciPy/scikit-learn跳过1项，相关`py_compile`通过。远端
  修改前备份`/home/pi/tennis_backups/tennis_pre_pickup_3s_20261005.tar.gz`；服务停机同步后
  在原有仅本次开机有效的PAUSED覆盖下重启，确认配置为前进2.0秒/收集3.0秒、服务
  `active`、`mode=PAUSED`、`motorOutputEnabled=true`、`cameraOnline=true`、
  `videoReady=true`、`runtimeError=null`及BCM17输出低电平。测试使用内存UART；未运行
  前端Node测试（未改前端），未实测自动收集高电平时长、真实车轮位移或入料效果。
  树莓派整机重启仍会清除临时PAUSED覆盖并恢复持久AUTO启动。

- 2026-10-05：修复近球角度微调后球出画面而无法触发收集的问题。已确认目标先在上方居中
  前进、经小步转向后用新画面再次居中、球框下沿达到0.80时，立即进入最多2秒近球收集窗口；
  AUTO前进时BCM17提前输出PICKUP。随后完全空画面只允许走完同一窗口剩余时间，单次UART
  指令最多300ms；转向、拒绝候选、近距离停车、重新出现、相机超时和模式切换均取消收集。
  窗口到期同一近球保持停车，避免重复触发或持续前进。新增转向后新帧、窗口到期、取消及
  重新进入上方视野后再触发的回归测试。本机`.venv\Scripts\python.exe -m unittest discover -q`
  114/114、相关`py_compile`和`git diff --check`通过；树莓派
  `.venv-gateway/bin/python -m unittest discover -q`运行112项，其中111项通过、离线训练器因
  缺少SciPy/scikit-learn跳过1项，相关`py_compile`通过。远端修改前备份位于
  `/home/pi/tennis_backups/tennis_pre_near_pickup_20261005.tar.gz`。部署前发现旧临时PAUSED覆盖
  已消失，先停止服务并重新安装仅本次开机有效的PAUSED覆盖；最终服务`active`、
  `mode=PAUSED`、`motorOutputEnabled=true`、`cameraOnline=true`、`videoReady=true`、
  `runtimeError=null`，BCM17为输出低电平，加载的近区阈值为0.80。测试使用内存UART；
  未运行前端Node测试（未改前端），未进行真实小车位移、自动收集高电平与入料效果测试。
  实车必须先标定0.80阈值及2秒位移，整机重启仍会失去临时PAUSED覆盖并恢复持久AUTO。

- 2026-10-05：AUTO丢球等待默认从10秒缩短为2秒；搜索由左右各3步并退回的局部扫视改为
  同方向18个T500脉冲、每步STOP并观察0.8秒，完成一圈后重新等待2秒。18步来自旧搜索
  约120°覆盖6个探测步的现场估计，真实角度尚未标定；新增环境变量
  `TENNIS_SEARCH_STEPS_PER_REVOLUTION`。外部停车清除搜索进度，重新获得有效画面后从等待
  开始。定向本机`.venv\Scripts\python.exe -m unittest -q test_zmotord_uart.py test_robot_gateway.py`
  53/53、本机`.venv\Scripts\python.exe -m unittest discover -q` 111/111、相关`py_compile`和
  `git diff --check`通过。旧地址`10.183.95.9`的SSH连接被关闭；发现当前树莓派地址
  `10.23.90.9`，用现有专用密钥连接。网关在PAUSED状态停止，旧搜索代码和测试已备份到
  `/home/pi/tennis_backups/tennis_pre_full_sweep_20261005.tar.gz`，随后同步并测试；树莓派定向
  测试53/53、完整测试109项（108项通过，离线训练器缺SciPy/scikit-learn跳过1项）及相关
  Python编译通过。服务在新的临时PAUSED覆盖下启动，健康检查为`active`、`mode=PAUSED`、
  `motorOutputEnabled=true`、`cameraOnline=true`、`videoReady=true`、`runtimeError=null`；远端
  环境文件没有搜索参数覆盖。测试使用内存UART，没有发送真实转向命令；电机方向及整圈
  角度仍待实车确认。前端Node测试未运行（本轮未改前端）。整机重启会清除临时覆盖并
  恢复持久AUTO启动。

- 2026-10-05：重构轻量验证器训练为完整拍摄会话隔离，修复相邻视频帧同时进入训练与验证
  导致的指标泄漏；新增暗光、过曝、冷暖色温和局部不均匀光照增强，并对困难负样本同步增强。
  参数选择留出最新176个暗光正帧和176个困难负帧，得到正样本175/176、负候选1453/1710；
  选定C=0.03后用全部已审核会话重训并更新`tennis_ball_verifier.npz`和报告。采集脚本新增
  `--condition`及非敏感`session.json`元数据。定向训练/验证器测试6/6、本机完整Python测试
  110/110及相关`py_compile`通过；测试使用内存UART，未发送真实电机命令。SSH端口可达，
  但远端在密钥交换阶段主动关闭连接，因此未执行树莓派测试、未同步模型、未重启服务，
  也未核实临时PAUSED覆盖；现场跨光照端到端验证仍未进行。

- 2026-09-30：可见球的AUTO对准改为按连续画面水平误差决定120～220ms短转向脉冲；
  每步结束发送STOP、静置0.15秒并等待转向后的新画面，中心容差改为±0.06。
  前进、手动、丢球搜索T500和下沿补行/捡球GPIO逻辑不变。本机
  `.venv\Scripts\python.exe -m unittest discover -q` 108/108、相关Python编译及
  `git diff --check`通过；本轮未改前端，未运行Node测试。树莓派停止网关后备份
  `/home/pi/tennis_backups/tennis_pre_visual_aim_20260930.tar.gz`并同步控制代码；远端完整
  Python测试108项（107项通过、离线训练器缺SciPy/scikit-learn跳过1项）及相关编译通过。
  服务在临时PAUSED覆盖下重启，健康检查`active`、`mode=PAUSED`、`cameraOnline=true`、
  `videoReady=true`、`runtimeError=null`、`throttled=0x0`，BCM17低电平。测试使用内存UART，
  未发送真实转向命令；120～220ms脉冲及画面中心容差尚未实车标定。整机重启会清除临时
  PAUSED覆盖并恢复持久AUTO配置。

- 2026-09-30：AUTO下仅在经确认目标从画面下沿消失后的2秒前进补行期间使BCM17进入
  PICKUP高电平，其他自动状态保持TRACKING低电平；禁用AUTO的手动作业模式按钮，
  电机干运行或UART不在线时也保持低电平；
  模式切换、急停、错误和手动失联时恢复TRACKING。丢球分段搜索从T250增至T500，
  每侧仍3步并停车观察，无角度反馈。本机完整Python测试104/104、终端Node测试12/12、
  相关Python `py_compile`及`git diff --check`通过；`npm.cmd`不在PATH，改用工作区
  捆绑Node执行终端测试。
  树莓派备份`/home/pi/tennis_backups/tennis_pre_auto_pickup_search_actual_20260930.tar.gz`，
  网关停机同步代码；远端完整Python测试104项（103项通过、离线训练器缺SciPy/scikit-learn
  跳过1项），相关Python编译通过。服务在临时PAUSED覆盖下启动，健康检查`active`、
  `mode=PAUSED`、`cameraOnline=true`、`videoReady=true`、`runtimeError=null`、
  `throttled=0x0`，BCM17为低电平。未实际行驶、未用真球触发自动捡球高电平，搜索角度、
  拾球效果和前端页面现场交互均未验证。整机重启会清除临时覆盖，恢复持久AUTO配置。

- 2026-08-10 `019d658`：保存当前网球识别、电机控制、训练和模拟器基线。
- 2026-08-10 `a91dcd2`：丢球搜索从整段旋转改为每侧3次、每次350ms的分阶段扫描。
- 2026-08-14：清除缓存、调试截图、过时SSH脚本、一次性启动脚本、本地虚拟环境、日志、
  临时凭据辅助文件和重复模拟器压缩包；保留训练数据、模型和协议资料。
- 2026-08-14：新增 `control_terminal/` PWA第一版、WebSocket/WebRTC客户端、
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
- 2026-08-14：采集176帧暗光近地网球正样本并重训轻量验证器；修复本地颜色候选框按中心
  重新匹配时可能错配微小轮廓的问题。仅对训练模型置信度不低于0.90的候选放宽圆度、
  填充率、实心度和宽高比，普通颜色候选继续使用严格形状规则；全数据回放正样本779/779、
  负样本0误报，现场暗光网球实时识别恢复。
- 2026-08-14：按用户要求从控制终端删除演示按钮、模拟传输、`?demo=1`自动入口和未连接
  画面提示；PWA缓存升级至v3，终端只保留真实树莓派连接路径。
- 2026-09-06：修复控制终端在宽度不超过1150px时隐藏访问令牌输入框的问题；窄窗口和手机
  布局现在保留令牌输入并允许连接认证网关。
- 2026-09-08：修复急停锁定后的网页恢复交互；未取得控制权时不能执行解除，页面明确提示
  先申请控制权，使用不阻塞心跳的网页确认框解除，PWA 缓存升级至 v4，解除后仍需人工选择
  `AUTO` 或 `MANUAL`，保持服务端急停和暂停安全边界。
- 2026-09-08：修复控制终端识别叠加框的坐标映射；按视频实际内容区域处理 `contain` 留白，
  解决正方形摄像头画面放入 4:3 容器时外框偏移，并将 `overlay.js` 纳入 PWA 缓存。
- 2026-09-08：增加本机浏览器令牌记忆和清除入口；令牌不硬编码进网页源码，PWA 缓存升级
  至 v5。
- 2026-09-09：支持多球候选同时显示，并按验证轮廓面积选择较近网球作为自动追踪目标；新增
  面积优先和面积相同按置信度破平局的测试。
- 2026-09-09：增加候选局部高光补偿；对候选框附近的高亮低饱和区域进行连接，改善网球一侧
  被强光照白后轮廓不完整导致的漏识别，并新增强光模拟测试。
- 2026-09-09：优化强光识别性能；复用每帧HSV掩膜，候选附近没有高光时跳过局部膨胀，
  将Hough圆检测缩小到240边长并限制候选数量；实测识别耗时和帧率得到改善。
- 2026-09-15：增加局部高光种子候选；Hough圆检测失败时，利用小块网球色与邻近紧凑高光
  区域的并集补全强光白球，并与已有圆候选去重；真实双球画面确认 `Accepted: 2`。
- 2026-09-15：修复单球多框；在候选生成阶段用完整圆/局部高光候选替换其覆盖的小颜色
  种子，避免同一球同时进入多个验证候选；真实画面确认 `Accepted: 1 Rejected: 0`。
- 2026-09-15：底层帧率优化；用距离变换替代强光补偿的大核膨胀，在圆候选局部ROI统计证据，
  网关摄像头改为硬件输出960×720、30FPS并增加环境参数校验；真实无球画面稳定约10 FPS，
  无热降频，最终树莓派完整测试67/67通过。
- 2026-09-15：部署邻近白色轮廓与候选源稳定性修复；普通颜色候选不再吸收邻近高光，
  同球颜色/强光候选增加2帧回退、3帧恢复的来源迟滞及0.35指数平滑。树莓派候选测试34/34、
  完整测试74/74通过，服务重启后健康，现场未再观察到两套轮廓逐帧快速跳变。
- 2026-09-15：隐藏Hough圆候选的合成大绿色轮廓，仅保留外层目标框、中心点和真实颜色轮廓；
  识别与控制逻辑不变。树莓派候选测试36/36、完整测试76/76通过，网页现场验证生效。
- 2026-09-15：修复远球与单帧漏检抖动；不用旧位置硬保持，改为上一轨迹引导当前帧局部
  重检测，只有当前颜色/高光与形状证据有效才输出随目标移动的新框。树莓派候选测试39/39、
  完整测试79/79通过，现场移动球未出现旧位置残留框。
- 2026-09-15：修改前在电脑和树莓派分别保存部署前备份；将单一时序目标升级为
  多球独立轨迹，对每个球分别关联、平滑和当前帧局部恢复，主目标采用1.35倍面积、连续3帧的
  切换迟滞。电脑端核心轨迹测试6/6和网关测试20/20通过，树莓派隔离测试66/66、同步后完整
  Python测试86/86通过；代码已同步，常驻服务等待现场安全确认后重启。
- 2026-09-09：视频通道增加断开和3秒无新帧自动重连，采用递增等待间隔并保留安全停车边界。
- 2026-09-17：修复浏览器控制租约超时后的本地状态卡死；租约被服务端拒绝或连接重建时清除
  旧`hasControl/leaseId`，恢复重新申请接管和急停解除，PWA缓存升级至v6。
- 2026-09-17：修复多圆拆分目标已计数但没有绿色边界；只显示已验证拆分子圆轮廓，继续隐藏
  普通Hough辅助圆。部署后现场确认两个相接球各有绿色边界；树莓派候选测试44/44、完整测试
  90项通过并跳过1项离线训练依赖测试，安全模式保持PAUSED且电机输出关闭。
- 2026-09-17：按现场要求隐藏所有已识别球的轮廓和球旁文字；主追踪球显示红色中心点，其他
  已识别球显示蓝色中心点。现场双球帧确认生效；树莓派候选测试45/45、完整测试91项通过并
  跳过1项离线训练依赖测试，安全模式保持PAUSED且电机输出关闭。
- 2026-09-22：新增独立追踪/捡球作业模式和网页切换按钮；有效控制租约可切换 TRACKING/PICKUP，
  网关通过`pinctrl`将BCM17（物理11）分别输出低/高电平，绕开UART BCM14/15。服务启动、正常
  退出及systemd停止钩子设置低电平；增加gpio组权限、在线/电平/错误遥测和PWA缓存v7。
  自动测试未运行（本轮执行要求不运行测试；未运行`test_robot_gateway.py`、候选过滤及
  `control_terminal`的`npm test`）。本机Python编译、Node脚本语法检查和`git diff --check`
  通过。代码和systemd模板已同步并重启树莓派服务；确认服务`active`、GPIO17为输出低电平，
  补充组含`gpio`，任务GPIO已启用；健康状态为`dryRun=true`、`motorOutputEnabled=false`、
  `mode=PAUSED`、`cameraOnline=true`、`videoReady=true`、`runtimeError=null`。未在网页点击切换，
  因此捡球高电平现场状态尚未触发核验。
- 2026-09-22：修正控制终端默认树莓派地址为现场IP`10.183.95.9`，并将浏览器保存的旧默认IP自动迁移到新地址，保留其他自定义地址；PWA缓存升级至v8。Node语法检查及`git diff --check`通过；未运行自动测试。
- 2026-09-30：手动前进使用独立满量程速度上限；终端默认100%时输出2500/500，倒车、转向和
  自动追球保持原上限。本机及树莓派电机/网关测试均39/39、Node测试12/12及语法/差异检查通过。
  服务以仅本次开机有效的PAUSED覆盖安全重启并加载新代码；持久配置仍为AUTO，树莓派重启后
  会恢复AUTO启动。本轮没有发送手动运动命令。
- 2026-09-30：按后续要求将MANUAL前进、后退和左右转向统一改为满量程速度上限1000；AUTO
  继续保持300上限。本机与树莓派电机/网关测试均39/39、Node测试12/12及语法/差异检查通过。
  部署期间树莓派整机重启导致临时PAUSED覆盖消失并恢复AUTO；发现后立即停止服务，在停止状态
  完成部署，再以新的临时PAUSED覆盖启动。最终服务、摄像头和视频正常，未发送手动运动命令。
- 2026-09-30：依据实车四方向错位报告重新映射四路UART PWM。手动与自动共享修正；本机及
  树莓派电机/网关测试各39/39通过，语法和差异检查通过。服务已在临时PAUSED覆盖下加载新代码；
  实际车轮方向仍需现场低速复验。
- 2026-09-30：按用户确认把AUTO追球前进、左右转向及丢球搜索设为与MANUAL 100%相同的
  `speed_delta=1000`和方向组合；追球指令时长、停车阈值、手动滑块范围及搜索分步时序不变。
  本机`.venv\Scripts\python.exe -m unittest test_zmotord_uart.py test_robot_gateway.py` 40/40、
  `.venv\Scripts\python.exe -m py_compile zmotord_uart.py test_zmotord_uart.py`和`git diff --check`
  通过。树莓派部署前备份位于
  `/home/pi/tennis_backups/tennis_pre_auto_manual_match_20260930.tar.gz`；在停止服务时同步代码，
  `.venv-gateway/bin/python -m unittest test_zmotord_uart.py test_robot_gateway.py` 40/40及对应
  Python编译通过。服务在原有临时PAUSED覆盖下重启，健康检查为`active`、`mode=PAUSED`、
  `motorOutputEnabled=true`、`cameraOnline=true`、`videoReady=true`、`runtimeError=null`；未发现
  速度环境变量覆盖，`throttled=0x0`。测试使用内存串口；完整视觉、前端测试及真实车轮动作
  未运行。整机重启会清除临时PAUSED覆盖并恢复持久AUTO启动。
- 2026-09-30：增加已确认网球从画面下沿消失后的单次2秒AUTO前进补行，限制在此前居中前进、
  球框下沿至少0.92且随后画面无候选时触发；短串口命令续发，到时停车。其他丢球、识别失败、
  目标重现、观察超时、急停和模式切换均保持/恢复停车；新增电机状态机回归测试。本机
  `.venv\Scripts\python.exe -m unittest discover -q` 100/100、相关Python编译及`git diff --check`
  通过。树莓派停止网关后备份
  `/home/pi/tennis_backups/tennis_pre_bottom_exit_20260930.tar.gz`并同步代码；
  `.venv-gateway/bin/python -m unittest discover -q`运行100项，其中99项通过、离线训练器
  因缺少SciPy/scikit-learn跳过1项，相关Python编译通过。服务在临时PAUSED覆盖下重新启动，
  健康检查`active`、`mode=PAUSED`、`motorOutputEnabled=true`、`cameraOnline=true`、
  `videoReady=true`、`runtimeError=null`。测试使用内存串口；现场真实车轮动作、2秒位移和
  网球入料效果未验证，前端测试本轮未运行。整机重启仍会清除临时PAUSED覆盖并恢复AUTO。
- 2026-09-30：修复上述部署后的确认识别崩溃。确认球时原代码重建观测字典，漏掉
  `bottom_exit_loss`，网关读取时抛出`KeyError`导致摄像头线程退出；网页重连无法恢复。改为
  更新原字典，保留全部默认字段，并新增三帧确认路径回归测试。本机
  `.venv\Scripts\python.exe -m unittest discover -q` 101/101、相关Python编译和
  `git diff --check`通过。树莓派停止故障服务时因退出超时被systemd强制结束，确认主进程为0；
  修改前备份`/home/pi/tennis_backups/tennis_pre_camera_keyerror_fix_20260930.tar.gz`。同步修复后
  树莓派定向回归1/1及完整测试101项（100项通过、离线训练器因缺少SciPy/scikit-learn跳过
  1项）、Python编译通过。服务在原有临时PAUSED覆盖下恢复，连续健康检查均为`active`、
  `mode=PAUSED`、`cameraOnline=true`、`videoReady=true`、`runtimeError=null`、`throttled=0x0`。
  树莓派本机回环认证视频WebSocket连续收到两帧有效JPEG（37938/37919字节），确认视频持续更新；
  测试使用内存串口，未发送真实电机运动命令；实际小球入画后的现场视频与2秒补行效果仍待
  用户复测，前端测试本轮未运行。整机重启仍会清除临时PAUSED覆盖并恢复持久AUTO配置。

## 14. 每次修改后的更新检查

- 本文件日期和变更记录是否更新。
- 当前参数、模式、协议字段和部署命令是否仍与代码一致。
- 新增或删除文件是否反映在仓库结构中。
- 真实通过的测试及未运行原因是否记录。
- 树莓派与终端的已完成/未完成边界是否清楚。
- 是否意外写入密码、私钥、令牌、固定Wi-Fi信息或其他秘密。
