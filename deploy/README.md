# 树莓派网关部署

网关已经接入摄像头、识别、遥测、认证视频和统一电机仲裁。基础 systemd 模板设置
`TENNIS_MOTOR_ENABLE=1`、`TENNIS_MODE_GPIO_ENABLE=1`，并使用 BCM17（物理排针 11）作为
追踪/捡球模式输出。基础模板的开机模式是`AUTO`；本车持久drop-in负责改为`PAUSED`。
本车已安装该drop-in，持久超声避障关闭，整机重启后保持`PAUSED`；本次开机另有临时启用覆盖。
不能单独安装基础模板而遗漏本车PAUSED覆盖。常驻控制端口必须启用认证。

## 已完成

2026-10-07超声试用：持久`zz-obstacle-commissioning.conf`仍为避障0/开机PAUSED。
临时模板`tennis-robot-gateway-ultrasonic-trial.conf`只安装到
`/run/systemd/system/tennis-robot-gateway.service.d/zzz-ultrasonic-trial-paused.conf`，
使本次开机避障1/开机PAUSED；整机重启后恢复避障0。不要将试用模板安装到`/etc`或删除
持久安全覆盖。仅当服务PAUSED时备份、停服并安装，并核对启动仍PAUSED。
用户随后要求不再测试，未继续近/远物体测距或试车；只完成启用与运行状态核对。
启用后AUTO避障优先于固定3秒收集，≤20cm会取消收集；小球也可能被当作障碍物。
未锁定近障碍时无回波放行，锁定后必须连续两次实测>30cm才恢复；不是可靠防撞保证。
此轮不由助手切换AUTO或发转向/前进命令。

- AUTO搜索发现有效但待三帧确认的主候选，先STOP观察最多1秒（`TARGET VERIFY`），
  停稳后的新确认帧才追踪；超时继续下一搜索步，不被重复候选无限续期。持续未确认候选
  需搜索冷却后新的无候选帧才能重新停车。待确认黄点、确认红点、其他球蓝点。
  不降低识别门槛、不改变80%下沿入口和3秒收集；暂停/急停/相机等安全仲裁优先。
- 源码目录：`/home/pi/tennis/robot_gateway`
- 独立虚拟环境：`/home/pi/tennis/.venv-gateway`
- 端口：TCP 8765，控制路径 `/ws`，视频路径 `/video`
- 健康检查：`http://树莓派地址:8765/health`
- 追踪模式：BCM17 输出低电平；捡球模式：BCM17 输出高电平（约3.3V）。
- BCM17 与 UART 使用的 BCM14/15（物理排针 8/10）不冲突。树莓派 GPIO 只能用作逻辑信号，
  外接控制板须共地且输入兼容 3.3V；不可直接驱动电机、线圈或其他大电流负载。

## 超声波避障（接线验证后启用）

用户提供的新版 HC-SR04/CS100A 模块资料标称 DC 3–5.5V，当前接线方案只针对该型号：
模块 VCC → 树莓派 3.3V 实体 1 或 17；GND → 实体 6；Trig → BCM23/实体 16；
Echo → BCM24/实体 18。务必先断电接线并核对实物型号。这里以 3.3V 供电，资料原理图
显示 Echo 芯片数字电源跟随 VCC，因此按 3.3V Echo 直连；如改用 5V 供电，Echo 必须先
降压到 GPIO 安全电平，不能直接接树莓派。资料要求 Trig 高电平至少 10µs；无目标时
Echo 约 66ms；相邻测量至少间隔 70ms。当前采样周期 85ms，使用 `lgpio` 的内核边沿
时间戳而非 Python 轮询脉冲。`lgpio` 由树莓派系统包提供，重建网关虚拟环境后需确认
`.venv-gateway/bin/python -c 'import lgpio'` 成功。

`TENNIS_OBSTACLE_ENABLE` 默认和 service 模板均为 `0`，尚未接线时不会把 BCM23 设为输出。
只有完成接线、静止测距以及电机物理安全确认后，才把它设为 `1` 并重启网关。
已接线且完成静态近/远阈值验证的这台车，使用
`deploy/tennis-robot-gateway-obstacle-commissioning.conf` 作为持久 systemd drop-in。
该持久文件设定`TENNIS_OBSTACLE_ENABLE=0`并保留`TENNIS_GATEWAY_BOOT_MODE=PAUSED`。
没有临时覆盖时AUTO不读取超声，BCM23/24不由网关占用；本次开机临时试用覆盖使开关为1，
启用采样及AUTO避障。整机重启恢复关闭；普通服务重启仍保留临时试用。
只能在空旷场地、有人看护且急停和物理电源开关可用时人工切换AUTO；不得恢复AUTO开机。
AUTO 下有效读数≤20cm即停车、取消捡球并进入避障；每次向左转 200ms 后停车静置、重新
测距，连续两次新读数>30cm后停车等待新的摄像头画面，再恢复寻球。未锁定近障碍时完整
周期无回波/超范围允许寻球；已锁定后无回波保持停车。异常回波、读数过期或GPIO初始化失败
也停车；最多45个短转向步仍未清障则锁定停车，需切换模式或重启后
重新尝试。20/30cm 可通过 `TENNIS_OBSTACLE_ENTER_CM`/`TENNIS_OBSTACLE_CLEAR_CM` 调整；
Trig/Echo 引脚也可通过 `TENNIS_OBSTACLE_TRIG_PIN`/`TENNIS_OBSTACLE_ECHO_PIN` 调整。
此单前向传感器无法检查车侧/车后障碍物；地面网球也可能被识别为障碍，安装高度和角度需
现场标定。MANUAL 不受本传感器仲裁，急停和 PAUSED 始终优先。

网关虚拟环境需要访问 Raspberry Pi OS 提供的 Picamera2/NumPy，以及 `pi` 用户现有的
OpenCV。安装或重建虚拟环境后执行：

```bash
sh /home/pi/tennis/deploy/configure_gateway_venv.sh
```

脚本通过 `.pth` 追加系统包路径，不使用会覆盖 FastAPI 依赖优先级的全局 `PYTHONPATH`。

## 安装为开机服务

先在树莓派本地生成令牌；令牌只保存在树莓派和受信任终端中，不提交到 Git：

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
sudoedit /etc/tennis-robot-gateway.env
```

在编辑器中写入一行，其中实际令牌至少 20 个字符：

```text
TENNIS_GATEWAY_TOKEN=在这里填入刚生成的令牌
```

然后限制文件权限并安装服务：

```bash
sudo chown root:root /etc/tennis-robot-gateway.env
sudo chmod 600 /etc/tennis-robot-gateway.env
sudo cp /home/pi/tennis/deploy/tennis-robot-gateway.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now tennis-robot-gateway.service
sudo systemctl status tennis-robot-gateway.service --no-pager -l
```

Windows/安卓终端连接时，把同一令牌填入界面的“访问令牌”输入框。若环境文件缺失或令牌
长度不足，服务模板会拒绝启动。不要把 8765 端口映射到公网；远程访问应使用可信 VPN。

终端“追踪/捡球模式”按钮在 MANUAL/PAUSED 下要求取得控制权。GPIO 输出在线时，选择
追踪模式将 BCM17 拉低，选择捡球模式将 BCM17 拉高。AUTO下由网关管理：
已确认可见球框下沿≥0.80、球心在近区中心±0.15内且允许前进时，立即启动固定3秒
直行与3秒收集高电平；允许从近处起步，不再等待空帧。启动后目标消失、重现、半球拒绝、
待确认、偏移或视觉过近均不打断、不续期；到时停车并拉低。暂停、手动、急停、
相机异常/超过0.5秒无新观察、UART故障和已启用避障仍优先取消，正常退出也拉低。
前进每条UART指令最长300ms，按剩余窗口截短。结束后同一近球保持STOP/PICKUP COMPLETE，
不重复开启3秒；需结束后的新上方确认球允许前进，或人工停车/模式切换重置才可重触发。
近区下沿默认≥0.80、小偏差继续直行，大偏差仍先对准；远区容差仍±0.06。
可用`TENNIS_NEAR_AIM_MIN_BOTTOM`和`TENNIS_NEAR_AIM_DEADBAND`调节。
兼容参数名`TENNIS_BOTTOM_EXIT_MIN_BOTTOM`默认0.80、`TENNIS_BOTTOM_EXIT_FORWARD_SECONDS`
和`TENNIS_PICKUP_OPEN_SECONDS`均默认3.0（前进0禁用，两者上限5秒，装置不少于前进）。
入口前仍要求视觉验证、未达到面积停车条件和转向后新帧；旧准备/空帧/半球等待路径已移除。
诊断看`VISION STATE`及`PICKUP STATE: NEAR_BALL/DRIVE_DONE/COMPLETE/RESET_EXTERNAL`；
系统日志断电后不保留。无入料/车轮反馈，3秒不保证真实位移或收集，且超声当前关闭，
须在空旷有人看护、物理电源/急停可用的场地验证。
`tennis-robot-gateway-runtime-paused.conf` 是临时 PAUSED 覆盖的模板；本车开机PAUSED
由上述持久drop-in保证。
