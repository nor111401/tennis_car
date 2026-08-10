"""右侧实时状态面板绘制。"""
from __future__ import annotations

import pygame

from utils.geometry import rad_to_deg


def _format_keys(frame_input) -> str:
    """把当前按键状态格式化为紧凑文本，如 'W S a D ·SP'。

    大写 = 按下，小写 = 未按。
    """
    if frame_input is None:
        return "-"
    parts = [
        "W" if frame_input.forward else "w",
        "A" if frame_input.left else "a",
        "S" if frame_input.backward else "s",
        "D" if frame_input.right else "d",
        "SP" if frame_input.stop else "·",
    ]
    return " ".join(parts)


class StatusPanel:
    """在窗口右侧绘制实时状态信息。"""

    BG_COLOR = (28, 32, 40)
    BORDER_COLOR = (66, 74, 88)
    TITLE_COLOR = (235, 235, 235)
    LABEL_COLOR = (168, 178, 190)
    VALUE_COLOR = (240, 240, 240)
    ACCENT_COLOR = (120, 220, 120)

    def __init__(self, width_px: int, window_height_px: int,
                 title_font: pygame.font.Font,
                 text_font: pygame.font.Font) -> None:
        self.width_px = width_px
        self.height_px = window_height_px
        self.title_font = title_font
        self.text_font = text_font

    def draw(self, surface: pygame.Surface, world, simulation,
             frame_input=None, keydown_count: int = 0,
             focused: bool = True, demo_mode: bool = False) -> None:
        """绘制状态面板。world / simulation 为仿真对象（仅读取）。

        frame_input / keydown_count / focused 为输入诊断信息，
        用于在界面上直观确认键盘事件是否送达、窗口是否聚焦。
        """
        panel_rect = pygame.Rect(surface.get_width() - self.width_px, 0,
                                 self.width_px, self.height_px)
        pygame.draw.rect(surface, self.BG_COLOR, panel_rect)
        pygame.draw.line(surface, self.BORDER_COLOR,
                         (panel_rect.left, 0), (panel_rect.left,
                                                self.height_px), 1)

        y = 14
        y = self._title(surface, panel_rect, y)
        y = self._divider(surface, panel_rect, y)
        y += 6

        stats = world.stats()
        robot = world.robot.get_state()
        rows: list[tuple[str, str]] = [
            ("仿真时间", f"{simulation.time:.2f} s"),
            ("状态", "暂停" if simulation.paused else "运行"),
            ("---", ""),
            ("网球总数", str(stats["total_balls"])),
            ("当前可见", str(stats["visible_balls"])),
            ("历史已发现", str(stats["discovered_balls"])),
            ("已收集", str(stats["collected_balls"])),
            ("选中目标", "无" if world.selected_ball_id is None
             else f"网球 #{world.selected_ball_id}"),
            ("---", ""),
            ("小车 x", f"{robot.x:.2f} m"),
            ("小车 y", f"{robot.y:.2f} m"),
            ("朝向 θ", f"{rad_to_deg(robot.theta):7.1f}°"),
            ("线速度 v", f"{robot.linear_velocity:+.2f} m/s"),
            ("角速度 ω", f"{robot.angular_velocity:+.2f} rad/s"),
            ("左轮 vL", f"{robot.left_wheel_speed:+.2f} m/s"),
            ("右轮 vR", f"{robot.right_wheel_speed:+.2f} m/s"),
            ("---", ""),
            ("窗口焦点", "有" if focused else "无"),
            ("键盘事件", f"{keydown_count} 次"),
            ("按键", _format_keys(frame_input)),
        ]
        if demo_mode:
            rows.append(("演示模式", "开启(F1)"))
        for label, value in rows:
            if label == "---":
                y = self._divider(surface, panel_rect, y)
                y += 4
                continue
            y = self._row(surface, panel_rect, y, label, value)

        # 输入诊断提示：从未收到键盘事件，或窗口未聚焦
        if keydown_count == 0:
            self._accent(surface, panel_rect, "未收到键盘事件：请点击本窗口后操作",
                         color=(255, 120, 80))
        elif not focused:
            self._accent(surface, panel_rect, "窗口未聚焦：请点击本窗口",
                         color=(255, 180, 60))
        elif simulation.paused:
            self._accent(surface, panel_rect, "PAUSED")

    # -- 内部绘制辅助 -------------------------------------------------------

    def _title(self, surface, rect, y) -> int:
        surf = self.title_font.render("状态面板 / Status", True,
                                      self.TITLE_COLOR)
        surface.blit(surf, (rect.left + 12, y))
        return y + surf.get_height() + 6

    def _divider(self, surface, rect, y) -> int:
        pygame.draw.line(surface, self.BORDER_COLOR,
                         (rect.left + 8, y), (rect.right - 8, y), 1)
        return y + 1

    def _row(self, surface, rect, y, label, value) -> int:
        label_surf = self.text_font.render(label, True, self.LABEL_COLOR)
        value_surf = self.text_font.render(value, True, self.VALUE_COLOR)
        surface.blit(label_surf, (rect.left + 12, y))
        surface.blit(value_surf, (rect.right - 12 - value_surf.get_width(), y))
        return y + max(label_surf.get_height(), value_surf.get_height()) + 5

    def _accent(self, surface, rect, text, color=None) -> None:
        color = color or self.ACCENT_COLOR
        surf = self.title_font.render(text, True, color)
        surface.blit(surf, (rect.left + 12, self.height_px - 32))
