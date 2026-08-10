"""配置加载与合法性校验测试。"""
from __future__ import annotations

import json

import pytest

from simulator.config import (
    DEFAULT_CONFIG_PATH,
    ConfigError,
    config_from_dict,
    load_config,
)


def test_default_config_loads():
    """默认配置可正常加载且关键值正确。"""
    cfg = load_config()
    assert cfg.court.width_m == pytest.approx(10.0)
    assert cfg.court.height_m == pytest.approx(6.0)
    assert cfg.balls.count == 10
    assert cfg.camera.half_fov_rad == pytest.approx(0.6108652381980153)


def test_missing_file_raises():
    """配置文件缺失 -> 明确报错。"""
    with pytest.raises(ConfigError, match="不存在"):
        load_config("no_such_config.json")


def _base_dict() -> dict:
    with open(DEFAULT_CONFIG_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def test_invalid_court_width():
    data = _base_dict()
    data["court"]["width_m"] = 0.0
    with pytest.raises(ConfigError, match="width_m"):
        config_from_dict(data)


def test_invalid_fov():
    data = _base_dict()
    data["camera"]["field_of_view_deg"] = 200.0
    with pytest.raises(ConfigError, match="field_of_view_deg"):
        config_from_dict(data)


def test_invalid_detection_range():
    """最大检测距离必须大于最小检测距离。"""
    data = _base_dict()
    data["camera"]["min_detection_distance"] = 5.0  # 大于 max 4.0
    with pytest.raises(ConfigError, match="max_detection_distance"):
        config_from_dict(data)


def test_robot_outside_court():
    data = _base_dict()
    data["robot"]["initial_x"] = 20.0
    with pytest.raises(ConfigError, match="initial_x"):
        config_from_dict(data)


def test_negative_ball_count():
    data = _base_dict()
    data["balls"]["count"] = -1
    with pytest.raises(ConfigError, match="balls.count"):
        config_from_dict(data)


def test_missing_section():
    data = _base_dict()
    del data["court"]
    with pytest.raises(ConfigError, match="court"):
        config_from_dict(data)


def test_invalid_log_level():
    data = _base_dict()
    data["logging"]["console_level"] = "VERBOSE"
    with pytest.raises(ConfigError, match="console_level"):
        config_from_dict(data)
