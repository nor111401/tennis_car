"""中文字体加载测试（pygame 默认字体不含 CJK 字形）。"""
from __future__ import annotations

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame
import pytest

from ui.fonts import create_font, find_cjk_font_path


@pytest.fixture(scope="module", autouse=True)
def pygame_env():
    pygame.init()
    pygame.display.set_mode((1, 1))
    yield
    pygame.quit()


def test_find_cjk_font():
    """能找到中文字体文件（找不到则跳过）。"""
    path = find_cjk_font_path()
    if path is None:
        pytest.skip("系统没有可用中文字体，无法验证")
    assert path.lower().endswith((".ttf", ".ttc"))
    assert os.path.isfile(path)


def test_cjk_font_has_chinese_glyphs():
    """加载的字体必须包含中文字形（metrics 不为 None）。"""
    if find_cjk_font_path() is None:
        pytest.skip("系统没有可用中文字体，无法验证")
    font = create_font(24)
    rects = font.metrics("网球收集仿真")
    assert rects is not None
    assert all(r is not None for r in rects)
