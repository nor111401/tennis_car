"""中文字体加载。

pygame 的默认内置字体（Font(None, size)）只包含少量 ASCII 字形，
不含中文字符，导致界面中文显示为“方框/占位符”。
本模块优先从系统加载支持 CJK 的字体（微软雅黑/黑体等），
保证 Windows 上中文正常显示。
"""
from __future__ import annotations

import os

import pygame

# Windows 常用中文字体文件（按优先级排列）
_CJK_FONT_FILES = [
    r"C:\Windows\Fonts\msyh.ttc",    # 微软雅黑
    r"C:\Windows\Fonts\msyhbd.ttc",  # 微软雅黑（粗体）
    r"C:\Windows\Fonts\simhei.ttf",  # 黑体
    r"C:\Windows\Fonts\simsun.ttc",  # 宋体
    r"C:\Windows\Fonts\deng.ttf",    # 等线
    r"C:\Windows\Fonts\kaiu.ttf",    # 楷体
]

# 非 Windows 平台常见中文字体名（通过 pygame.font.match_font 查找）
_NON_WINDOWS_CANDIDATES = [
    "notosanscjksc",
    "notosanscjk",
    "wqymicrohei",
    "wqyzenhei",
    "wenquanyimicrohei",
    "pingfangsc",
]


def find_cjk_font_path() -> str | None:
    """返回一个可用的中文字体文件路径；找不到返回 None。"""
    for path in _CJK_FONT_FILES:
        if os.path.isfile(path):
            return path
    for name in _NON_WINDOWS_CANDIDATES:
        path = pygame.font.match_font(name)
        if path:
            return path
    return None


def create_font(size: int) -> pygame.font.Font:
    """创建支持中文的字体对象；找不到中文字体时回退到 pygame 默认字体。

    调用前提：pygame 已完成初始化（pygame.init() 或 pygame.font.init()）。
    """
    path = find_cjk_font_path()
    if path is not None:
        return pygame.font.Font(path, size)
    return pygame.font.Font(None, size)
