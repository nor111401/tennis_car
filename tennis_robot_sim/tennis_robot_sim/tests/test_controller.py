"""键盘控制器映射单元测试（不依赖 pygame / 显示）。"""
from __future__ import annotations

import pytest

from simulator.controller import BaseController, KeyboardController
from simulator.types import FrameInput


def make_controller() -> KeyboardController:
    return KeyboardController(max_linear_speed=1.0, max_angular_speed=2.0)


def test_forward():
    ctrl = make_controller()
    ctrl.set_input(FrameInput(forward=True))
    target = ctrl.update(None, 1.0 / 60.0)
    assert target.linear_velocity == pytest.approx(1.0)
    assert target.angular_velocity == pytest.approx(0.0)


def test_backward():
    ctrl = make_controller()
    ctrl.set_input(FrameInput(backward=True))
    assert ctrl.update(None, 1.0 / 60.0).linear_velocity == pytest.approx(-1.0)


def test_turn_left_positive():
    """左转 -> 角速度为 +max（逆时针为正）。"""
    ctrl = make_controller()
    ctrl.set_input(FrameInput(left=True))
    target = ctrl.update(None, 1.0 / 60.0)
    assert target.linear_velocity == pytest.approx(0.0)
    assert target.angular_velocity == pytest.approx(2.0)


def test_turn_right_negative():
    ctrl = make_controller()
    ctrl.set_input(FrameInput(right=True))
    assert ctrl.update(None, 1.0 / 60.0).angular_velocity == pytest.approx(-2.0)


def test_wa_combo():
    """W + A -> 前进同时左转。"""
    ctrl = make_controller()
    ctrl.set_input(FrameInput(forward=True, left=True))
    target = ctrl.update(None, 1.0 / 60.0)
    assert target.linear_velocity == pytest.approx(1.0)
    assert target.angular_velocity == pytest.approx(2.0)


def test_stop_overrides():
    """空格停止优先于其他按键。"""
    ctrl = make_controller()
    ctrl.set_input(FrameInput(forward=True, left=True, stop=True))
    target = ctrl.update(None, 1.0 / 60.0)
    assert (target.linear_velocity, target.angular_velocity) == (0.0, 0.0)


def test_no_key_no_motion():
    ctrl = make_controller()
    target = ctrl.update(None, 1.0 / 60.0)
    assert (target.linear_velocity, target.angular_velocity) == (0.0, 0.0)


def test_base_controller_not_implemented():
    with pytest.raises(NotImplementedError):
        BaseController().update(None, 0.01)
