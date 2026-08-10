"""键盘输入：将 pygame 事件转换为逻辑控制输入。"""
from __future__ import annotations

import pygame

from simulator.controller import FrameInput
from utils.logger import get_logger

# SDL2 物理扫描码（QWERTY 布局，与系统键盘布局无关）。
# 用于 pygame.key.get_pressed() 兜底路径 —— 注意：get_pressed() 返回的
# 是**按扫描码索引**的长度 512 数组，而 K_w=119 这类常量是按键码，
# 两者不直接对应（K_w 的物理扫描码是 26），不能直接 keys[pygame.K_w]。
_SCANCODES = {
    pygame.K_w: 26,
    pygame.K_a: 4,
    pygame.K_s: 22,
    pygame.K_d: 7,
    pygame.K_SPACE: 44,
}

# 输入焦点丢失事件类型（兼容不同 pygame 版本）
_FOCUS_LOST_EVENTS = [pygame.ACTIVEEVENT]
if hasattr(pygame, "WINDOWFOCUSLOST"):
    _FOCUS_LOST_EVENTS.append(pygame.WINDOWFOCUSLOST)

_APP_INPUT_FOCUS = getattr(pygame, "APPINPUTFOCUS", 1)


class InputHandler:
    """收集持续按键与单次动作按键。

    **为什么用事件追踪而不是 pygame.key.get_pressed()：**
    `pygame.key.get_pressed()` 返回**按物理扫描码索引**的数组，而
    `pygame.K_w` 这类常量是**按键码**（W 按键码 119 ≠ 物理扫描码 26）。
    直接用 `keys[pygame.K_w]` 会读到错误的键，导致 WASD 失效。
    因此本类以 KEYDOWN/KEYUP 事件追踪为主，另以 get_pressed(扫描码) 兜底。

    约定：
    - 持续按键（W/A/S/D/空格）由 KEYDOWN/KEYUP 更新，支持多键同时按下；
    - 单次动作按键（R/B/C/P/V/G/T/ESC/F1）在 KEYDOWN 时触发一次；
    - 仅在**输入焦点**丢失时清空按键（鼠标离开窗口不触发清空）。
    """

    # 单次动作按键 -> 动作名
    KEY_ACTIONS = {
        pygame.K_r: "reset",           # 重置小车和网球
        pygame.K_b: "respawn",         # 重新随机生成网球
        pygame.K_c: "collect",         # 手动收集满足条件的网球
        pygame.K_p: "toggle_pause",    # 暂停/继续
        pygame.K_v: "toggle_fov",      # 显示/隐藏摄像头视野
        pygame.K_g: "toggle_grid",     # 显示/隐藏网格
        pygame.K_t: "cycle_target",    # 切换选中的测试目标
        pygame.K_F1: "toggle_demo",    # 演示模式（自动绕圈，用于诊断）
        pygame.K_ESCAPE: "quit",       # 退出
        pygame.K_q: "quit",
    }

    def __init__(self, logger=None) -> None:
        # 当前按下的按键码集合（由 KEYDOWN/KEYUP 维护）
        self._pressed: set[int] = set()
        # 收到 KEYDOWN 的总次数（用于诊断：0 表示从未收到按键事件）
        self._keydown_count: int = 0
        self.logger = logger or get_logger()

    # -- 对外接口 ----------------------------------------------------------

    def get_frame_input(self) -> FrameInput:
        """读取当前持续按键状态（多键组合支持）。"""
        return FrameInput(
            forward=self._key_state(pygame.K_w),
            backward=self._key_state(pygame.K_s),
            left=self._key_state(pygame.K_a),
            right=self._key_state(pygame.K_d),
            stop=self._key_state(pygame.K_SPACE),
        )

    def process_events(self, events: list[pygame.event.Event]) -> list[str]:
        """处理事件队列，返回本帧触发的动作名列表，并维护持续按键。"""
        actions: list[str] = []
        for event in events:
            if event.type == pygame.QUIT:
                actions.append("quit")
            elif event.type == pygame.KEYDOWN:
                self._pressed.add(event.key)
                self._keydown_count += 1
                self.logger.debug("KEYDOWN: %s", pygame.key.name(event.key))
                action = self.KEY_ACTIONS.get(event.key)
                if action is not None:
                    actions.append(action)
            elif event.type == pygame.KEYUP:
                self._pressed.discard(event.key)
                self.logger.debug("KEYUP: %s", pygame.key.name(event.key))
            elif event.type in _FOCUS_LOST_EVENTS:
                self._handle_focus_lost(event)
        return actions

    def keydown_count(self) -> int:
        """已收到的按键事件总数（用于诊断输入是否送达）。"""
        return self._keydown_count

    def is_focused(self) -> bool:
        """窗口当前是否拥有键盘焦点。"""
        try:
            return bool(pygame.key.get_focused())
        except Exception:
            return False

    # -- 内部 -------------------------------------------------------------

    def _key_state(self, key: int) -> bool:
        """判断某个键当前是否按下。

        路径一：事件追踪（KEYDOWN/KEYUP 维护的集合）；
        路径二：get_pressed() 按物理扫描码索引（事件丢失时的兜底）。
        """
        if key in self._pressed:
            return True
        scancode = _SCANCODES.get(key)
        if scancode is None:
            return False
        try:
            return bool(pygame.key.get_pressed()[scancode])
        except Exception:
            return False

    def _handle_focus_lost(self, event) -> None:
        """输入焦点丢失时清空按键集合，避免“卡键”。"""
        if event.type == pygame.ACTIVEEVENT:
            # ACTIVEEVENT 也用于鼠标进出窗口；仅当输入焦点变化且丢失时清空
            if event.gain == 0 and (event.state & _APP_INPUT_FOCUS):
                self._pressed.clear()
        else:  # WINDOWFOCUSLOST
            self._pressed.clear()
