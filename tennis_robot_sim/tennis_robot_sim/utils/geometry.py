"""基础几何与数学工具。

全局约定：
- 长度统一使用米（m），角度统一使用弧度（rad）；
- 角度范围为 [-pi, pi)，theta 逆时针为正。
"""
from __future__ import annotations

import math

TWO_PI = 2.0 * math.pi


def clamp(value: float, low: float, high: float) -> float:
    """将 value 限制在 [low, high] 区间内。"""
    if high < low:
        raise ValueError(f"high({high}) 不能小于 low({low})")
    return max(low, min(high, value))


def normalize_angle(angle: float) -> float:
    """将任意角度归一化到 [-pi, pi)。

    示例：pi -> -pi；1.5*pi -> -pi/2；-1.5*pi -> pi/2。
    """
    angle = math.fmod(angle, TWO_PI)
    if angle >= math.pi:
        angle -= TWO_PI
    elif angle < -math.pi:
        angle += TWO_PI
    return angle


def angle_between(from_angle: float, to_angle: float) -> float:
    """返回从 from_angle 转到 to_angle 的最小有符号角度（弧度，[-pi, pi)）。"""
    return normalize_angle(to_angle - from_angle)


def deg_to_rad(deg: float) -> float:
    """角度转弧度。"""
    return math.radians(deg)


def rad_to_deg(rad: float) -> float:
    """弧度转角度。"""
    return math.degrees(rad)


def rotate_vector(x: float, y: float, angle: float) -> tuple[float, float]:
    """将向量 (x, y) 逆时针旋转 angle（弧度），返回 (x', y')。

    旋转矩阵：x' = x*cos - y*sin；y' = x*sin + y*cos。
    """
    c = math.cos(angle)
    s = math.sin(angle)
    return (x * c - y * s, x * s + y * c)
