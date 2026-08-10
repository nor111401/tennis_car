"""自动网球捡球小车 —— 二维仿真平台入口。

运行：
    python main.py

无界面/CI 冒烟测试支持：
    设置 SDL_VIDEODRIVER=dummy 与 TENNIS_SIM_AUTOQUIT_FRAMES=N，
    渲染 N 帧后自动退出，用于无显示器环境验证主循环。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# 保证从任意目录运行都能导入项目包
_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pygame

from simulator.config import load_config
from simulator.controller import KeyboardController
from simulator.simulation import Simulation
from simulator.types import FrameInput, TargetVelocity
from simulator.world import World
from ui.input_handler import InputHandler
from ui.renderer import Renderer
from utils.logger import setup_logging

# 版本号：用于确认是否运行了最新代码（显示在窗口标题与启动日志中）
APP_VERSION = "1.2"


def main() -> int:
    # 1. 加载配置与日志
    config = load_config()
    log = setup_logging(
        log_dir=config.logging.dir,
        console_level=config.logging.console_level,
        file_level=config.logging.file_level,
    )
    log.info("配置加载成功：场地 %.1f x %.1f m，%d 个网球，随机种子 %d",
             config.court.width_m, config.court.height_m,
             config.balls.count, config.balls.random_seed)

    # 2. 构建世界与仿真
    world = World(config, logger=log)
    simulation = Simulation(world, fixed_dt=config.simulation.fixed_dt,
                            time_scale=config.simulation.time_scale)

    # 3. 界面与控制器
    renderer = Renderer(config.window, config.court, config.robot,
                        config.camera, world)
    pygame.display.set_caption(
        f"Tennis Ball Robot Sim v{APP_VERSION} — 点击窗口后使用 WASD"
    )
    input_handler = InputHandler(logger=log)
    controller = KeyboardController(config.robot.max_linear_speed,
                                    config.robot.max_angular_speed)

    clock = pygame.time.Clock()
    accumulator = 0.0  # 固定时间步长累积器（秒）
    autoquit_frames = int(os.environ.get("TENNIS_SIM_AUTOQUIT_FRAMES", "0"))
    frame_count = 0
    demo_mode = False
    input_warning_logged = False
    frame_input = FrameInput()

    log.info("进入主循环 v%s（目标 %d FPS，固定步长 %.4f s）",
             APP_VERSION, config.window.fps, simulation.fixed_dt)
    running = True
    try:
        while running:
            frame_ms = clock.tick(config.window.fps)

            # 单次动作按键
            for action in input_handler.process_events(pygame.event.get()):
                if action == "quit":
                    running = False
                    log.info("收到退出请求")
                elif action == "reset":
                    world.reset()
                    log.info("用户重置小车和网球")
                elif action == "respawn":
                    world.regenerate_balls()
                    log.info("用户重新随机生成网球")
                elif action == "collect":
                    collected = world.collect_if_possible()
                    log.info("手动收集：本次收集 %d 个网球", collected)
                elif action == "toggle_pause":
                    simulation.toggle_pause()
                    log.info("仿真状态：%s",
                             "暂停" if simulation.paused else "继续")
                elif action == "toggle_fov":
                    renderer.toggle_fov()
                elif action == "toggle_grid":
                    renderer.toggle_grid()
                elif action == "cycle_target":
                    world.cycle_selected_target()
                elif action == "toggle_demo":
                    demo_mode = not demo_mode
                    world.robot.stop()
                    log.info("演示模式：%s", "开启" if demo_mode else "关闭")

            if not running:
                break

            # 输入诊断：运行一段时间仍未收到任何按键事件时提示
            if (input_handler.keydown_count() == 0
                    and simulation.time > 2.0 and not input_warning_logged):
                input_warning_logged = True
                log.warning(
                    "运行 2 秒仍未收到键盘事件：请点击仿真窗口使其获得焦点后再操作"
                )

            frame_input = input_handler.get_frame_input()
            if not simulation.paused:
                # 键盘控制通过统一控制接口产生目标速度，不直接修改坐标
                if demo_mode:
                    # F1 演示模式：小车自动绕圈，用于诊断
                    target = TargetVelocity(linear_velocity=0.3,
                                            angular_velocity=0.6)
                else:
                    controller.set_input(frame_input)
                    observation = simulation.get_observation()
                    target = controller.update(observation,
                                               simulation.fixed_dt)
                world.robot.set_velocity(target.linear_velocity,
                                         target.angular_velocity)

                # 固定时间步长推进，避免运动积分依赖显示帧率
                accumulator += frame_ms / 1000.0
                accumulator = min(accumulator, 0.1)  # 防止卡顿后追帧过多
                while accumulator >= simulation.fixed_dt:
                    simulation.step()
                    accumulator -= simulation.fixed_dt
            else:
                accumulator = 0.0

            renderer.render(simulation,
                            frame_input=frame_input,
                            keydown_count=input_handler.keydown_count(),
                            focused=input_handler.is_focused(),
                            demo_mode=demo_mode)
            frame_count += 1
            if autoquit_frames and frame_count >= autoquit_frames:
                running = False
                log.info("自动退出（冒烟测试：渲染 %d 帧）", frame_count)
    except Exception:
        log.exception("主循环发生异常")
        raise
    finally:
        pygame.quit()
        log.info("仿真结束，累计仿真时间 %.2f 秒", simulation.time)
    return 0


if __name__ == "__main__":
    sys.exit(main())
