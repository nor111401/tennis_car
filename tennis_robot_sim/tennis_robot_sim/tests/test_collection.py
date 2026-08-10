"""简化收集判定单元测试（含世界层面的重复收集防护）。"""
from __future__ import annotations

import dataclasses
import math

import pytest

from simulator.ball import Ball, BallStatus
from simulator.collection import CollectionRule
from simulator.config import CollectionConfig, load_config
from simulator.types import Pose
from simulator.world import World

POSE = Pose(x=5.0, y=3.0, theta=0.0)


def make_rule(**overrides) -> CollectionRule:
    base = CollectionConfig(distance_m=0.3, angle_deg=30.0, auto_collect=True)
    return CollectionRule(dataclasses.replace(base, **overrides))


def test_collectable_when_distance_and_angle_ok():
    """距离与角度均满足 -> 可收集。"""
    rule = make_rule()
    assert rule.can_collect(POSE, 5.2, 3.0)  # 距离 0.2，方位 0°


def test_not_collectable_when_angle_too_large():
    """距离满足但角度超出 -> 不可收集。"""
    rule = make_rule()  # 锥角 ±15°
    assert not rule.can_collect(POSE, 5.2, 3.2)  # 距离 ~0.28，方位 45°


def test_not_collectable_when_distance_too_large():
    """角度满足但距离超出 -> 不可收集。"""
    rule = make_rule()
    assert not rule.can_collect(POSE, 5.4, 3.0)  # 距离 0.4 > 0.3


def test_angle_is_full_cone():
    """angle_deg 为完整锥角，边界含边界本身。"""
    rule = make_rule(angle_deg=30.0)  # ±15°
    half = math.radians(15.0)
    on_edge = (5.0 + 0.25 * math.cos(half), 3.0 + 0.25 * math.sin(half))
    assert rule.can_collect(POSE, *on_edge)
    just_out = (5.0 + 0.25 * math.cos(half + 0.05),
                3.0 + 0.25 * math.sin(half + 0.05))
    assert not rule.can_collect(POSE, *just_out)


def test_collected_ball_not_recollected():
    """世界层面：已收集网球不能重复收集。"""
    config = load_config()
    cfg = dataclasses.replace(config, balls=dataclasses.replace(config.balls,
                                                                count=0))
    world = World(cfg)
    ball = Ball(id=0, x=5.2, y=3.0, radius=config.balls.radius_m)
    world.balls.append(ball)
    world.robot.set_pose(5.0, 3.0, 0.0)
    world.update_visibility()

    assert world.collect_if_possible() == 1
    assert world.stats()["collected_balls"] == 1
    assert ball.status is BallStatus.COLLECTED

    assert world.collect_if_possible() == 0
    assert world.stats()["collected_balls"] == 1


def test_auto_collect_respects_config():
    """自动收集开关：关闭时不自动收集，开启时自动收集。"""
    config = load_config()
    base = dataclasses.replace(config, balls=dataclasses.replace(config.balls,
                                                                 count=0))
    # 关闭自动收集
    world_off = World(base)
    world_off.balls.append(Ball(id=0, x=5.2, y=3.0,
                                radius=config.balls.radius_m))
    world_off.robot.set_pose(5.0, 3.0, 0.0)
    assert world_off.try_auto_collect() == 0
    assert world_off.stats()["collected_balls"] == 0

    # 开启自动收集
    cfg_on = dataclasses.replace(
        base, collection=dataclasses.replace(base.collection, auto_collect=True))
    world_on = World(cfg_on)
    world_on.balls.append(Ball(id=0, x=5.2, y=3.0,
                               radius=config.balls.radius_m))
    world_on.robot.set_pose(5.0, 3.0, 0.0)
    assert world_on.try_auto_collect() == 1
    assert world_on.stats()["collected_balls"] == 1
