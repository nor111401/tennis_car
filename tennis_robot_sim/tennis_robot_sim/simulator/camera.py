"""虚拟摄像头：二维扇形有限视野（理想检测模型）。

检测条件（同时满足）：
1. 目标与摄像头（非小车中心）距离在 [min_detection_distance,
   max_detection_distance] 范围内；
2. 目标相对摄像头朝向的夹角 |bearing| <= 视场角 / 2。

方位角约定（写入文档）：
- bearing 单位为弧度，取值 [-pi, pi)；
- **正号 = 目标在摄像头（机器人）前进方向的左侧（逆时针）**；
- 负号 = 右侧。
该约定与 theta 逆时针为正的数学约定一致。

当前阶段为理想检测：不漏检、不误检、无噪声、无置信度。
为方便后续加入漏检/噪声等模型，检测集中在 get_visible_balls 中。
"""
from __future__ import annotations

import math
from typing import Iterable

import numpy as np

from utils.geometry import normalize_angle, rotate_vector
from .ball import Ball
from .config import CameraConfig
from .types import BallDetection, Pose


class Camera:
    """二维扇形视野摄像头。"""

    def __init__(self, config: CameraConfig) -> None:
        self.config = config

    @property
    def half_fov_rad(self) -> float:
        """视场角的一半（弧度）。"""
        return self.config.field_of_view_rad / 2.0

    def camera_pose(self, robot_pose: Pose) -> Pose:
        """摄像头在世界坐标系中的位姿（与车体固连，朝向与车体一致）。

        偏移量 camera_offset 定义在小车坐标系中（前向为 +x）。
        """
        ox, oy = rotate_vector(self.config.camera_offset_x,
                               self.config.camera_offset_y,
                               robot_pose.theta)
        return Pose(x=robot_pose.x + ox, y=robot_pose.y + oy,
                    theta=robot_pose.theta)

    def is_ball_visible(self, robot_pose: Pose, x: float, y: float) -> bool:
        """判断单个点是否在摄像头视野内（标量版本，便于单点调试）。"""
        cam = self.camera_pose(robot_pose)
        dx = x - cam.x
        dy = y - cam.y
        distance = math.hypot(dx, dy)
        if distance < self.config.min_detection_distance:
            return False
        if distance > self.config.max_detection_distance:
            return False
        bearing = normalize_angle(math.atan2(dy, dx) - cam.theta)
        return abs(bearing) <= self.half_fov_rad

    def get_visible_balls(self, robot_pose: Pose,
                          balls: Iterable[Ball]) -> list[BallDetection]:
        """返回当前可见的网球检测列表（矢量计算，结果有序、无重复）。"""
        active = [b for b in balls if b.is_active()]
        if not active:
            return []

        cam = self.camera_pose(robot_pose)
        bx = np.array([b.x for b in active], dtype=np.float64)
        by = np.array([b.y for b in active], dtype=np.float64)
        dx = bx - cam.x
        dy = by - cam.y

        distance = np.hypot(dx, dy)
        raw_bearing = np.arctan2(dy, dx) - cam.theta
        # 归一化到 [-pi, pi)，与 normalize_angle 约定一致
        bearing = (raw_bearing + np.pi) % (2.0 * np.pi) - np.pi

        min_d = self.config.min_detection_distance
        max_d = self.config.max_detection_distance
        mask = ((distance >= min_d) & (distance <= max_d)
                & (np.abs(bearing) <= self.half_fov_rad))

        detections: list[BallDetection] = []
        for idx in np.flatnonzero(mask):
            b = active[int(idx)]
            detections.append(BallDetection(
                ball_id=b.id,
                world_x=b.x,
                world_y=b.y,
                distance=float(distance[idx]),
                bearing=float(bearing[idx]),
            ))
        return detections

    def detect(self, robot_pose: Pose,
               world_balls: Iterable[Ball]) -> list[BallDetection]:
        """预留检测接口（等价于 get_visible_balls）。

        后续可在该方法内叠加漏检/误检/噪声等模拟层。
        """
        return self.get_visible_balls(robot_pose, world_balls)
