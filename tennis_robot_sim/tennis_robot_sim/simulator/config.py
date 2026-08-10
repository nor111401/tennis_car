"""配置加载、解析与合法性校验。

配置来源为 config/default_config.json（或通过 load_config(path) 指定）。
所有配置在解析后进行合法性校验，失败抛出 ConfigError 并给出明确原因。
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    """配置加载或校验失败。"""


# ---------------------------------------------------------------------------
# 配置数据类（frozen，只读）
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SimulationConfig:
    """仿真时间推进配置。"""

    fixed_dt: float          # 固定仿真步长（秒）
    time_scale: float        # 时间倍速（1.0 为实时）


@dataclass(frozen=True)
class WindowConfig:
    """窗口配置。"""

    width: int               # 窗口宽度（px）
    height: int              # 窗口高度（px）
    fps: int                 # 目标帧率
    panel_width: int         # 右侧状态面板宽度（px）


@dataclass(frozen=True)
class CourtConfig:
    """二维网球场配置。"""

    width_m: float           # 场地长度（米，x 方向）
    height_m: float          # 场地宽度（米，y 方向）
    grid_step_m: float       # 背景网格间距（米）


@dataclass(frozen=True)
class RobotConfig:
    """差速小车参数。"""

    initial_x: float
    initial_y: float
    initial_theta_deg: float
    wheel_base: float        # 左右轮距（米）
    wheel_radius: float      # 车轮半径（米，预留：换算车轮角速度用）
    length: float            # 车体长（米，x 方向）
    width: float             # 车体宽（米，y 方向）
    max_linear_speed: float  # 最大线速度（m/s）
    max_angular_speed: float # 最大角速度（rad/s）

    @property
    def initial_theta_rad(self) -> float:
        return math.radians(self.initial_theta_deg)


@dataclass(frozen=True)
class CameraConfig:
    """虚拟摄像头配置（二维扇形视野）。"""

    field_of_view_deg: float      # 水平视场角（度）
    max_detection_distance: float # 最大检测距离（米）
    min_detection_distance: float # 最小检测距离（米）
    camera_offset_x: float        # 摄像头在车体系中的偏移 x（米，前向为正）
    camera_offset_y: float        # 摄像头在车体系中的偏移 y（米）

    @property
    def field_of_view_rad(self) -> float:
        return math.radians(self.field_of_view_deg)

    @property
    def half_fov_rad(self) -> float:
        return self.field_of_view_rad / 2.0


@dataclass(frozen=True)
class BallsConfig:
    """网球配置。"""

    count: int               # 网球数量
    radius_m: float          # 网球半径（米）
    random_seed: int         # 随机种子（保证可复现）
    spawn_margin_m: float    # 网球距场地边界的额外边距（米）


@dataclass(frozen=True)
class CollectionConfig:
    """简化收集判定配置。"""

    distance_m: float        # 收集半径（到小车中心的距离上限，米）
    angle_deg: float         # 收集锥角（度，完整锥角，小车前方对称 ±angle/2）
    auto_collect: bool       # 是否开启自动收集


@dataclass(frozen=True)
class LoggingConfig:
    """日志配置。"""

    dir: str                 # 日志目录
    console_level: str       # 控制台级别
    file_level: str          # 文件级别


@dataclass(frozen=True)
class SimConfig:
    """完整仿真配置。"""

    simulation: SimulationConfig
    window: WindowConfig
    court: CourtConfig
    robot: RobotConfig
    camera: CameraConfig
    balls: BallsConfig
    collection: CollectionConfig
    logging: LoggingConfig


DEFAULT_CONFIG_PATH = (Path(__file__).resolve().parents[1]
                       / "config" / "default_config.json")


# ---------------------------------------------------------------------------
# 加载与解析
# ---------------------------------------------------------------------------

def load_config(path: str | Path | None = None) -> SimConfig:
    """从 JSON 文件加载并校验配置。path 为 None 时使用默认配置文件。"""
    p = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    if not p.is_file():
        raise ConfigError(f"配置文件不存在: {p}")
    try:
        with open(p, encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"配置文件 JSON 解析失败: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"无法读取配置文件 {p}: {exc}") from exc
    return config_from_dict(data)


def config_from_dict(data: dict) -> SimConfig:
    """从字典构建配置对象并执行校验。"""
    if not isinstance(data, dict):
        raise ConfigError("配置根节点必须是 JSON 对象")

    sim = _section(data, "simulation")
    win = _section(data, "window")
    court = _section(data, "court")
    robot = _section(data, "robot")
    cam = _section(data, "camera")
    balls = _section(data, "balls")
    coll = _section(data, "collection")
    log = _section(data, "logging")

    cfg = SimConfig(
        simulation=SimulationConfig(
            fixed_dt=_number(sim, "fixed_dt", 1.0 / 60.0),
            time_scale=_number(sim, "time_scale", 1.0),
        ),
        window=WindowConfig(
            width=_int(win, "width"),
            height=_int(win, "height"),
            fps=_int(win, "fps", 60),
            panel_width=_int(win, "panel_width", 300),
        ),
        court=CourtConfig(
            width_m=_number(court, "width_m"),
            height_m=_number(court, "height_m"),
            grid_step_m=_number(court, "grid_step_m", 1.0),
        ),
        robot=RobotConfig(
            initial_x=_number(robot, "initial_x", 1.0),
            initial_y=_number(robot, "initial_y", 1.0),
            initial_theta_deg=_number(robot, "initial_theta_deg", 0.0),
            wheel_base=_number(robot, "wheel_base"),
            wheel_radius=_number(robot, "wheel_radius"),
            length=_number(robot, "length"),
            width=_number(robot, "width"),
            max_linear_speed=_number(robot, "max_linear_speed"),
            max_angular_speed=_number(robot, "max_angular_speed"),
        ),
        camera=CameraConfig(
            field_of_view_deg=_number(cam, "field_of_view_deg"),
            max_detection_distance=_number(cam, "max_detection_distance"),
            min_detection_distance=_number(cam, "min_detection_distance", 0.0),
            camera_offset_x=_number(cam, "camera_offset_x", 0.0),
            camera_offset_y=_number(cam, "camera_offset_y", 0.0),
        ),
        balls=BallsConfig(
            count=_int(balls, "count"),
            radius_m=_number(balls, "radius_m"),
            random_seed=_int(balls, "random_seed", 42),
            spawn_margin_m=_number(balls, "spawn_margin_m", 0.2),
        ),
        collection=CollectionConfig(
            distance_m=_number(coll, "distance_m"),
            angle_deg=_number(coll, "angle_deg"),
            auto_collect=_bool(coll, "auto_collect", False),
        ),
        logging=LoggingConfig(
            dir=_str(log, "dir", "logs"),
            console_level=_str(log, "console_level", "INFO"),
            file_level=_str(log, "file_level", "DEBUG"),
        ),
    )
    validate_config(cfg)
    return cfg


# ---------------------------------------------------------------------------
# 字段读取辅助
# ---------------------------------------------------------------------------

def _section(data: dict, name: str) -> dict:
    value = _get(data, name)
    if not isinstance(value, dict):
        raise ConfigError(f"配置段 {name!r} 必须是 JSON 对象")
    return value


def _get(data: dict, key: str) -> Any:
    if key not in data:
        raise ConfigError(f"配置缺少必需字段: {key!r}")
    return data[key]


def _number(section: dict, key: str, default: float | None = None) -> float:
    if key not in section:
        if default is not None:
            return float(default)
        raise ConfigError(f"配置缺少必需字段: {key!r}")
    value = section[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"字段 {key!r} 必须为数值，收到 {value!r}")
    return float(value)


def _int(section: dict, key: str, default: int | None = None) -> int:
    return int(_number(section, key, default))


def _bool(section: dict, key: str, default: bool = False) -> bool:
    if key not in section:
        return default
    value = section[key]
    if not isinstance(value, bool):
        raise ConfigError(f"字段 {key!r} 必须为布尔值，收到 {value!r}")
    return value


def _str(section: dict, key: str, default: str | None = None) -> str:
    if key not in section:
        if default is not None:
            return default
        raise ConfigError(f"配置缺少必需字段: {key!r}")
    value = section[key]
    if not isinstance(value, str):
        raise ConfigError(f"字段 {key!r} 必须为字符串，收到 {value!r}")
    return value


# ---------------------------------------------------------------------------
# 合法性校验
# ---------------------------------------------------------------------------

_VALID_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


def validate_config(cfg: SimConfig) -> None:
    """对配置进行基本合法性检查，失败抛出 ConfigError。"""
    errors: list[str] = []

    # 窗口
    if cfg.window.width <= 0 or cfg.window.height <= 0:
        errors.append("window.width / height 必须大于 0")
    if not (1 <= cfg.window.fps <= 240):
        errors.append("window.fps 应在 1~240 之间")
    if not (0 <= cfg.window.panel_width < cfg.window.width):
        errors.append("window.panel_width 应在 [0, window.width) 之间")

    # 场地
    if cfg.court.width_m <= 0 or cfg.court.height_m <= 0:
        errors.append("court.width_m / height_m 必须大于 0")
    if cfg.court.grid_step_m <= 0:
        errors.append("court.grid_step_m 必须大于 0")

    # 小车
    if cfg.robot.wheel_base <= 0:
        errors.append("robot.wheel_base 必须大于 0")
    if cfg.robot.wheel_radius <= 0:
        errors.append("robot.wheel_radius 必须大于 0")
    if cfg.robot.length <= 0 or cfg.robot.width <= 0:
        errors.append("robot.length / width 必须大于 0")
    if cfg.robot.max_linear_speed < 0:
        errors.append("robot.max_linear_speed 不能为负")
    if cfg.robot.max_angular_speed < 0:
        errors.append("robot.max_angular_speed 不能为负")
    if not (0 <= cfg.robot.initial_x <= cfg.court.width_m):
        errors.append(f"robot.initial_x({cfg.robot.initial_x}) 超出场地范围")
    if not (0 <= cfg.robot.initial_y <= cfg.court.height_m):
        errors.append(f"robot.initial_y({cfg.robot.initial_y}) 超出场地范围")

    # 摄像头
    if not (0 < cfg.camera.field_of_view_deg < 180):
        errors.append("camera.field_of_view_deg 应在 (0, 180) 之间")
    if cfg.camera.max_detection_distance <= 0:
        errors.append("camera.max_detection_distance 必须大于 0")
    if cfg.camera.min_detection_distance < 0:
        errors.append("camera.min_detection_distance 不能为负")
    if cfg.camera.max_detection_distance <= cfg.camera.min_detection_distance:
        errors.append("camera.max_detection_distance 必须大于 "
                      "camera.min_detection_distance")

    # 网球
    if cfg.balls.count < 0:
        errors.append("balls.count 不能为负")
    if cfg.balls.radius_m <= 0:
        errors.append("balls.radius_m 必须大于 0")
    if cfg.balls.spawn_margin_m < 0:
        errors.append("balls.spawn_margin_m 不能为负")

    # 收集
    if cfg.collection.distance_m <= 0:
        errors.append("collection.distance_m 必须大于 0")
    if not (0 < cfg.collection.angle_deg <= 180):
        errors.append("collection.angle_deg 应在 (0, 180] 之间")

    # 仿真
    if cfg.simulation.fixed_dt <= 0:
        errors.append("simulation.fixed_dt 必须大于 0")
    if cfg.simulation.time_scale <= 0:
        errors.append("simulation.time_scale 必须大于 0")

    # 日志级别
    for label, level in (("logging.console_level", cfg.logging.console_level),
                         ("logging.file_level", cfg.logging.file_level)):
        if str(level).upper() not in _VALID_LEVELS:
            errors.append(f"{label} 非法: {level!r}")

    if errors:
        raise ConfigError("配置校验失败：\n  - " + "\n  - ".join(errors))
