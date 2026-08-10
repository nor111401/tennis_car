"""键盘输入处理测试（基于合成事件的逻辑验证，不依赖真实键盘）。

说明：`pygame.key.get_pressed()` 返回按扫描码索引的数组，与 K_* 按键码
不对应，因此 InputHandler 改为事件追踪。这里用合成 KEYDOWN/KEYUP 事件
验证其正确性。
"""
from __future__ import annotations

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")  # 无头模式，避免弹出窗口

import pygame
import pytest

from ui.input_handler import InputHandler


@pytest.fixture(scope="module", autouse=True)
def pygame_env():
    pygame.init()
    pygame.display.set_mode((1, 1))
    yield
    pygame.quit()


def test_wasd_continuous_keys():
    """W+A 同时按下 -> forward 与 left 均为 True；松开 W 后 forward 为 False。"""
    handler = InputHandler()
    events = [
        pygame.event.Event(pygame.KEYDOWN, key=pygame.K_w),
        pygame.event.Event(pygame.KEYDOWN, key=pygame.K_a),
    ]
    assert handler.process_events(events) == []
    inp = handler.get_frame_input()
    assert inp.forward is True
    assert inp.left is True
    assert inp.backward is False
    assert inp.right is False

    handler.process_events([pygame.event.Event(pygame.KEYUP, key=pygame.K_w)])
    inp = handler.get_frame_input()
    assert inp.forward is False
    assert inp.left is True


def test_space_stop():
    """空格 -> stop 为 True。"""
    handler = InputHandler()
    handler.process_events(
        [pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE)]
    )
    assert handler.get_frame_input().stop is True
    handler.process_events(
        [pygame.event.Event(pygame.KEYUP, key=pygame.K_SPACE)]
    )
    assert handler.get_frame_input().stop is False


def test_one_shot_actions():
    """R/P/T 在 KEYDOWN 时各触发一次对应动作。"""
    handler = InputHandler()
    events = [
        pygame.event.Event(pygame.KEYDOWN, key=pygame.K_r),
        pygame.event.Event(pygame.KEYDOWN, key=pygame.K_p),
        pygame.event.Event(pygame.KEYDOWN, key=pygame.K_t),
    ]
    actions = handler.process_events(events)
    assert actions == ["reset", "toggle_pause", "cycle_target"]


def test_quit_event():
    """QUIT 事件 -> quit 动作。"""
    handler = InputHandler()
    assert handler.process_events([pygame.event.Event(pygame.QUIT)]) == ["quit"]


def test_focus_loss_clears_keys():
    """窗口失焦（WINDOWFOCUSLOST）清空按键，避免卡键。"""
    handler = InputHandler()
    handler.process_events(
        [pygame.event.Event(pygame.KEYDOWN, key=pygame.K_w)]
    )
    assert handler.get_frame_input().forward is True
    handler.process_events([pygame.event.Event(pygame.WINDOWFOCUSLOST)])
    assert handler.get_frame_input().forward is False


def test_input_focus_loss_clears_keys():
    """ACTIVEEVENT 输入焦点丢失 -> 清空按键。"""
    handler = InputHandler()
    handler.process_events(
        [pygame.event.Event(pygame.KEYDOWN, key=pygame.K_w)]
    )
    handler.process_events([
        pygame.event.Event(pygame.ACTIVEEVENT, gain=0,
                           state=pygame.APPINPUTFOCUS)
    ])
    assert handler.get_frame_input().forward is False


def test_mouse_leave_does_not_clear_keys():
    """鼠标离开窗口（MOUSEFOCUS）不应清空按键。"""
    handler = InputHandler()
    handler.process_events(
        [pygame.event.Event(pygame.KEYDOWN, key=pygame.K_w)]
    )
    handler.process_events([
        pygame.event.Event(pygame.ACTIVEEVENT, gain=0,
                           state=pygame.APPMOUSEFOCUS)
    ])
    assert handler.get_frame_input().forward is True


def test_keydown_counter():
    """keydown_count 统计收到的按键事件数。"""
    handler = InputHandler()
    assert handler.keydown_count() == 0
    handler.process_events([
        pygame.event.Event(pygame.KEYDOWN, key=pygame.K_w),
        pygame.event.Event(pygame.KEYDOWN, key=pygame.K_a),
    ])
    assert handler.keydown_count() == 2
