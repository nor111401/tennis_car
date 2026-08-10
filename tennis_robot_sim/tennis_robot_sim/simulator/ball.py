"""网球模型与随机生成。

状态区分（本节按需求保留）：
- Ball.status  : 网球真实状态（是否被收集）+ 当前可见性；
- Ball.was_seen: 历史是否曾进入过视野（用于“历史已发现”统计）。
本阶段不实现目标跟踪/数据关联，仅维护上述两层信息。
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from enum import Enum, auto

from .config import BallsConfig, CourtConfig


class BallStatus(Enum):
    """网球在仿真中的状态。"""

    UNSEEN = auto()     # 从未进入过摄像头视野
    VISIBLE = auto()    # 当前在摄像头视野内
    HIDDEN = auto()     # 曾经进入过视野，当前不在视野内
    COLLECTED = auto()  # 已被小车收集


@dataclass
class Ball:
    """一个网球。"""

    id: int
    x: float                  # 世界 x（米）
    y: float                  # 世界 y（米）
    radius: float             # 半径（米）
    status: BallStatus = BallStatus.UNSEEN
    was_seen: bool = False    # 历史是否进入过视野

    def is_active(self) -> bool:
        """网球是否仍参与仿真（未被收集）。"""
        return self.status is not BallStatus.COLLECTED


class BallGenerator:
    """按配置随机生成网球。

    保证：
    - 网球中心位于场地范围内（含半径 + 边距内缩）；
    - 网球避开小车初始位置（avoid_radius 半径圆之外）。
    """

    MAX_ATTEMPTS_PER_BALL = 200

    def __init__(self, config: BallsConfig, court: CourtConfig,
                 rng: random.Random | None = None) -> None:
        self.config = config
        self.court = court
        self.rng = rng if rng is not None else random.Random(config.random_seed)

    def _sample_position(self, avoid_x: float, avoid_y: float,
                         avoid_radius: float) -> tuple[float, float]:
        """在场地内采样一个避开小车初始位置的坐标。"""
        margin = self.config.radius_m + self.config.spawn_margin_m
        lo_x = margin
        hi_x = self.court.width_m - margin
        lo_y = margin
        hi_y = self.court.height_m - margin
        if hi_x <= lo_x or hi_y <= lo_y:
            raise ValueError(
                "场地过小，无法容纳网球（请增大场地或减小网球半径/边距）"
            )
        for _ in range(self.MAX_ATTEMPTS_PER_BALL):
            x = self.rng.uniform(lo_x, hi_x)
            y = self.rng.uniform(lo_y, hi_y)
            if math.hypot(x - avoid_x, y - avoid_y) >= avoid_radius:
                return x, y
        # 极端情况下回退：返回最后一个仍位于场地内的随机点
        return self.rng.uniform(lo_x, hi_x), self.rng.uniform(lo_y, hi_y)

    def generate(self, avoid_x: float, avoid_y: float,
                 avoid_radius: float) -> list[Ball]:
        """生成 config.count 个网球。"""
        balls: list[Ball] = []
        for i in range(self.config.count):
            x, y = self._sample_position(avoid_x, avoid_y, avoid_radius)
            balls.append(Ball(id=i, x=x, y=y, radius=self.config.radius_m))
        return balls
