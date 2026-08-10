"""两轮差速小车运动学模型。

速度单位约定：
- 车体线速度 linear_velocity : 米/秒（m/s）；
- 车体角速度 angular_velocity : 弧度/秒（rad/s），正 = 左转（逆时针）；
- 左右轮速度 left/right_wheel_speed : **米/秒（车轮线速度）**，非角速度。
  需要车轮角速度（rad/s）时使用 wheel_angular_speeds() 换算。

差速运动学：
    v     = (v_left + v_right) / 2
    omega = (v_right - v_left) / wheel_base
    x'    = x + v * cos(theta) * dt
    y'    = y + v * sin(theta) * dt
    theta'= normalize(theta + omega * dt)
"""
from __future__ import annotations

import math

from utils.geometry import clamp, normalize_angle
from .config import RobotConfig
from .types import Pose, RobotState


class Robot:
    """简化的两轮差速小车。

    运动模型与显示解耦：本类不依赖 pygame，任何对位姿的修改
    都通过 set_velocity / set_wheel_speeds / update 完成。
    """

    def __init__(self, config: RobotConfig) -> None:
        self.config = config
        self.state = RobotState(
            x=config.initial_x,
            y=config.initial_y,
            theta=math.radians(config.initial_theta_deg),
            linear_velocity=0.0,
            angular_velocity=0.0,
            left_wheel_speed=0.0,
            right_wheel_speed=0.0,
        )
        self._court_width_m: float | None = None
        self._court_height_m: float | None = None

    # -- 外部接口 ---------------------------------------------------------

    def set_court_bounds(self, width_m: float, height_m: float) -> None:
        """设置场地边界，用于防止小车驶出场地。"""
        self._court_width_m = width_m
        self._court_height_m = height_m

    def reset(self) -> None:
        """恢复到初始位姿与零速度。"""
        cfg = self.config
        self.state = RobotState(
            x=cfg.initial_x,
            y=cfg.initial_y,
            theta=math.radians(cfg.initial_theta_deg),
            linear_velocity=0.0,
            angular_velocity=0.0,
            left_wheel_speed=0.0,
            right_wheel_speed=0.0,
        )

    def set_velocity(self, linear_velocity: float, angular_velocity: float) -> None:
        """方式一：按线速度 + 角速度控制（自动限幅并换算轮速）。"""
        v = clamp(linear_velocity, -self.config.max_linear_speed,
                  self.config.max_linear_speed)
        omega = clamp(angular_velocity, -self.config.max_angular_speed,
                      self.config.max_angular_speed)
        self.state.linear_velocity = v
        self.state.angular_velocity = omega
        # 逆运动学：由 (v, omega) 求左右轮线速度（m/s）
        self.state.left_wheel_speed = v - omega * self.config.wheel_base / 2.0
        self.state.right_wheel_speed = v + omega * self.config.wheel_base / 2.0

    def set_wheel_speeds(self, left_speed: float, right_speed: float) -> None:
        """方式二：按左右轮速度控制（单位 m/s）。

        左右轮速度被限制在 [-max_linear_speed, max_linear_speed] 内；
        车体速度由差速运动学正解严格得出（不再额外截断角速度，
        因为轮速是物理输入，角速度由轮速决定）。
        """
        max_v = self.config.max_linear_speed
        left = clamp(left_speed, -max_v, max_v)
        right = clamp(right_speed, -max_v, max_v)
        self.state.left_wheel_speed = left
        self.state.right_wheel_speed = right
        # 差速运动学正解
        self.state.linear_velocity = (left + right) / 2.0
        self.state.angular_velocity = (right - left) / self.config.wheel_base

    def stop(self) -> None:
        """立即停止。"""
        self.set_velocity(0.0, 0.0)

    def set_pose(self, x: float, y: float, theta: float) -> None:
        """直接设置位姿（测试/场景初始化用，不改动速度）。"""
        self.state.x = x
        self.state.y = y
        self.state.theta = normalize_angle(theta)

    def get_pose(self) -> Pose:
        """当前位姿快照。"""
        s = self.state
        return Pose(x=s.x, y=s.y, theta=s.theta)

    def get_state(self) -> RobotState:
        """当前完整状态快照（副本，外部修改不影响内部）。"""
        from dataclasses import replace

        return replace(self.state)

    def wheel_angular_speeds(self) -> tuple[float, float]:
        """左右轮角速度（rad/s）= 线速度 / wheel_radius。"""
        if self.config.wheel_radius <= 0:
            raise ValueError("wheel_radius 必须大于零才能换算车轮角速度")
        return (self.state.left_wheel_speed / self.config.wheel_radius,
                self.state.right_wheel_speed / self.config.wheel_radius)

    # -- 运动学更新 --------------------------------------------------------

    def update(self, dt: float) -> None:
        """按当前速度积分一个时间步长 dt（秒）。"""
        if dt < 0:
            raise ValueError("时间步长不能为负")
        s = self.state
        # 连续模型积分：使用积分起始时刻的速度
        s.x += s.linear_velocity * math.cos(s.theta) * dt
        s.y += s.linear_velocity * math.sin(s.theta) * dt
        s.theta = normalize_angle(s.theta + s.angular_velocity * dt)
        self._clamp_to_court()

    def _clamp_to_court(self) -> None:
        """将小车中心限制在场地内（考虑车体半尺寸，避免越界）。"""
        if self._court_width_m is None or self._court_height_m is None:
            return
        half_len = self.config.length / 2.0
        half_wid = self.config.width / 2.0
        low_x = min(half_len, self._court_width_m / 2.0)
        high_x = max(self._court_width_m - half_len, low_x)
        low_y = min(half_wid, self._court_height_m / 2.0)
        high_y = max(self._court_height_m - half_wid, low_y)
        self.state.x = clamp(self.state.x, low_x, high_x)
        self.state.y = clamp(self.state.y, low_y, high_y)
