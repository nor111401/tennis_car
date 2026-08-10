"""Pygame 实时二维渲染。

渲染器只读仿真状态，不修改任何世界/小车数据。
仿真更新与绘制逻辑分离：渲染频率由 clock 控制，不影响运动学积分。
"""
from __future__ import annotations

import math

import pygame

from simulator.ball import Ball, BallStatus
from simulator.robot import Robot
from simulator.simulation import Simulation
from simulator.world import World
from utils.coordinate_transform import CoordinateTransformer
from utils.logger import get_logger
from .fonts import create_font, find_cjk_font_path
from .status_panel import StatusPanel


class Renderer:
    """负责所有画面绘制。"""

    FONT_SIZE = 20
    SMALL_FONT_SIZE = 15
    PANEL_MARGIN = 16
    FOV_SEGMENTS = 36
    HELP_LINE_HEIGHT = 17

    COLOR = {
        "court_bg": (30, 130, 88),
        "court_line": (255, 255, 255),
        "grid": (216, 242, 224),
        "ball_unseen": (238, 238, 238),
        "ball_unseen_edge": (130, 130, 140),
        "ball_visible": (255, 214, 60),
        "ball_visible_edge": (255, 255, 255),
        "ball_hidden": (160, 172, 182),
        "ball_id_text": (20, 22, 28),
        "ball_selected": (255, 64, 205),
        "robot_body": (46, 88, 168),
        "robot_edge": (205, 222, 255),
        "wheel": (24, 24, 24),
        "heading": (255, 255, 255),
        "fov_fill": (120, 200, 255),
        "help_bg": (16, 20, 26),
        "help_text": (238, 238, 238),
    }

    def __init__(self, window_config, court_config, robot_config,
                 camera_config, world: World) -> None:
        self.window_cfg = window_config
        self.court_cfg = court_config
        self.robot_cfg = robot_config
        self.camera_cfg = camera_config
        self.world = world
        self.logger = get_logger()

        pygame.init()
        self.screen = pygame.display.set_mode(
            (window_config.width, window_config.height)
        )
        pygame.display.set_caption(
            "Tennis Ball Collecting Robot — 2D Simulator"
        )
        # 加载支持中文的字体（pygame 默认字体不含 CJK 字形）
        cjk_font_path = find_cjk_font_path()
        self.font = create_font(self.FONT_SIZE)
        self.small_font = create_font(self.SMALL_FONT_SIZE)
        if cjk_font_path is None:
            self.logger.warning(
                "未找到支持中文的系统字体，界面中文将显示为方框；"
                "可安装微软雅黑/黑体后重试"
            )
        else:
            self.logger.info("界面使用中文字体: %s", cjk_font_path)

        self.canvas_w = window_config.width - window_config.panel_width
        self.canvas_h = window_config.height
        self.transformer = CoordinateTransformer(
            court_config.width_m, court_config.height_m,
            self.canvas_w, self.canvas_h, margin_px=self.PANEL_MARGIN,
        )
        self.panel = StatusPanel(
            window_config.panel_width, window_config.height,
            self.font, self.small_font,
        )
        # 半透明覆盖层（用于扇形视野等带透明度图形）
        self._overlay = pygame.Surface(
            (window_config.width, window_config.height), pygame.SRCALPHA
        )
        self.show_fov = True
        self.show_grid = True

    # -- 对外接口 -----------------------------------------------------------

    def toggle_fov(self) -> None:
        self.show_fov = not self.show_fov

    def toggle_grid(self) -> None:
        self.show_grid = not self.show_grid

    def render(self, simulation: Simulation, frame_input=None,
               keydown_count: int = 0, focused: bool = True,
               demo_mode: bool = False) -> None:
        """绘制一帧。frame_input 等为输入诊断信息。"""
        world = self.world
        self._draw_court_area()
        if self.show_grid:
            self._draw_grid()
        self._draw_balls(world.balls)
        self._draw_selected_target(world)
        if self.show_fov:
            self._draw_fov(world.robot)
        self._draw_robot(world.robot)
        self.panel.draw(self.screen, world, simulation,
                        frame_input=frame_input,
                        keydown_count=keydown_count,
                        focused=focused,
                        demo_mode=demo_mode)
        if demo_mode:
            self._draw_banner("演示模式 (F1 关闭)：小车自动绕圈",
                              (120, 220, 120))
        elif keydown_count == 0 and simulation.time > 1.5:
            self._draw_banner("未收到键盘事件 — 请点击本窗口获取焦点后使用 WASD",
                              (255, 130, 80))
        elif not focused and simulation.time > 1.5:
            self._draw_banner("窗口未聚焦 — 请点击本窗口",
                              (255, 190, 70))
        self._draw_help()
        pygame.display.flip()

    def _draw_banner(self, text: str, color) -> None:
        """在画布顶部中央绘制一条横幅。"""
        surf = self.font.render(text, True, color)
        rect = surf.get_rect()
        rect.midtop = (self.canvas_w // 2, 10)
        bg = surf.get_rect().inflate(16, 8)
        bg.midtop = rect.midtop
        pygame.draw.rect(self.screen, (18, 20, 26), bg)
        pygame.draw.rect(self.screen, color, bg, 2)
        self.screen.blit(surf, rect)

    # -- 场地与网格 -----------------------------------------------------------

    def _draw_court_area(self) -> None:
        rect = self.transformer.court_rect_px().as_pygame_rect()
        pygame.draw.rect(self.screen, self.COLOR["court_bg"], rect)
        pygame.draw.rect(self.screen, self.COLOR["court_line"], rect, 3)

    def _draw_grid(self) -> None:
        step = self.court_cfg.grid_step_m
        color = self.COLOR["grid"]
        rect = self.transformer.court_rect_px()
        x = 0.0
        while x <= self.court_cfg.width_m + 1e-9:
            sx = self.transformer.world_to_screen(x, 0.0)[0]
            pygame.draw.line(self.screen, color,
                             (int(sx), int(rect.y)), (int(sx), int(rect.y + rect.height)), 1)
            x += step
        y = 0.0
        while y <= self.court_cfg.height_m + 1e-9:
            sy = self.transformer.world_to_screen(0.0, y)[1]
            pygame.draw.line(self.screen, color,
                             (int(rect.x), int(sy)), (int(rect.x + rect.width), int(sy)), 1)
            y += step

    # -- 网球 --------------------------------------------------------------

    def _draw_balls(self, balls: list[Ball]) -> None:
        for ball in balls:
            if ball.status is BallStatus.COLLECTED:
                continue  # 已收集：隐藏
            sx, sy = self.transformer.world_to_screen(ball.x, ball.y)
            radius = max(int(ball.radius * self.transformer.scale_px_per_m), 3)
            center = (int(sx), int(sy))

            if ball.status is BallStatus.VISIBLE:
                # 当前可见：高亮
                pygame.draw.circle(self.screen, self.COLOR["ball_visible"],
                                   center, radius)
                pygame.draw.circle(self.screen, self.COLOR["ball_visible_edge"],
                                   center, radius + 4, 2)
            elif ball.status is BallStatus.HIDDEN:
                # 曾经见过、当前不可见：轮廓 + 内点
                pygame.draw.circle(self.screen, self.COLOR["ball_hidden"],
                                   center, radius, 2)
                pygame.draw.circle(self.screen, self.COLOR["ball_hidden"],
                                   center, 3)
            else:
                # 从未进入视野：普通颜色
                pygame.draw.circle(self.screen, self.COLOR["ball_unseen"],
                                   center, radius)
                pygame.draw.circle(self.screen, self.COLOR["ball_unseen_edge"],
                                   center, radius, 1)

            # 网球编号
            label = self.small_font.render(str(ball.id), True,
                                           self.COLOR["ball_id_text"])
            self.screen.blit(label, (int(sx) + radius + 3, int(sy) - radius - 8))

    def _draw_selected_target(self, world: World) -> None:
        if world.selected_ball_id is None:
            return
        ball = next((b for b in world.balls
                     if b.id == world.selected_ball_id), None)
        if ball is None or not ball.is_active():
            return
        sx, sy = self.transformer.world_to_screen(ball.x, ball.y)
        r = max(int(ball.radius * self.transformer.scale_px_per_m), 3) + 8
        pygame.draw.circle(self.screen, self.COLOR["ball_selected"],
                           (int(sx), int(sy)), r, 3)

    # -- 小车 --------------------------------------------------------------

    def _draw_robot(self, robot: Robot) -> None:
        pose = robot.get_pose()
        cx, cy = self.transformer.world_to_screen(pose.x, pose.y)
        scale = self.transformer.scale_px_per_m
        half_len = self.robot_cfg.length / 2.0
        half_wid = self.robot_cfg.width / 2.0
        cos_t = math.cos(pose.theta)
        sin_t = math.sin(pose.theta)

        # 车体四角（局部坐标系 -> 世界 -> 屏幕）
        corners_local = [(half_len, half_wid), (half_len, -half_wid),
                         (-half_len, -half_wid), (-half_len, half_wid)]
        pts: list[tuple[int, int]] = []
        for lx, ly in corners_local:
            rx = lx * cos_t - ly * sin_t
            ry = lx * sin_t + ly * cos_t
            pts.append((int(cx + rx * scale), int(cy - ry * scale)))
        pygame.draw.polygon(self.screen, self.COLOR["robot_body"], pts)
        pygame.draw.polygon(self.screen, self.COLOR["robot_edge"], pts, 2)

        # 朝向箭头
        arrow_len = int((half_len + 0.15) * scale)
        tip = (int(cx + cos_t * arrow_len), int(cy - sin_t * arrow_len))
        pygame.draw.line(self.screen, self.COLOR["heading"],
                         (int(cx), int(cy)), tip, 3)
        pygame.draw.circle(self.screen, self.COLOR["heading"], tip, 4)

        # 左右轮位置（车体两侧中点）
        wheel_radius = max(int(self.robot_cfg.wheel_radius * scale), 3)
        for side in (+1.0, -1.0):
            off_y = side * (half_wid * 0.85)
            wx = -off_y * sin_t
            wy = off_y * cos_t
            w_center = (int(cx + wx * scale), int(cy - wy * scale))
            pygame.draw.circle(self.screen, self.COLOR["wheel"], w_center,
                               wheel_radius)

    # -- 摄像头视野 -----------------------------------------------------------

    def _draw_fov(self, robot: Robot) -> None:
        cam_pose = self.world.camera.camera_pose(robot.get_pose())
        cx, cy = self.transformer.world_to_screen(cam_pose.x, cam_pose.y)
        half = self.camera_cfg.half_fov_rad
        max_dist = self.camera_cfg.max_detection_distance

        # 扇形外圈采样点（世界系 -> 屏幕系）
        pts: list[tuple[int, int]] = [(int(cx), int(cy))]
        for i in range(self.FOV_SEGMENTS + 1):
            angle = cam_pose.theta - half + (2.0 * half) * i / self.FOV_SEGMENTS
            wx = cam_pose.x + max_dist * math.cos(angle)
            wy = cam_pose.y + max_dist * math.sin(angle)
            sx, sy = self.transformer.world_to_screen(wx, wy)
            pts.append((int(sx), int(sy)))

        # 半透明填充（仅在场地矩形内可见）
        court_rect = self.transformer.court_rect_px().as_pygame_rect()
        self._overlay.fill((0, 0, 0, 0))
        pygame.draw.polygon(self._overlay, (*self.COLOR["fov_fill"], 55), pts)
        self.screen.set_clip(court_rect)
        self.screen.blit(self._overlay, (0, 0))
        # 扇形轮廓
        pygame.draw.lines(self.screen, self.COLOR["fov_fill"], False, pts, 2)
        self.screen.set_clip(None)

    # -- 提示文字 -------------------------------------------------------------

    def _draw_help(self) -> None:
        lines = [
            "W/S 前进/后退    A/D 左转/右转    空格 停止",
            "R 重置    B 重生成球    C 手动收集    P 暂停",
            "V 视野开/关    G 网格开/关    T 切换目标    F1 演示    ESC 退出",
        ]
        y = self.canvas_h - 6 - len(lines) * self.HELP_LINE_HEIGHT
        for line in lines:
            surf = self.small_font.render(line, True, self.COLOR["help_text"])
            rect = surf.get_rect()
            rect.bottomleft = (8, y)
            pygame.draw.rect(self.screen, self.COLOR["help_bg"],
                             rect.inflate(8, 4))
            self.screen.blit(surf, rect)
            y += self.HELP_LINE_HEIGHT
