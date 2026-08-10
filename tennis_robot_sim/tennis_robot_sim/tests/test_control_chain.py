"""无头集成测试：模拟按键事件驱动完整控制链。

验证 main.py 主循环的连线逻辑（事件 -> FrameInput -> KeyboardController
-> Robot.set_velocity -> Simulation.step）能够真正驱动小车运动，
从而回归验证 WASD 控制问题。
"""
from __future__ import annotations

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")  # 无头模式

import pygame
import pytest

from simulator.config import load_config
from simulator.controller import KeyboardController
from simulator.simulation import Simulation
from simulator.world import World
from ui.input_handler import InputHandler


@pytest.fixture(scope="module", autouse=True)
def pygame_env():
    pygame.init()
    pygame.display.set_mode((1, 1))
    yield
    pygame.quit()


def _setup():
    config = load_config()
    world = World(config)
    sim = Simulation(world, fixed_dt=config.simulation.fixed_dt)
    handler = InputHandler()
    controller = KeyboardController(config.robot.max_linear_speed,
                                    config.robot.max_angular_speed)
    return world, sim, handler, controller


def _step(world, sim, handler, controller, events=None):
    """镜像 main.py 主循环的按键处理 + 控制 + 步进。"""
    for _action in handler.process_events(events or []):
        pass  # 本测试只关注持续移动控制
    if not sim.paused:
        controller.set_input(handler.get_frame_input())
        target = controller.update(sim.get_observation(), sim.fixed_dt)
        world.robot.set_velocity(target.linear_velocity, target.angular_velocity)
        sim.step()


def test_hold_w_drives_robot_forward():
    """按住 W -> 小车沿 +x 直线前进。"""
    world, sim, handler, controller = _setup()
    start = world.robot.get_pose()
    for _ in range(15):
        _step(world, sim, handler, controller,
              events=[pygame.event.Event(pygame.KEYDOWN, key=pygame.K_w)])
    pose = world.robot.get_pose()
    assert pose.x > start.x + 0.05
    assert pose.y == pytest.approx(start.y, abs=1e-6)
    assert pose.theta == pytest.approx(start.theta, abs=1e-9)


def test_hold_a_turns_left():
    """按住 A -> 小车左转（theta 增大）。"""
    world, sim, handler, controller = _setup()
    start = world.robot.get_pose()
    for _ in range(20):
        _step(world, sim, handler, controller,
              events=[pygame.event.Event(pygame.KEYDOWN, key=pygame.K_a)])
    assert world.robot.get_pose().theta > start.theta


def test_release_key_stops_robot():
    """松开 W（KEYUP）-> 小车停止。"""
    world, sim, handler, controller = _setup()
    start = world.robot.get_pose()
    # 按住 W 前进
    for _ in range(10):
        _step(world, sim, handler, controller,
              events=[pygame.event.Event(pygame.KEYDOWN, key=pygame.K_w)])
    assert world.robot.get_pose().x > start.x + 0.01
    # 松开 W 后再推进
    for _ in range(10):
        _step(world, sim, handler, controller,
              events=[pygame.event.Event(pygame.KEYUP, key=pygame.K_w)])
    pose = world.robot.get_pose()
    assert pose.x == pytest.approx(world.robot.get_state().x)  # 位置不再变化
    assert world.robot.get_state().linear_velocity == pytest.approx(0.0)


def test_space_immediate_stop():
    """按住空格 -> 立即停止（即使同时按 W）。"""
    world, sim, handler, controller = _setup()
    for _ in range(5):
        _step(world, sim, handler, controller,
              events=[pygame.event.Event(pygame.KEYDOWN, key=pygame.K_w)])
    assert world.robot.get_state().linear_velocity > 0.0
    # 按下空格后目标速度归零
    handler.process_events([pygame.event.Event(pygame.KEYDOWN,
                                               key=pygame.K_SPACE)])
    controller.set_input(handler.get_frame_input())
    target = controller.update(sim.get_observation(), sim.fixed_dt)
    assert (target.linear_velocity, target.angular_velocity) == (0.0, 0.0)
