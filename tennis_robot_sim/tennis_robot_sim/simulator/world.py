"""仿真世界：场地 + 小车 + 网球 + 摄像头 + 收集规则。

世界对象持有所有仿真实体，并维护：
- 每个网球的历史可见信息（Ball.was_seen）；
- 每个网球的当前可见状态（Ball.status，由 update_visibility 刷新）；
- 已收集数量、选中的测试目标。
本阶段不实现多目标记忆/数据关联，仅为后续模块预留状态字段。
"""
from __future__ import annotations

import logging
import math
import random

from utils.logger import get_logger
from .ball import Ball, BallGenerator, BallStatus
from .camera import Camera
from .collection import CollectionRule
from .config import SimConfig
from .controller import Observation
from .court import Court
from .robot import Robot
from .types import BallDetection


class World:
    """仿真世界的唯一入口；UI 层只读，主循环通过 World 修改状态。"""

    def __init__(self, config: SimConfig,
                 logger: logging.Logger | None = None) -> None:
        self.config = config
        self.logger = logger or get_logger()

        self.court = Court(config.court.width_m, config.court.height_m)
        self.robot = Robot(config.robot)
        self.robot.set_court_bounds(self.court.width_m, self.court.height_m)
        self.camera = Camera(config.camera)
        self.collection = CollectionRule(config.collection)

        # 随机源：保证相同随机种子可复现
        self._rng = random.Random(config.balls.random_seed)
        self._generator = BallGenerator(config.balls, config.court, self._rng)

        self.balls: list[Ball] = self._generate_balls()
        self._last_visible: list[BallDetection] = []
        self._prev_visible_ids: set[int] = set()
        self.selected_ball_id: int | None = None
        self.collected_count: int = 0

        self.logger.info("世界初始化完成：%d 个网球", len(self.balls))

    # -- 接口 -------------------------------------------------------------

    def get_active_balls(self) -> list[Ball]:
        """返回未被收集的网球。"""
        return [b for b in self.balls if b.is_active()]

    def get_visible_balls(self) -> list[BallDetection]:
        """返回当前可见的网球检测列表（上一次可见性更新的缓存结果）。"""
        return list(self._last_visible)

    def collect_ball(self, ball_id: int) -> bool:
        """将指定网球标记为已收集；返回是否成功收集。"""
        ball = self._find_ball(ball_id)
        if ball is None:
            self.logger.warning("尝试收集不存在的网球 #%d", ball_id)
            return False
        if ball.status is BallStatus.COLLECTED:
            self.logger.debug("网球 #%d 已收集，忽略重复收集", ball_id)
            return False
        ball.status = BallStatus.COLLECTED
        self.collected_count += 1
        if self.selected_ball_id == ball_id:
            self.selected_ball_id = None
        self.logger.info(
            "网球 #%d 已被收集 @ (%.2f, %.2f)，当前已收集 %d 个",
            ball_id, ball.x, ball.y, self.collected_count,
        )
        return True

    def reset(self) -> None:
        """重置小车位姿并按固定种子重新生成网球。"""
        self.robot.reset()
        self.balls = self._generate_balls()
        self.collected_count = 0
        self.selected_ball_id = None
        self._last_visible = []
        self._prev_visible_ids = set()
        self.logger.info("小车和网球已重置")

    def regenerate_balls(self) -> None:
        """使用相同随机种子重新随机生成网球（场景重摆）。"""
        self.balls = self._generate_balls()
        self.collected_count = 0
        self.selected_ball_id = None
        self._last_visible = []
        self._prev_visible_ids = set()
        self.logger.info("网球已重新生成（共 %d 个）", len(self.balls))

    def update_visibility(self) -> None:
        """刷新所有网球的可视状态，并记录首次看见 / 离开视野事件。"""
        pose = self.robot.get_pose()
        active = self.get_active_balls()
        detections = self.camera.get_visible_balls(pose, active)
        visible_ids = {d.ball_id for d in detections}

        for ball in active:
            if ball.id in visible_ids:
                if not ball.was_seen:
                    ball.was_seen = True
                    self.logger.info("网球 #%d 首次进入视野 @ (%.2f, %.2f)",
                                     ball.id, ball.x, ball.y)
                if ball.status is not BallStatus.VISIBLE:
                    ball.status = BallStatus.VISIBLE
            else:
                if ball.was_seen and ball.status is BallStatus.VISIBLE:
                    self.logger.info("网球 #%d 离开视野", ball.id)
                ball.status = (BallStatus.HIDDEN if ball.was_seen
                               else BallStatus.UNSEEN)

        self._last_visible = detections
        self._prev_visible_ids = visible_ids

    def collect_if_possible(self) -> int:
        """收集当前满足收集条件的网球，返回本次收集数量。"""
        pose = self.robot.get_pose()
        count = 0
        for ball in self.get_active_balls():
            if self.collection.can_collect(pose, ball.x, ball.y):
                if self.collect_ball(ball.id):
                    count += 1
        if count > 0:
            self.logger.info("本次共收集 %d 个网球", count)
        return count

    def try_auto_collect(self) -> int:
        """若配置开启自动收集则执行收集，否则不动作。"""
        if not self.config.collection.auto_collect:
            return 0
        return self.collect_if_possible()

    def cycle_selected_target(self) -> None:
        """在可见网球之间循环切换选中的测试目标。"""
        visible = [b for b in self.balls
                   if b.is_active() and b.status is BallStatus.VISIBLE]
        if not visible:
            self.selected_ball_id = None
            self.logger.debug("当前无可见目标可选中")
            return
        if self.selected_ball_id is None or \
                all(b.id != self.selected_ball_id for b in visible):
            self.selected_ball_id = visible[0].id
        else:
            idx = next(i for i, b in enumerate(visible)
                       if b.id == self.selected_ball_id)
            self.selected_ball_id = visible[(idx + 1) % len(visible)].id
        self.logger.info("选中测试目标 网球 #%d", self.selected_ball_id)

    def stats(self) -> dict:
        """实时统计信息（供状态面板显示）。"""
        total = len(self.balls)
        visible = sum(1 for b in self.balls
                      if b.status is BallStatus.VISIBLE)
        discovered = sum(1 for b in self.balls if b.was_seen)
        return {
            "total_balls": total,
            "visible_balls": visible,
            "discovered_balls": discovered,
            "collected_balls": self.collected_count,
        }

    def build_observation(self, time: float) -> Observation:
        """构造控制器观测（世界状态的只读快照）。"""
        return Observation(
            time=time,
            robot=self.robot.get_state(),
            visible_balls=tuple(self._last_visible),
            active_balls=tuple(self.get_active_balls()),
            stats=self.stats(),
        )

    # -- 内部 -------------------------------------------------------------

    def _generate_balls(self) -> list[Ball]:
        # 避让半径：小车外接圆半径 + 网球半径 + 少量余量
        avoid_radius = (math.hypot(self.config.robot.length,
                                   self.config.robot.width) / 2.0
                        + self.config.balls.radius_m + 0.1)
        return self._generator.generate(self.config.robot.initial_x,
                                        self.config.robot.initial_y,
                                        avoid_radius)

    def _find_ball(self, ball_id: int) -> Ball | None:
        for ball in self.balls:
            if ball.id == ball_id:
                return ball
        return None
