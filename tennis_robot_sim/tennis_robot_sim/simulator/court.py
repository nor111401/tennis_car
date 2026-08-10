"""二维矩形网球场。"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Court:
    """二维网球场，长度单位统一为米。

    - width_m : 场地长度（x 方向）
    - height_m: 场地宽度（y 方向）
    """

    width_m: float
    height_m: float

    def __init__(self, width_m: float, height_m: float) -> None:
        if width_m <= 0 or height_m <= 0:
            raise ValueError("场地长宽必须大于零")
        object.__setattr__(self, "width_m", width_m)
        object.__setattr__(self, "height_m", height_m)

    def in_bounds(self, x: float, y: float, margin: float = 0.0) -> bool:
        """判断点 (x, y) 是否在场地内（含可选内缩边距）。"""
        return (margin <= x <= self.width_m - margin
                and margin <= y <= self.height_m - margin)
