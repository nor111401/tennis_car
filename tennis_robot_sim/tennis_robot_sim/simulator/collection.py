"""简化网球收集判定（不模拟滚筒/传送带/机械碰撞）。"""
from __future__ import annotations

import math

from utils.geometry import normalize_angle
from .config import CollectionConfig
from .types import Pose


class CollectionRule:
    """虚拟收集规则。

    判定条件（同时满足）：
    1. 网球到小车中心的距离 <= distance_m；
    2. 网球相对小车朝向的夹角 |bearing| <= angle_deg / 2。
    其中 angle_deg 为**完整锥角**（在小车前方对称分布 ±angle_deg/2）。
    """

    def __init__(self, config: CollectionConfig) -> None:
        self.config = config

    @property
    def half_angle_rad(self) -> float:
        """收集锥角的一半（弧度）。"""
        return math.radians(self.config.angle_deg) / 2.0

    def can_collect(self, robot_pose: Pose, ball_x: float, ball_y: float) -> bool:
        """判断网球是否满足收集条件。"""
        dx = ball_x - robot_pose.x
        dy = ball_y - robot_pose.y
        distance = math.hypot(dx, dy)
        if distance > self.config.distance_m:
            return False
        bearing = normalize_angle(math.atan2(dy, dx) - robot_pose.theta)
        return abs(bearing) <= self.half_angle_rad
