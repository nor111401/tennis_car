"""世界坐标 <-> 屏幕坐标转换单元测试。"""
from __future__ import annotations

import pytest

from utils.coordinate_transform import CoordinateTransformer


def make_transformer() -> CoordinateTransformer:
    return CoordinateTransformer(10.0, 6.0, 1000, 800, margin_px=20)


def test_center_maps_to_canvas_center():
    """场地中心映射到画布中心。"""
    t = make_transformer()
    sx, sy = t.world_to_screen(5.0, 3.0)
    assert sx == pytest.approx(500.0, abs=1.0)
    assert sy == pytest.approx(400.0, abs=1.0)


def test_corners_inside_canvas():
    """场地四角映射后仍在画布内。"""
    t = make_transformer()
    for x in (0.0, 10.0):
        for y in (0.0, 6.0):
            sx, sy = t.world_to_screen(x, y)
            assert 0 <= sx <= 1000
            assert 0 <= sy <= 800


def test_corner_order():
    """屏幕 y 向下：底部世界坐标映射到更大的屏幕 y。"""
    t = make_transformer()
    bottom_left = t.world_to_screen(0.0, 0.0)
    top_left = t.world_to_screen(0.0, 6.0)
    bottom_right = t.world_to_screen(10.0, 0.0)
    assert bottom_left[1] > top_left[1]   # 底部在下方
    assert bottom_right[0] > bottom_left[0]  # x 向右增大


def test_round_trip():
    """世界 -> 屏幕 -> 世界 应还原。"""
    t = make_transformer()
    for x, y in [(0.5, 0.5), (5.0, 3.0), (9.7, 5.8), (0.0, 0.0), (10.0, 6.0)]:
        sx, sy = t.world_to_screen(x, y)
        wx, wy = t.screen_to_world(sx, sy)
        assert wx == pytest.approx(x, abs=1e-6)
        assert wy == pytest.approx(y, abs=1e-6)


def test_court_rect_size():
    """场地矩形尺寸等于 场地边长 * 比例。"""
    t = make_transformer()
    rect = t.court_rect_px()
    assert rect.width == pytest.approx(10.0 * t.scale_px_per_m)
    assert rect.height == pytest.approx(6.0 * t.scale_px_per_m)


def test_invalid_court_raises():
    """非法场地尺寸应报错。"""
    with pytest.raises(ValueError):
        CoordinateTransformer(0.0, 6.0, 1000, 800, margin_px=20)
