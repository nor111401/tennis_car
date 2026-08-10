"""仿真推进逻辑（与显示解耦）。

Simulation 以固定时间步长推进世界仿真：
- 运动积分使用 fixed_dt，不依赖显示帧率；
- 显示层只负责渲染，帧率只影响画面刷新频率。
"""
from __future__ import annotations

from .controller import Observation
from .world import World


class Simulation:
    """仿真时间轴与暂停/运行状态。"""

    def __init__(self, world: World, fixed_dt: float = 1.0 / 60.0,
                 time_scale: float = 1.0) -> None:
        if fixed_dt <= 0:
            raise ValueError("fixed_dt 必须大于零")
        if time_scale <= 0:
            raise ValueError("time_scale 必须大于零")
        self.world = world
        self.fixed_dt = fixed_dt
        self.time_scale = time_scale
        self.time: float = 0.0
        self.paused: bool = False
        self.running: bool = True

    def step(self) -> None:
        """推进一个固定仿真步长。"""
        dt = self.fixed_dt * self.time_scale
        # 1) 更新小车位姿；2) 刷新可见性；3) 自动收集
        self.world.robot.update(dt)
        self.world.update_visibility()
        self.world.try_auto_collect()
        self.time += dt

    def toggle_pause(self) -> None:
        """切换暂停/继续。"""
        self.paused = not self.paused

    def get_observation(self) -> Observation:
        """当前观测快照。"""
        return self.world.build_observation(self.time)
