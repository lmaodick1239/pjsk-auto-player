"""
scrcpy 视频流后端 —— 通过 PPM 格式从 scrcpy 获取高帧率手机画面。

原理:
  scrcpy --output-format=ppm 将手机屏幕以 PPM (便携像素图) 格式
  持续输出到 stdout。每帧包含: header + RGB 像素数据。
  OpenCV 可以直接解码 PPM 格式。

  相比 ADB screencap (5-15 FPS), 通过 scrcpy 可获得 30-60 FPS,
  是执行自动化的关键性能提升。

需要安装 scrcpy:
  - macOS: brew install scrcpy
  - Windows: scoop install scrcpy
  - Linux: apt install scrcpy
"""

import logging
import os
import subprocess
import sys
import threading
import time
from typing import Optional

import numpy as np

logger = logging.getLogger("pjsk_scrcpy")


class ScrcpyController:
    """
    scrcpy 视频流控制器 (PPM 模式)。

    启动 scrcpy 进程并通过 stdout 持续读取 PPM 格式的视频帧。
    提供 get_frame() 方法供 ADBController 调用。
    """

    def __init__(self, config: dict):
        self.cfg = config.get("scrcpy", {})
        self.serial = config.get("adb", {}).get("device_serial", "")
        self.executable = self._find_scrcpy()

        self._process: Optional[subprocess.Popen] = None
        self._latest_frame: Optional[np.ndarray] = None
        self._lock = threading.Lock()
        self._running = False
        self._reader_thread: Optional[threading.Thread] = None
        self._frame_count = 0
        self._fps = 0.0
        self._last_fps_time = time.time()

        # PPM 解析状态
        self._buffer = b""
        self._header_done = False
        self._ppm_width = 0
        self._ppm_height = 0
        self._ppm_data_size = 0
        self._state = "header"  # header → data

        # 帧跳过 (后台线程始终只保留最新帧, 天然不积压)
        self._frame_skip_enabled = self.cfg.get("frame_skip", True)

    def _find_scrcpy(self) -> str:
        """查找 scrcpy 可执行文件。"""
        exe = self.cfg.get("executable", "scrcpy")
        if os.path.isfile(exe):
            return exe
        which_cmd = "where" if sys.platform == "win32" else "which"
        try:
            subprocess.run([which_cmd, exe], capture_output=True, check=True)
            logger.info(f"scrcpy 已找到: {exe}")
            return exe
        except (subprocess.CalledProcessError, FileNotFoundError):
            logger.error(
                f"'{exe}' 未在 PATH 中。请安装 scrcpy"
            )
            return exe

    def start(self) -> bool:
        """Launch scrcpy with a specific window title and start window capture."""
        if self._running:
            return True

        max_fps = self.cfg.get("max_fps", 60)
        bit_rate = self.cfg.get("bit_rate", 8000000)
        scale = self.cfg.get("scale", 0.5)

        cmd = [self.executable]

        if self.serial:
            cmd += ["-s", self.serial]

        # Use a unique window title to easily find the window
        self._window_title = f"pjsk_scrcpy_{int(time.time())}"

        cmd += [
            "--window-title", self._window_title,
            "--max-fps", str(max_fps),
            "--max-size", str(int(1080 * scale)),
            "--video-bit-rate", str(bit_rate),
        ]

        logger.info(f"启动 scrcpy 窗口捕获: max_fps={max_fps}, scale={scale}")

        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            logger.error("scrcpy 未安装")
            return False
        except Exception as e:
            logger.error(f"启动 scrcpy 失败: {e}")
            return False

        self._running = True
        self._reader_thread = threading.Thread(
            target=self._read_loop,
            daemon=True,
            name="scrcpy-window-capture"
        )
        self._reader_thread.start()

        # 等待首帧
        for _ in range(200):
            time.sleep(0.01)
            with self._lock:
                if self._latest_frame is not None:
                    h, w = self._latest_frame.shape[:2]
                    logger.info(f"scrcpy 窗口捕获已启动: {w}x{h} @ {max_fps}FPS")
                    return True

        logger.warning("scrcpy 启动超时 (未捕获到帧)")
        self.stop()
        return False

    def _read_loop(self):
        """后台线程: 持续捕获 scrcpy 窗口。"""
        import cv2
        try:
            import mss
            import pygetwindow as gw
        except ImportError:
            logger.error("未安装 mss 或 pygetwindow。请运行 'pip install mss pygetwindow'")
            return

        with mss.mss() as sct:
            window = None
            for _ in range(50):
                windows = gw.getWindowsWithTitle(self._window_title)
                if windows:
                    window = windows[0]
                    break
                time.sleep(0.1)

            if not window:
                logger.error("无法找到 scrcpy 窗口")
                return

            while self._running:
                try:
                    if window.isMinimized:
                        time.sleep(0.1)
                        continue

                    rect = {"left": window.left, "top": window.top, "width": window.width, "height": window.height}

                    if rect["width"] <= 0 or rect["height"] <= 0:
                        time.sleep(0.1)
                        continue

                    sct_img = sct.grab(rect)
                    img = np.array(sct_img)
                    bgr = img[:, :, :3]

                    with self._lock:
                        self._latest_frame = bgr
                        self._frame_count += 1
                        
                        now = time.time()
                        if now - self._last_fps_time >= 1.0:
                            self._fps = self._frame_count / (now - self._last_fps_time)
                            self._frame_count = 0
                            self._last_fps_time = now

                except Exception as e:
                    logger.warning(f"窗口捕获错误: {e}")
                    time.sleep(0.1)

                time.sleep(1.0 / self.cfg.get("max_fps", 60))

        logger.info("scrcpy 窗口捕获线程已退出")

    def get_frame(self) -> Optional[np.ndarray]:
        """
        获取最新视频帧 (BGR 格式)。

        v5.2 FIX: 修复 frame_skip 逻辑缺陷 — 原逻辑 `% 2 == 0` 每两帧才返回一帧,
        导致主循环获取帧率减半。修复后始终返回最新帧; frame_skip 改为控制
        后台读取线程是否丢弃积压帧 (始终只保留最新帧, 天然避免了积压问题)。
        """
        with self._lock:
            if self._latest_frame is None:
                return None
            # 始终返回最新帧的副本。
            # 后台线程持续以最大速率覆盖 self._latest_frame,
            # 取帧线程取到的是"当前最新", 天然无积压。
            return self._latest_frame.copy()

    def get_fps(self) -> float:
        """获取当前 FPS。"""
        with self._lock:
            return self._fps

    def stop(self):
        """关闭 scrcpy 进程。"""
        self._running = False
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=3)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None
        logger.info("scrcpy PPM 已停止")
