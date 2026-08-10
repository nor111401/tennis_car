"""差速小车运动学单元测试。

覆盖：直线运动 / 原地转向 / 曲线运动 / 零速度 / 速度限幅 /
角度归一化 / 场地边界 / 正逆运动学换算。
"""
from __future__ import annotations

import dataclasses
import math

import pytest

from simulator.config import RobotConfig
from simulator.robot import Robot


def make_robot(**overrides) -> Robot:
    base = RobotConfig(
        initial_x=1.0, initial_y=1.0, initial_theta_deg=0.0,
        wheel_base=0.35, wheel_radius=0.05, length=0.45, width=0.35,
        max_linear_speed=1.0, max_angular_speed=2.0,
    )
    robot = Robot(dataclasses.replace(base, **overrides))
    robot.set_court_bounds(10.0, 6.0)
    return robot


def test_straight_line_motion():
    """左右轮速度相等 -> 沿朝向直线运动。"""
    robot = make_robot()
    robot.set_wheel_speeds(0.5, 0.5)
    robot.update(1.0)
    pose = robot.get_pose()
    assert pose.x == pytest.approx(1.5, abs=1e-9)
    assert pose.y == pytest.approx(1.0, abs=1e-9)
    assert pose.theta == pytest.approx(0.0, abs=1e-9)


def test_turn_in_place():
    """左右轮反向等速 -> 原地转向，位置不变。"""
    robot = make_robot()
    robot.set_wheel_speeds(-1.0, 1.0)
    dt = 0.1
    robot.update(dt)
    expected_omega = (1.0 - (-1.0)) / 0.35  # rad/s
    pose = robot.get_pose()
    assert pose.theta == pytest.approx(expected_omega * dt, abs=1e-9)
    assert pose.x == pytest.approx(1.0, abs=1e-9)
    assert pose.y == pytest.approx(1.0, abs=1e-9)


def test_curved_motion():
    """左右轮速度不等 -> 位置与朝向均变化（曲线运动）。"""
    robot = make_robot()
    robot.set_wheel_speeds(0.2, 0.5)
    before = robot.get_pose()
    robot.update(0.2)
    after = robot.get_pose()
    assert (after.x, after.y) != (before.x, before.y)
    assert after.theta != before.theta
    state = robot.get_state()
    assert state.left_wheel_speed == pytest.approx(0.2)
    assert state.right_wheel_speed == pytest.approx(0.5)


def test_zero_velocity_no_motion():
    """零速度 -> 位姿不变化。"""
    robot = make_robot()
    robot.set_wheel_speeds(0.0, 0.0)
    robot.update(1.0)
    pose = robot.get_pose()
    assert (pose.x, pose.y, pose.theta) == (1.0, 1.0, 0.0)


def test_wheel_speed_clamp():
    """左右轮速度超过上限 -> 被限幅。"""
    robot = make_robot(max_linear_speed=1.0)
    robot.set_wheel_speeds(5.0, -5.0)
    state = robot.get_state()
    assert state.left_wheel_speed == pytest.approx(1.0)
    assert state.right_wheel_speed == pytest.approx(-1.0)
    assert state.linear_velocity == pytest.approx(0.0)


def test_velocity_clamp():
    """线速度/角速度超过上限 -> 被限幅。"""
    robot = make_robot(max_linear_speed=1.0, max_angular_speed=2.0)
    robot.set_velocity(5.0, 3.0)
    state = robot.get_state()
    assert state.linear_velocity == pytest.approx(1.0)
    assert state.angular_velocity == pytest.approx(2.0)


def test_theta_normalized():
    """长时间旋转后朝向始终归一化到 [-pi, pi)。"""
    robot = make_robot()
    robot.set_velocity(0.0, 2.0)
    for _ in range(200):
        robot.update(0.05)
    theta = robot.get_pose().theta
    assert -math.pi <= theta < math.pi


def test_stays_in_court():
    """小车不能驶出场地。"""
    robot = make_robot(initial_x=0.1, initial_y=3.0)
    robot.set_court_bounds(10.0, 6.0)
    robot.set_velocity(1.0, 0.0)
    for _ in range(300):
        robot.update(0.05)
    pose = robot.get_pose()
    half_len = 0.45 / 2.0
    assert pose.x >= half_len - 1e-9
    assert pose.x <= 10.0 - half_len + 1e-9
    assert 0.0 <= pose.y <= 6.0


def test_set_velocity_inverse_kinematics():
    """由 (v, omega) 换算左右轮速度。"""
    robot = make_robot()
    robot.set_velocity(0.5, 0.0)
    state = robot.get_state()
    assert state.left_wheel_speed == pytest.approx(0.5)
    assert state.right_wheel_speed == pytest.approx(0.5)

    robot.set_velocity(0.0, 2.0)
    state = robot.get_state()
    # v_left = v - omega*base/2 = -0.35；v_right = +0.35
    assert state.left_wheel_speed == pytest.approx(-0.35)
    assert state.right_wheel_speed == pytest.approx(0.35)


def test_set_wheel_speeds_forward_kinematics():
    """由左右轮速度换算 (v, omega)。"""
    robot = make_robot()
    robot.set_wheel_speeds(0.4, 0.6)
    state = robot.get_state()
    assert state.linear_velocity == pytest.approx(0.5)
    assert state.angular_velocity == pytest.approx((0.6 - 0.4) / 0.35)
