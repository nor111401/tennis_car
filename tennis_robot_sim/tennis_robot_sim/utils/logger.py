"""日志系统：同时输出到控制台与 logs/ 目录下的文本文件。"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path


def _parse_level(name: str) -> int:
    level = getattr(logging, str(name).upper(), None)
    if not isinstance(level, int):
        return logging.INFO
    return level


def setup_logging(log_dir: str = "logs",
                  console_level: str = "INFO",
                  file_level: str = "DEBUG",
                  name: str = "tennis_sim") -> logging.Logger:
    """初始化并返回项目日志器。

    - console_level / file_level 接受 DEBUG/INFO/WARNING/ERROR/CRITICAL；
    - 日志同时输出到控制台与 log_dir 下的 sim_<时间戳>.log 文件；
    - 重复调用不会重复添加 handler。
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    if logger.handlers:  # 已初始化过
        return logger

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    console = logging.StreamHandler()
    console.setLevel(_parse_level(console_level))
    console.setFormatter(fmt)
    logger.addHandler(console)

    os.makedirs(log_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_path = str(Path(log_dir) / f"sim_{timestamp}.log")
    file_handler = logging.FileHandler(file_path, encoding="utf-8")
    file_handler.setLevel(_parse_level(file_level))
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    logger.info("日志文件: %s", file_path)
    return logger


def get_logger(name: str = "tennis_sim") -> logging.Logger:
    """获取已有日志器（未初始化时返回一个无 handler 的 logger）。"""
    return logging.getLogger(name)
