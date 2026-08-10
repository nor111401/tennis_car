"""摄像头视野判断单元测试。

覆盖：正前方可见 / 视场角外不可见 / 最大最小距离限制 /
旋转后视野变化 / 边界角度稳定性 / bearing 正负号约定 / 摄像头偏移。
"""
from __future__ import annotations

import dataclasses
import math

import pytest

from simulator.camera import Camera
from simulator.config import CameraConfig
from simulator.types import Pose


def make_camera(**overrides) -> Camera:
    base = CameraConfig(
        field_of_view_deg=70.0, max_detection_distance=4.0,
        min_detection_distance=0.1, camera_offset_x=0.0, camera_offset_y=0.0,
    )
    return Camera(dataclasses.replace(base, **overrides))


def robot_pose(x: float = 5.0, y: float = 3.0, theta: float = 0.0) -> Pose:
    return Pose(x=x, y=y, theta=theta)


class _Ball:
    """测试用网球桩（仅暴露 id / 位置 / 活动状态）。"""

    def __init__(self, ball_id: int, x: float, y: float) -> None:
        self.id = ball_id
        self.x = x
        self.y = y

    def is_active(self) -> bool:
        return True


def test_ball_ahead_visible():
    """正前方且距离合适 -> 可见。"""
    cam = make_camera()
    balls = [_Ball(1, 7.0, 3.0)]  # 距机器人 2.0 m，正前方
    visible = cam.get_visible_balls(robot_pose(), balls)
    assert [d.ball_id for d in visible] == [1]
    assert visible[0].distance == pytest.approx(2.0)
    assert visible[0].bearing == pytest.approx(0.0)


def test_ball_outside_fov_not_visible():
    """视场角外（45° > 35° 半角）-> 不可见。"""
    cam = make_camera()  # 半视场角 35°
    balls = [_Ball(1, 6.0, 4.0)]
    assert cam.get_visible_balls(robot_pose(), balls) == []


def test_ball_beyond_max_distance():
    """超出最大检测距离 -> 不可见。"""
    cam = make_camera(max_detection_distance=4.0)
    balls = [_Ball(1, 5.0, 8.0)]  # 距离 5.0 > 4.0
    assert cam.get_visible_balls(robot_pose(), balls) == []


def test_ball_within_min_distance():
    """小于最小检测距离 -> 不可见。"""
    cam = make_camera(min_detection_distance=0.1)
    balls = [_Ball(1, 5.0, 3.02)]  # 距离 0.02 < 0.1
    assert cam.get_visible_balls(robot_pose(), balls) == []


def test_rotation_changes_fov():
    """小车旋转后视野正确变化。"""
    cam = make_camera()
    balls = [_Ball(1, 6.0, 3.0),   # 朝 +x 时正右方（可见）
             _Ball(2, 5.0, 6.0)]   # 朝 +y 时正前方（可见）
    vis0 = {d.ball_id for d in cam.get_visible_balls(robot_pose(theta=0.0), balls)}
    assert vis0 == {1}
    vis90 = {d.ball_id for d in cam.get_visible_balls(
        robot_pose(theta=math.pi / 2.0), balls)}
    assert vis90 == {2}


def test_boundary_angle_stability():
    """恰好处于边界角上 -> 可见（含边界）；略超边界 -> 不可见。"""
    cam = make_camera(field_of_view_deg=70.0)  # 半角 35°
    half = math.radians(35.0)
    on_boundary = _Ball(1, 5.0 + 2.0 * math.cos(half),
                        3.0 + 2.0 * math.sin(half))
    visible = cam.get_visible_balls(robot_pose(), [on_boundary])
    assert [d.ball_id for d in visible] == [1]

    just_out = _Ball(2, 5.0 + 2.0 * math.cos(half + 0.02),
                     3.0 + 2.0 * math.sin(half + 0.02))
    assert cam.get_visible_balls(robot_pose(), [just_out]) == []


def test_bearing_sign_convention():
    """bearing 正负号：左侧为正，右侧为负。"""
    cam = make_camera()
    ang = math.radians(30.0)
    left = _Ball(1, 5.0 + 2.0 * math.cos(ang), 3.0 + 2.0 * math.sin(ang))
    right = _Ball(2, 5.0 + 2.0 * math.cos(ang), 3.0 - 2.0 * math.sin(ang))
    detections = cam.get_visible_balls(robot_pose(), [left, right])
    by_id = {d.ball_id: d for d in detections}
    assert by_id[1].bearing > 0
    assert by_id[2].bearing < 0


def test_bearing_behind_is_not_visible():
    """目标在正后方（bearing 约 ±pi）-> 不可见。"""
    cam = make_camera()
    balls = [_Ball(1, 3.0, 3.0)]
    assert cam.get_visible_balls(robot_pose(), balls) == []


def test_camera_offset_uses_camera_position():
    """摄像头带偏移时，距离以摄像头位置为基准。"""
    cam = make_camera(camera_offset_x=0.2)
    ball = _Ball(1, 5.4, 3.0)  # 距机器人中心 0.4，距摄像头 0.2
    detections = cam.get_visible_balls(robot_pose(), [ball])
    assert len(detections) == 1
    assert detections[0].distance == pytest.approx(0.2)


def test_detect_interface_alias():
    """预留接口 detect() 与 get_visible_balls() 行为一致。"""
    cam = make_camera()
    balls = [_Ball(1, 7.0, 3.0)]
    assert len(cam.detect(robot_pose(), balls)) == 1


def test_collected_ball_not_detected():
    """已收集网球不参与检测。"""

    class _Collected(_Ball):
        def is_active(self) -> bool:
            return False

    cam = make_camera()
    balls = [_Collected(1, 7.0, 3.0)]
    assert cam.get_visible_balls(robot_pose(), balls) == []
