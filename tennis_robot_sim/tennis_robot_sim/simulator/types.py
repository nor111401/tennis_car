"""跨模块共享的数据类型定义。"""
from __future__ import annotations

from dataclasses import dataclass

from .ball import Ball


@dataclass(frozen=True)
class Pose:
    """二维位姿：位置 (x, y) 与朝向 theta。

    - 单位：米 / 弧度；
    - theta 归一化到 [-pi, pi)，逆时针为正。
    """

    x: float
    y: float
    theta: float


@dataclass
class RobotState:
    """差速小车完整状态。"""

    x: float                 # 世界 x（米）
    y: float                 # 世界 y（米）
    theta: float             # 朝向（弧度，[-pi, pi)）
    linear_velocity: float   # 车体线速度（m/s）
    angular_velocity: float  # 车体角速度（rad/s）
    left_wheel_speed: float  # 左轮线速度（m/s）
    right_wheel_speed: float # 右轮线速度（m/s）


@dataclass(frozen=True)
class BallDetection:
    """一个可见网球检测结果。

    - distance：网球到摄像头（非小车中心）的距离，米；
    - bearing：网球相对摄像头朝向的方位角，弧度，[-pi, pi)；
      正号 = 目标在左侧（逆时针方向），负号 = 右侧。
    """

    ball_id: int
    world_x: float
    world_y: float
    distance: float
    bearing: float


@dataclass(frozen=True)
class TargetVelocity:
    """控制器输出的目标速度。"""

    linear_velocity: float   # m/s
    angular_velocity: float  # rad/s，正 = 左转（逆时针）


@dataclass(frozen=True)
class FrameInput:
    """一帧的逻辑按键状态（由 UI 层填充，控制器消费）。"""

    forward: bool = False
    backward: bool = False
    left: bool = False
    right: bool = False
    stop: bool = False


@dataclass(frozen=True)
class Observation:
    """控制器观测：世界状态的只读快照。"""

    time: float
    robot: RobotState
    visible_balls: tuple[BallDetection, ...]
    active_balls: tuple[Ball, ...]
    stats: dict
