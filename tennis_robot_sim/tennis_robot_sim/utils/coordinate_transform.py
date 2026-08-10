"""世界坐标（米）与屏幕像素坐标（px）之间的转换。

坐标约定：
- 世界系：原点在场地左下角，x 向右，y 向上（标准数学坐标系）；
- 屏幕系：原点在窗口左上角，x 向右，y 向下（Pygame 约定）。

本模块不依赖 pygame，只返回数值/元组。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RectPx:
    """屏幕上的矩形区域（左上角 x/y、宽、高），单位 px。"""

    x: float
    y: float
    width: float
    height: float

    def as_pygame_rect(self):
        """转换为 pygame.Rect（仅 UI 层调用）。"""
        import pygame  # 延迟导入，保持本模块可无 pygame 测试

        return pygame.Rect(int(self.x), int(self.y),
                           int(self.width), int(self.height))


class CoordinateTransformer:
    """世界坐标与屏幕坐标互转，保持场地纵横比并居中显示。

    换算关系：
        scale = min((画布宽 - 2*margin) / 场地宽, (画布高 - 2*margin) / 场地高)
        screen_x = offset_x + world_x * scale
        screen_y = offset_y + (court_height - world_y) * scale   # y 轴翻转
    """

    def __init__(self, court_width_m: float, court_height_m: float,
                 canvas_width_px: float, canvas_height_px: float,
                 margin_px: float = 20.0) -> None:
        if court_width_m <= 0 or court_height_m <= 0:
            raise ValueError("场地长宽必须大于零")
        if canvas_width_px <= 0 or canvas_height_px <= 0:
            raise ValueError("画布尺寸必须大于零")
        if margin_px < 0:
            raise ValueError("边距不能为负")

        self.court_width_m = court_width_m
        self.court_height_m = court_height_m
        self.canvas_width_px = canvas_width_px
        self.canvas_height_px = canvas_height_px
        self.margin_px = margin_px

        avail_w = canvas_width_px - 2.0 * margin_px
        avail_h = canvas_height_px - 2.0 * margin_px
        # 在保持纵横比的前提下取可用空间内能容纳的最大比例
        self.scale_px_per_m = min(avail_w / court_width_m,
                                  avail_h / court_height_m)
        drawn_w = self.scale_px_per_m * court_width_m
        drawn_h = self.scale_px_per_m * court_height_m
        # 居中偏移
        self.offset_x_px = margin_px + (avail_w - drawn_w) / 2.0
        self.offset_y_px = margin_px + (avail_h - drawn_h) / 2.0

    def world_to_screen(self, x_m: float, y_m: float) -> tuple[float, float]:
        """世界坐标 -> 屏幕坐标，返回 (sx, sy)。"""
        sx = self.offset_x_px + x_m * self.scale_px_per_m
        sy = self.offset_y_px + (self.court_height_m - y_m) * self.scale_px_per_m
        return sx, sy

    def screen_to_world(self, sx_px: float, sy_px: float) -> tuple[float, float]:
        """屏幕坐标 -> 世界坐标，返回 (x, y)。"""
        x_m = (sx_px - self.offset_x_px) / self.scale_px_per_m
        y_m = self.court_height_m - (sy_px - self.offset_y_px) / self.scale_px_per_m
        return x_m, y_m

    def court_rect_px(self) -> RectPx:
        """场地在屏幕上对应的矩形区域（px）。"""
        return RectPx(
            x=self.offset_x_px,
            y=self.offset_y_px,
            width=self.court_width_m * self.scale_px_per_m,
            height=self.court_height_m * self.scale_px_per_m,
        )
