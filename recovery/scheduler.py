"""
HealthScheduler — 控制器健康心跳检测。

单线程, 由主循环 tick() 驱动, 不创建独立线程。

检查项:
  - ADB 存活: 每 5s 执行 adb get-state
  - scrcpy 进程: 每 10s 检查 process.poll()
  - 最新帧时间: 每 5s 检查最近帧未超时
  - Minitouch: 每 10s socket ping
"""

import logging
import time
from typing import Callable, Optional

logger = logging.getLogger("pjsk.recovery.scheduler")


class HealthScheduler:
    """控制器健康心跳检测。"""

    # 检查间隔 (秒)
    ADB_INTERVAL = 5.0
    SCRCPY_INTERVAL = 10.0
    FRAME_INTERVAL = 5.0
    MINITOUCH_INTERVAL = 10.0

    # 帧超时阈值 (秒)
    FRAME_TIMEOUT = 15.0

    def __init__(self, controller, config: dict,
                 on_unhealthy: Optional[Callable] = None):
        self.controller = controller
        self.config = config
        self._on_unhealthy = on_unhealthy

        # 上次检查时间
        self._last_adb_check = 0.0
        self._last_scrcpy_check = 0.0
        self._last_frame_check = 0.0
        self._last_minitouch_check = 0.0

        # 最新帧时间
        self._last_frame_time = 0.0

        # 运行状态
        self._running = True

        # 缓存 adb + serial (避免每 tick 读取 config)
        self._adb_exe = config.get("adb", {}).get("executable", "adb")
        self._adb_serial = config.get("adb", {}).get("device_serial", "")

    def on_frame_received(self, timestamp: float):
        """主循环告知最新帧时间。"""
        self._last_frame_time = timestamp

    def on_tick(self, now: float):
        """在 _main_loop 中每帧调用, 内部按间隔执行检查。"""
        if not self._running:
            return

        # 1. ADB 存活
        if now - self._last_adb_check >= self.ADB_INTERVAL:
            self._last_adb_check = now
            if not self._check_adb():
                self._report("adb_down")

        # 2. 最新帧时间
        if now - self._last_frame_check >= self.FRAME_INTERVAL:
            self._last_frame_check = now
            if self._last_frame_time > 0 and \
               now - self._last_frame_time > self.FRAME_TIMEOUT:
                self._report("frame_timeout")

        # 3. scrcpy 进程
        if now - self._last_scrcpy_check >= self.SCRCPY_INTERVAL:
            self._last_scrcpy_check = now
            if not self._check_scrcpy():
                self._report("scrcpy_down")

        # 4. Minitouch
        if now - self._last_minitouch_check >= self.MINITOUCH_INTERVAL:
            self._last_minitouch_check = now
            if not self._check_minitouch():
                self._report("minitouch_down")

    def _check_adb(self) -> bool:
        """检查 ADB 是否存活。"""
        try:
            import subprocess
            serial = self._adb_serial
            cmd = [self._adb_exe]
            if serial:
                cmd += ["-s", serial]
            cmd.append("get-state")
            result = subprocess.run(cmd, capture_output=True,
                                    timeout=3, text=True)
            return result.returncode == 0 and "device" in result.stdout.strip().lower()
        except Exception:
            return False

    def _check_scrcpy(self) -> bool:
        """检查 scrcpy 进程是否存活。"""
        try:
            ctrl = self.controller
            if ctrl is None:
                return True  # 没有 scrcpy 控制器不报错
            if hasattr(ctrl, '_active_backend') and ctrl._active_backend:
                backend = ctrl._active_backend
                if hasattr(backend, '_process') and backend._process is not None:
                    return backend._process.poll() is None
            return True
        except Exception:
            return True  # 检查失败不报错

    def _check_minitouch(self) -> bool:
        """检查 Minitouch socket 是否存活。"""
        try:
            ctrl = self.controller
            if ctrl is None:
                return True
            if hasattr(ctrl, '_active_backend') and ctrl._active_backend:
                backend = ctrl._active_backend
                if hasattr(backend, '_mt_socket') and backend._mt_socket is not None:
                    try:
                        backend._mt_socket.send(b"")
                        return True
                    except (OSError, AttributeError):
                        return False
            return True
        except Exception:
            return True

    def _report(self, issue: str):
        """向上报告不健康状态。"""
        logger.warning("[Health] ⚠ 检测到异常: %s", issue)
        if self._on_unhealthy:
            self._on_unhealthy(issue)

    def stop(self):
        """停止所有检查。"""
        self._running = False

    def reset(self):
        """重置所有检查时间 (场景切换/恢复后调用)。"""
        now = time.time()
        self._last_adb_check = now
        self._last_scrcpy_check = now
        self._last_frame_check = now
        self._last_minitouch_check = now
        self._last_frame_time = now
