"""控制器抽象与键盘控制器。

控制器统一接口：
    update(observation: Observation, dt: float) -> TargetVelocity

后续可直接新增：
    TargetFollowingController / PathPlanningController /
    RealMotorController 等派生类（本阶段不实现）。
"""
from __future__ import annotations

from .types import FrameInput, Observation, TargetVelocity


class BaseController:
    """控制器基类：输入观测，输出目标速度。"""

    def update(self, observation: Observation, dt: float) -> TargetVelocity:
        raise NotImplementedError


class KeyboardController(BaseController):
    """键盘控制器：把逻辑按键（FrameInput）映射为线速度/角速度目标。

    约定：
    - forward/backward 控制线速度，left/right 控制角速度；
    - 角速度方向：left 为左转 = 正（逆时针），与 theta 约定一致；
    - 输出速度会被 Robot.set_velocity 再做限幅（二次保险）；
    - 同时按住 W + A 即为前进同时左转（多键组合）。
    """

    def __init__(self, max_linear_speed: float, max_angular_speed: float) -> None:
        self.max_linear_speed = max_linear_speed
        self.max_angular_speed = max_angular_speed
        self._input = FrameInput()

    def set_input(self, frame_input: FrameInput) -> None:
        """由 UI 层注入当前帧的逻辑按键状态。"""
        self._input = frame_input

    def update(self, observation: Observation, dt: float) -> TargetVelocity:
        inp = self._input
        if inp.stop:
            return TargetVelocity(linear_velocity=0.0, angular_velocity=0.0)
        v = self.max_linear_speed * (inp.forward - inp.backward)
        omega = self.max_angular_speed * (inp.left - inp.right)
        return TargetVelocity(linear_velocity=v, angular_velocity=omega)
