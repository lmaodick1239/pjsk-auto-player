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
        """启动 scrcpy PPM 视频流。返回是否成功。"""
        if self._running:
            return True

        max_fps = self.cfg.get("max_fps", 60)
        bit_rate = self.cfg.get("bit_rate", 8000000)
        scale = self.cfg.get("scale", 0.5)

        # PPM 模式: 输出原始像素数据, 无需编解码
        cmd = [self.executable]

        if self.serial:
            cmd += ["-s", self.serial]

        # --no-window: 不显示窗口
        # --no-control: 不处理输入
        # --output-format=ppm: 输出 PPM 格式 (关键!)
        # --max-fps: 限制帧率
        cmd += [
            "--no-window",
            "--no-control",
            "--output-format=ppm",
            "--max-fps", str(max_fps),
            "--max-size", str(int(1080 * scale)),
            "--video-bit-rate", str(bit_rate),
        ]

        logger.info(f"启动 scrcpy PPM 流: max_fps={max_fps}, scale={scale}")

        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=0,  # 无缓冲
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
            name="scrcpy-ppm-reader"
        )
        self._reader_thread.start()

        # 等待首帧
        for _ in range(100):
            time.sleep(0.01)
            with self._lock:
                if self._latest_frame is not None:
                    h, w = self._latest_frame.shape[:2]
                    logger.info(f"scrcpy PPM 已启动: {w}x{h} @ {max_fps}FPS")
                    return True

        logger.warning("scrcpy PPM 启动超时 (未收到帧)")
        self.stop()
        return False

    def _read_loop(self):
        """
        后台线程: 读取 scrcpy stdout 的 PPM 数据流。

        PPM 格式:
          Header: "P6\\n<width> <height>\\n255\\n"
          Data:   width × height × 3 bytes (RGB)
        """
        self._buffer = b""
        self._state = "header"

        while self._running and self._process and self._process.stdout:
            try:
                chunk = self._process.stdout.read(65536)
            except Exception:
                break

            if not chunk:
                logger.info("scrcpy PPM 流结束")
                break

            self._buffer += chunk
            self._parse_buffer()

        logger.info("scrcpy PPM 读取线程已退出")

    def _parse_buffer(self):
        """
        从缓冲区解析 PPM 帧 (v5.2 优化: 一行式 header 解析 + 批量处理)。

        PPM P6 格式:
          Header: "P6\n<width> <height>\n255\n"
          Data:   width × height × 3 bytes (RGB)

        优化: 使用 splitlines() 一次性解析 header,
              避免多次 find() 调用和 byte 切片操作。
        """
        while True:
            if self._state == "header":
                # 检查是否有完整的 header (至少需要 3 行)
                lines = self._buffer.split(b"\n", 3)
                if len(lines) < 4:
                    break  # header 不完整, 等待更多数据

                # P6
                if lines[0].strip() != b"P6":
                    # 无效格式, 跳过这个字节重新扫描
                    self._buffer = self._buffer[1:]
                    continue

                # 解析尺寸 "W H"
                try:
                    dims = lines[1].strip().decode("ascii")
                    parts = dims.split()
                    self._ppm_width = int(parts[0])
                    self._ppm_height = int(parts[1])
                except (ValueError, UnicodeDecodeError, IndexError):
                    self._buffer = self._buffer[1:]
                    continue

                # 验证最大值行 (通常为 "255")
                # 可能包含注释, 跳过多余头部行
                max_val_line = lines[2].strip()
                if max_val_line.startswith(b"#"):
                    # 罕见: PPM 带注释行, 继续向后扫描
                    extended = self._buffer.split(b"\n", 5)
                    if len(extended) >= 5:
                        max_val_line = extended[4].strip()
                    else:
                        break
                # 容忍非标准值 (如 "255" 但可能有空格)

                # 计算 data 在 buffer 中的偏移
                # 前 3 行的总字节数 = 3 个分隔符 + 各自内容
                header_end = (len(lines[0]) + len(lines[1]) + len(lines[2])
                              + 3)  # 3 个 \n
                self._ppm_data_size = self._ppm_width * self._ppm_height * 3
                self._state = "data"
                self._buffer = self._buffer[header_end:]

                # 验证数据大小合理性
                if self._ppm_data_size <= 0 or self._ppm_data_size > 100 * 1024 * 1024:
                    logger.warning(f"PPM 数据大小异常: {self._ppm_data_size}, 重置")
                    self._state = "header"
                    self._buffer = b""
                    break

            if self._state == "data":
                if len(self._buffer) < self._ppm_data_size:
                    break  # 数据还不够

                # 取出一帧
                frame_data = self._buffer[:self._ppm_data_size]

                # PPM 是 RGB, OpenCV 需要 BGR
                rgb = np.frombuffer(frame_data, dtype=np.uint8).reshape(
                    self._ppm_height, self._ppm_width, 3
                )
                # RGB → BGR (使用视图操作加速)
                bgr = rgb[:, :, ::-1].copy()

                with self._lock:
                    self._latest_frame = bgr
                    self._frame_count += 1

                    # FPS 统计
                    now = time.time()
                    if now - self._last_fps_time >= 1.0:
                        self._fps = self._frame_count / (now - self._last_fps_time)
                        self._frame_count = 0
                        self._last_fps_time = now

                # 移除已处理的数据, 保留可能的下一帧头部
                self._buffer = self._buffer[self._ppm_data_size:]
                self._state = "header"

                # 继续循环, buffer 中可能已有下一帧
                continue

            break

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
