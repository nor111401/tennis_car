"""世界状态接口与网球可见性维护测试。"""
from __future__ import annotations

import dataclasses
import math

import pytest

from simulator.ball import Ball, BallStatus
from simulator.config import load_config
from simulator.simulation import Simulation
from simulator.world import World


def make_world(count: int = 0) -> World:
    config = load_config()
    cfg = dataclasses.replace(config, balls=dataclasses.replace(config.balls,
                                                                count=count))
    return World(cfg)


def add_ball(world: World, ball_id: int, x: float, y: float) -> Ball:
    ball = Ball(id=ball_id, x=x, y=y, radius=world.config.balls.radius_m)
    world.balls.append(ball)
    return ball


def test_generation_within_bounds_and_avoids_robot():
    """网球生成在场地内且避开小车初始位置。"""
    world = make_world(count=30)
    rx, ry = world.config.robot.initial_x, world.config.robot.initial_y
    avoid_radius = (math.hypot(world.config.robot.length,
                               world.config.robot.width) / 2.0
                    + world.config.balls.radius_m + 0.1)
    assert len(world.balls) == 30
    for ball in world.balls:
        assert 0.0 <= ball.x <= world.config.court.width_m
        assert 0.0 <= ball.y <= world.config.court.height_m
        assert math.hypot(ball.x - rx, ball.y - ry) >= avoid_radius - 1e-6


def test_generation_reproducible_with_seed():
    """相同随机种子 -> 相同的网球分布。"""
    world1 = World(load_config())
    world2 = World(load_config())
    pos1 = [(b.x, b.y) for b in world1.balls]
    pos2 = [(b.x, b.y) for b in world2.balls]
    assert pos1 == pytest.approx(pos2)


def test_ball_visibility_lifecycle():
    """网球从未见 -> 可见 -> 离开可见（HIDDEN）的状态流转。"""
    world = make_world(count=0)
    ball = add_ball(world, 0, 6.0, 3.0)
    world.robot.set_pose(5.0, 3.0, 0.0)

    world.update_visibility()
    assert ball.status is BallStatus.VISIBLE
    assert ball.was_seen is True
    assert [d.ball_id for d in world.get_visible_balls()] == [0]
    assert world.stats()["visible_balls"] == 1
    assert world.stats()["discovered_balls"] == 1

    # 旋转 90° 使其离开视野
    world.robot.set_pose(5.0, 3.0, math.pi / 2.0)
    world.update_visibility()
    assert ball.status is BallStatus.HIDDEN
    assert ball.was_seen is True
    assert world.get_visible_balls() == []
    assert world.stats()["discovered_balls"] == 1


def test_active_balls_exclude_collected():
    """被收集的网球从活动列表中移除。"""
    world = make_world(count=0)
    add_ball(world, 0, 5.2, 3.0)
    add_ball(world, 1, 7.0, 3.0)
    world.robot.set_pose(5.0, 3.0, 0.0)
    world.update_visibility()

    assert world.collect_if_possible() == 1
    assert [b.id for b in world.get_active_balls()] == [1]


def test_collect_ball_direct():
    """直接收集接口：成功 / 重复收集 / 不存在的 id。"""
    world = make_world(count=0)
    ball = add_ball(world, 0, 6.0, 3.0)
    assert world.collect_ball(0) is True
    assert ball.status is BallStatus.COLLECTED
    assert world.collect_ball(0) is False
    assert world.collect_ball(99) is False


def test_reset_restores_initial_state():
    """重置后小车回到初始位姿、收集数清零、网球数量不变。"""
    world = make_world(count=5)
    world.robot.set_pose(8.0, 4.0, 1.0)
    world.collect_if_possible()
    world.reset()

    pose = world.robot.get_pose()
    cfg = world.config.robot
    assert pose.x == pytest.approx(cfg.initial_x)
    assert pose.y == pytest.approx(cfg.initial_y)
    assert pose.theta == pytest.approx(math.radians(cfg.initial_theta_deg))
    assert world.stats()["collected_balls"] == 0
    assert len(world.balls) == 5


def test_simulation_step_advances_time():
    """仿真按固定步长推进时间。"""
    world = make_world(count=0)
    sim = Simulation(world, fixed_dt=0.05)
    sim.step()
    assert sim.time == pytest.approx(0.05)
    assert sim.paused is False
    sim.toggle_pause()
    assert sim.paused is True


def test_observation_snapshot():
    """观测快照包含时间、机器人状态与可见目标。"""
    world = make_world(count=0)
    add_ball(world, 0, 6.0, 3.0)
    world.robot.set_pose(5.0, 3.0, 0.0)
    world.update_visibility()

    obs = world.build_observation(time=1.5)
    assert obs.time == pytest.approx(1.5)
    assert obs.robot.x == pytest.approx(5.0)
    assert [d.ball_id for d in obs.visible_balls] == [0]
    assert obs.stats["total_balls"] == 1
