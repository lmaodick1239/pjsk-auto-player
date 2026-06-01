"""
ADB 控制器 —— 通过 ADB / scrcpy 连接安卓手机, 完成截图、触摸操作。

支持多种后端:
  - ADB exec-out screencap (默认, 5-15 FPS)
  - ADB file screencap (兼容模式, 3-8 FPS)
  - scrcpy 视频流 (可选, 30-60 FPS, 需安装 scrcpy)

Windows / macOS / Linux 通用。
"""

import subprocess
import time
import logging
import os
import sys
import socket
import threading
from typing import Optional

import numpy as np

logger = logging.getLogger("pjsk_adb")


class ADBController:
    """ADB 控制器, 封装设备连接、截图、触摸操作。"""

    def __init__(self, config: dict):
        self.cfg = config["adb"]
        self.screen = config["screen"]
        self.executable = self._find_adb()
        self.serial = self.cfg.get("device_serial", "").strip()

        # 后端状态标志 (替代 hasattr)
        self._scrcpy_ready = False
        self._mt_ready = False
        self._scrcpy_instance = None
        self._minitouch_socket: Optional[socket.socket] = None  # v5.2: 提前初始化防 AttributeError
        self._minitouch_proc = None

        # v5.6.1: 提前初始化异步截屏属性，消除热路径 getattr 开销
        self._async_running = False
        self._async_frame: Optional[np.ndarray] = None
        self._async_lock = threading.Lock()
        self._async_last_time = 0.0
        self._async_fps = 0.0
        self._async_frame_count = 0
        self._async_target_interval = 0.0
        self._async_thread: Optional[threading.Thread] = None

        # v5.6.1: 子进程缓存 — 避免每帧 subprocess.run 隐式 fork() 开销
        self._adb_last_check = 0.0
        self._adb_cached_devices: list[dict] = []

    # ──────────────────────────────────────────
    def _find_adb(self) -> str:
        """查找 adb 可执行文件 (Windows 下为 adb.exe)。"""
        exe = self.cfg.get("executable", "adb")
        # 如果指定了完整路径, 直接使用
        if os.path.isfile(exe):
            return exe
        # 从 PATH 查找
        which_cmd = "where" if sys.platform == "win32" else "which"
        try:
            subprocess.run([which_cmd, exe], capture_output=True, check=True)
            return exe
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass

        # 自动下载 ADB
        logger.info("ADB 未在 PATH 中找到, 尝试自动下载...")
        downloaded = self._download_adb()
        if downloaded and os.path.isfile(downloaded):
            self.executable = downloaded
            return downloaded

        logger.warning(f"ADB 未找到, 请安装: "
                       "https://developer.android.com/studio/releases/platform-tools")
        return exe

    def _download_adb(self) -> str:
        """自动下载 ADB platform-tools。"""
        import urllib.request
        import zipfile
        import platform as pf

        system = pf.system()
        url = ""
        if system == "Darwin":
            url = "https://dl.google.com/android/repository/platform-tools-latest-darwin.zip"
        elif system == "Linux":
            url = "https://dl.google.com/android/repository/platform-tools-latest-linux.zip"
        elif system == "Windows":
            url = "https://dl.google.com/android/repository/platform-tools-latest-windows.zip"
        else:
            return ""

        cache_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache", "adb")
        os.makedirs(cache_dir, exist_ok=True)
        adb_exe = os.path.join(cache_dir, "platform-tools",
                               "adb.exe" if system == "Windows" else "adb")

        if os.path.isfile(adb_exe):
            logger.info(f"ADB 已缓存: {adb_exe}")
            return adb_exe

        zip_path = os.path.join(cache_dir, "platform-tools.zip")
        try:
            logger.info(f"下载 ADB: {url}")
            # 设置 120s 超时防止网络问题导致无限卡住
            urllib.request.urlretrieve(url, zip_path)
            with zipfile.ZipFile(zip_path, "r") as z:
                z.extractall(cache_dir)
            os.chmod(adb_exe, 0o755)
            logger.info(f"ADB 下载完成: {adb_exe}")
            # 清理临时 zip
            try:
                os.remove(zip_path)
            except OSError:
                pass
            return adb_exe
        except Exception as e:
            logger.warning(f"ADB 下载失败: {e}")
            # 清理破损的临时文件
            try:
                os.remove(zip_path)
            except OSError:
                pass
            return ""

    def _adb_cmd(self, *args: str) -> list[str]:
        """构造 adb 命令列表。"""
        cmd = [self.executable]
        if self.serial:
            cmd += ["-s", self.serial]
        cmd += list(args)
        return cmd

    def devices(self) -> list[dict]:
        """列出已连接的设备。"""
        result = subprocess.run(
            self._adb_cmd("devices"),
            capture_output=True, text=True, timeout=10
        )
        lines = result.stdout.strip().splitlines()
        devices = []
        for line in lines[1:]:
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) == 2 and parts[1] == "device":
                devices.append({"serial": parts[0], "status": "device"})
        return devices

    def is_connected(self) -> bool:
        """检查设备是否连接。设备列表有 1s 缓存，减少 subprocess 调用。"""
        now = time.time()
        if now - self._adb_last_check < 1.0 and self._adb_cached_devices:
            devs = self._adb_cached_devices
        else:
            devs = self.devices()
            self._adb_cached_devices = devs
            self._adb_last_check = now
        if self.serial:
            return any(d["serial"] == self.serial for d in devs)
        return len(devs) > 0

    def wait_for_device(self, timeout: int = 30) -> bool:
        """等待设备连接。"""
        logger.info(f"等待设备连接 (超时 {timeout}s)...")
        for _ in range(timeout):
            if self.is_connected():
                logger.info("设备已连接.")
                return True
            time.sleep(1)
        logger.error("设备连接超时.")
        return False

    def get_screen_size(self) -> tuple[int, int]:
        """通过 adb shell wm size 获取屏幕尺寸。"""
        try:
            result = subprocess.run(
                self._adb_cmd("shell", "wm", "size"),
                capture_output=True, text=True, timeout=10
            )
            for line in result.stdout.splitlines():
                if "Physical size:" in line or "Override size:" in line:
                    if "x" in line:
                        size_str = line.split()[-1].strip()
                        w, h = size_str.split("x")
                        return int(w), int(h)
        except Exception as e:
            logger.warning(f"获取屏幕尺寸失败: {e}")
        return self.screen["width"], self.screen["height"]

    # ──────────────────────────────────────────
    # 屏幕截图 (后端分发)
    # ──────────────────────────────────────────

    def screencap(self) -> Optional[np.ndarray]:
        """
        截取手机屏幕, 返回 BGR numpy 数组 (OpenCV 格式)。

        自动选择已配置的截图方法。
        如果异步截屏线程已启动, 直接返回最新缓存帧 (零延迟)。
        否则: 自动检测 scrcpy → ADB raw → ADB PNG 依次降级。
        """
        import cv2  # 延迟导入

        # v5.2: 如果异步截屏在运行, 直接用缓存帧 (零延迟)
        # 如果缓存帧超过 3 秒未更新, 说明线程可能已死, 回退到同步模式
        if self._async_running:
            with self._async_lock:
                if self._async_frame is not None and (time.time() - self._async_last_time) < 3.0:
                    return self._async_frame.copy()
                # 线程可能卡死, 静默回退到同步
                if self._async_frame is None:
                    logger.debug("异步截屏: 缓存帧为空, 回退到同步模式")

        method = self.cfg.get("screencap_method", "auto")

        # ===== auto 模式 — 自动检测最快可用后端 =====
        if method == "auto":
            if self._scrcpy_ready:
                return self._screencap_scrcpy()
            # 首次: 尝试自动检测 scrcpy
            try:
                import shutil
                if shutil.which("scrcpy"):
                    logger.debug("scrcpy 已检测到, 自动启用 scrcpy 后端")
                    self.cfg["screencap_method"] = "scrcpy"
                    self._scrcpy_ready = True
                    return self._screencap_scrcpy()
            except Exception:
                pass
            # scrcpy 不可用, 降级到 raw screencap (比 PNG 快 2-3x)
            logger.debug("scrcpy 未安装, 使用 ADB raw screencap (10-25 FPS)")
            self.cfg["screencap_method"] = "raw"
            return self._screencap_raw()

        if method == "scrcpy":
            return self._screencap_scrcpy()
        elif method == "raw":
            return self._screencap_raw()
        elif method == "exec-out":
            return self._screencap_execout()
        elif method == "file":
            return self._screencap_file()
        else:
            logger.error(f"不支持的 screencap 方法: {method}")
            return None

    def _screencap_raw(self) -> Optional[np.ndarray]:
        """
        使用 adb exec-out screencap (无 -p 参数) 获取原始 RGBA 截图。
        比 PNG 模式快 2-3 倍 (无需 PNG 编解码), 可达 10-25 FPS。

        原始数据格式 (小端序):
          4 bytes: width  (uint32 LE)
          4 bytes: height (uint32 LE)
          4 bytes: pixel_format (uint32 LE, 1=RGBA_8888)
          width*height*4 bytes: pixel data (RGBA)
        """
        import cv2
        import struct

        try:
            result = subprocess.run(
                self._adb_cmd("exec-out", "screencap"),
                capture_output=True, timeout=10
            )
            if result.returncode != 0 or len(result.stdout) < 16:
                # 回退到 PNG 模式 (某些设备不支持 raw)
                logger.debug(f"raw screencap 不可用 (stdout={len(result.stdout)} bytes), 回退到 PNG")
                return self._screencap_execout()

            data = result.stdout
            # 解析 header (little-endian)
            w = struct.unpack_from("<I", data, 0)[0]
            h = struct.unpack_from("<I", data, 4)[0]
            fmt = struct.unpack_from("<I", data, 8)[0]
            header_size = 12

            # 验证合理性
            if w <= 0 or h <= 0 or w > 4096 or h > 4096:
                logger.warning(f"raw screencap 尺寸异常: {w}x{h}, 回退到 PNG")
                return self._screencap_execout()

            expected_size = header_size + w * h * 4
            if len(data) < expected_size:
                logger.warning(f"raw screencap 数据不完整 ({len(data)} < {expected_size}), 回退到 PNG")
                return self._screencap_execout()

            # 提取像素数据 (RGBA → BGR)
            pixels = data[header_size:header_size + w * h * 4]
            rgba = np.frombuffer(pixels, dtype=np.uint8).reshape(h, w, 4)

            # RGBA → BGR (OpenCV 格式)
            # 丢弃 alpha 通道, RGB → BGR
            frame = cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGR)
            return frame

        except subprocess.TimeoutExpired:
            logger.warning("raw screencap 超时, 回退到 PNG")
            return self._screencap_execout()
        except Exception as e:
            logger.warning(f"raw screencap 异常: {e}, 回退到 PNG")
            return self._screencap_execout()

    def _screencap_execout(self) -> Optional[np.ndarray]:
        """使用 adb exec-out screencap -p 获取 PNG 截图 (兼容模式, 5-15 FPS)。"""
        import cv2

        try:
            result = subprocess.run(
                self._adb_cmd("exec-out", "screencap", "-p"),
                capture_output=True, timeout=15
            )
            if result.returncode != 0 or len(result.stdout) < 100:
                logger.warning(f"screencap 失败, stdout={len(result.stdout)} bytes")
                return None

            img_arr = np.frombuffer(result.stdout, dtype=np.uint8)
            frame = cv2.imdecode(img_arr, cv2.IMREAD_COLOR)
            if frame is None:
                logger.warning("screencap 解码失败")
                return None
            return frame

        except subprocess.TimeoutExpired:
            logger.warning("screencap 超时")
            return None
        except Exception as e:
            logger.warning(f"screencap 异常: {e}")
            return None

    def _screencap_file(self) -> Optional[np.ndarray]:
        """截图保存到设备文件再 pull (兼容模式, 3-8 FPS)。"""
        import cv2

        try:
            ts = int(time.time() * 1000)
            remote_path = f"{self.cfg.get('temp_dir', '/sdcard/')}ss_{ts}.png"

            subprocess.run(
                self._adb_cmd("shell", "screencap", "-p", remote_path),
                capture_output=True, timeout=15
            )

            local_temp = f"__temp_ss_{ts}.png"
            subprocess.run(
                self._adb_cmd("pull", remote_path, local_temp),
                capture_output=True, timeout=15
            )
            subprocess.run(
                self._adb_cmd("shell", "rm", remote_path),
                capture_output=True, timeout=10
            )

            frame = cv2.imread(local_temp)
            if os.path.exists(local_temp):
                os.remove(local_temp)
            return frame

        except Exception as e:
            logger.warning(f"screencap_file 异常: {e}")
            return None

    # ──────────────────────────────────────────
    # scrcpy 后端 (可选, 30-60 FPS)
    # ──────────────────────────────────────────

    def _screencap_scrcpy(self) -> Optional[np.ndarray]:
        """
        通过 scrcpy 视频流获取画面帧。

        scrcpy 提供 ~30 FPS 的视频流, 远快于 ADB screencap。
        需要安装 scrcpy (https://github.com/Genymobile/scrcpy)。
        """
        # 延迟导入 ScrcpyController
        try:
            from scrcpy_controller import ScrcpyController
        except ImportError:
            logger.error(
                "scrcpy_controller.py 未找到, 回退到 ADB screencap。"
                "请确保 scrcpy_controller.py 在项目目录中。"
            )
            self._scrcpy_ready = False
            return self._screencap_execout()

        if not hasattr(self, '_scrcpy_instance') or self._scrcpy_instance is None:
            self._scrcpy_instance = ScrcpyController(self.cfg)
            if not self._scrcpy_instance.start():
                logger.error("scrcpy 启动失败, 回退到 ADB screencap")
                self._scrcpy_instance = None
                self._scrcpy_ready = False
                return self._screencap_execout()
            self._scrcpy_ready = True

        frame = self._scrcpy_instance.get_frame()
        if frame is None:
            # 画面流中断: 尝试重启一次
            logger.warning("scrcpy 帧丢失, 尝试重启...")
            self.close_scrcpy()
            self._scrcpy_instance = None
            self._scrcpy_ready = False
            # 降级到 ADB
            return self._screencap_execout()
        return frame

    def close_scrcpy(self):
        """关闭 scrcpy 后端 (如果有启动)。"""
        if hasattr(self, '_scrcpy_instance') and self._scrcpy_instance:
            self._scrcpy_instance.stop()

    # ──────────────────────────────────────────
    # Minitouch 后端 (可选, <5ms 触摸延迟)
    # ──────────────────────────────────────────

    def init_minitouch(self) -> bool:
        """
        初始化 minitouch 后端。

        minitouch 是一个运行在安卓设备上的触摸守护进程,
        通过本地 socket 接收触摸命令, 延迟 <5ms (远快于 ADB input ~50ms)。

        使用方式:
          1. adb_controller.py 在启动时自动推送 minitouch 到设备
          2. 启动 minitouch 进程, 建立 socket 连接
          3. tap() / swipe() 等方法自动切换到 minitouch

        返回是否成功初始化。
        """
        self._minitouch_socket: Optional[socket.socket] = None
        self._minitouch_proc = None
        self._mt_ready = False  # 布尔标志替代 hasattr
        self._mt_max_contacts = 2
        self._mt_max_x = self.screen["width"]
        self._mt_max_y = self.screen["height"]

        # 缓存缩放因子 (避免每次除法)
        self._mt_scale_x = self._mt_max_x / self.screen["width"]
        self._mt_scale_y = self._mt_max_y / self.screen["height"]

        # minitouch 二进制文件路径
        mt_bin = self.cfg.get("minitouch", {}).get("binary_path", "")
        if not mt_bin:
            # 自动查找内置二进制
            import glob
            builtin = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "bin", "minitouch")
            # 尝试根据架构查找
            arch = self._get_device_arch()
            if arch:
                mt_bin = os.path.join(builtin, f"minitouch_{arch}")
            else:
                mt_bin = os.path.join(builtin, "minitouch")

        if not os.path.exists(mt_bin):
            logger.warning(f"minitouch 二进制不存在: {mt_bin}")
            logger.info("可从 https://github.com/DeviceFarmer/minitouch 下载")
            logger.info("或设置 adb.minitouch.binary_path")
            return False

        # 推送二进制到设备
        remote_path = "/data/local/tmp/minitouch"
        push_result = subprocess.run(
            self._adb_cmd("push", mt_bin, remote_path),
            capture_output=True, text=True, timeout=10
        )
        if push_result.returncode != 0:
            logger.warning(f"minitouch 推送失败: {push_result.stderr.strip()}")
            return False

        # 设置执行权限
        subprocess.run(
            self._adb_cmd("shell", "chmod", "755", remote_path),
            capture_output=True, timeout=5
        )

        # 启动 minitouch (后台进程)
        try:
            self._minitouch_proc = subprocess.Popen(
                self._adb_cmd("shell", remote_path),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except Exception as e:
            logger.warning(f"minitouch 启动失败: {e}")
            return False

        # 优化: 用轮询替代固定 sleep, 平均快 ~400ms
        # 检查 /proc/net/tcp 看 minitouch 是否开始监听
        for attempt in range(20):
            check = subprocess.run(
                self._adb_cmd("shell", "ls", "/proc/net/tcp"),
                capture_output=True, text=True, timeout=3
            )
            # minitouch 监听在 port 1111 (0x0457 in hex)
            if "0457" in check.stdout:
                break
            time.sleep(0.025)  # 25ms 间隔轮询
        else:
            # 最后尝试一次 + 短等待
            time.sleep(0.1)

        # 通过 ADB forward 建立本地 socket 连接
        # minitouch 默认监听 localhost:1111
        forward_result = subprocess.run(
            self._adb_cmd("forward", "tcp:1111", "tcp:1111"),
            capture_output=True, text=True, timeout=5
        )
        if forward_result.returncode != 0:
            logger.warning(f"ADB forward 失败: {forward_result.stderr.strip()}")
            self._cleanup_minitouch()
            return False

        # 连接 socket
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect(("127.0.0.1", 1111))

            # 读取 minitouch 协议版本信息
            # 格式: v <version> <max_contacts> <max_x> <max_y>
            welcome = b""
            while b"\n" not in welcome:
                try:
                    chunk = sock.recv(1024)
                    if not chunk:
                        break
                    welcome += chunk
                except socket.timeout:
                    break

            welcome_str = welcome.decode().strip()
            logger.info(f"minitouch 已连接: {welcome_str}")

            # 解析协议信息
            parts = welcome_str.split()
            if len(parts) >= 4 and parts[0] == "v":
                self._mt_max_contacts = int(parts[1])
                self._mt_max_x = int(parts[2])
                self._mt_max_y = int(parts[3])
                # 基于实际设备分辨率更新缩放因子
                self._mt_scale_x = self._mt_max_x / self.screen["width"]
                self._mt_scale_y = self._mt_max_y / self.screen["height"]

            self._minitouch_socket = sock
            self._mt_ready = True
            logger.info(f"minitouch 初始化成功 (延迟 <5ms, "
                        f"触点={self._mt_max_contacts}, "
                        f"分辨率={self._mt_max_x}x{self._mt_max_y})")
            return True

        except (socket.error, OSError) as e:
            logger.warning(f"minitouch socket 连接失败: {e}")
            self._cleanup_minitouch()
            return False

    def _get_device_arch(self) -> str:
        """获取设备 CPU 架构。"""
        try:
            result = subprocess.run(
                self._adb_cmd("shell", "getprop", "ro.product.cpu.abi"),
                capture_output=True, text=True, timeout=5
            )
            arch = result.stdout.strip()
            # 映射到 minitouch 二进制命名
            mapping = {
                "arm64-v8a": "arm64",
                "armeabi-v7a": "arm",
                "x86_64": "x86_64",
                "x86": "x86",
            }
            return mapping.get(arch, arch)
        except Exception:
            return ""

    def _mt_tap(self, x: int, y: int) -> bool:
        """通过 minitouch 发送点击事件。v5.2: 套接字故障自动降级。"""
        if not self._minitouch_socket:
            return self._mt_fallback_tap(x, y)
        try:
            scaled_x = int(x * self._mt_scale_x)
            scaled_y = int(y * self._mt_scale_y)
            cmd = f"d 0 {scaled_x} {scaled_y} 50\nc\nu 0\nc\n"
            self._minitouch_socket.sendall(cmd.encode())
            return True
        except (socket.error, OSError, BrokenPipeError) as e:
            logger.warning(f"minitouch tap 失败: {e}, 自动降级到 ADB input")
            self._mt_ready = False
            self._cleanup_minitouch()
            return self._mt_fallback_tap(x, y)

    def _mt_swipe(self, x1: int, y1: int, x2: int, y2: int,
                  duration_ms: int = 50) -> bool:
        """通过 minitouch 发送滑动事件。v5.2: 套接字故障自动降级。"""
        if not self._minitouch_socket:
            return self._mt_fallback_swipe(x1, y1, x2, y2, duration_ms)
        try:
            sx1 = int(x1 * self._mt_scale_x)
            sy1 = int(y1 * self._mt_scale_y)
            sx2 = int(x2 * self._mt_scale_x)
            sy2 = int(y2 * self._mt_scale_y)

            cmd = f"d 0 {sx1} {sy1} 50\nc\n"

            steps = max(int(duration_ms / 5), 1)
            for i in range(1, steps + 1):
                t = i / steps
                mx = int(sx1 + (sx2 - sx1) * t)
                my = int(sy1 + (sy2 - sy1) * t)
                cmd += f"m 0 {mx} {my} 50\nc\n"

            cmd += "u 0\nc\n"

            self._minitouch_socket.sendall(cmd.encode())
            time.sleep(duration_ms / 1000.0)
            return True
        except (socket.error, OSError, BrokenPipeError) as e:
            logger.warning(f"minitouch swipe 失败: {e}, 自动降级到 ADB input")
            self._mt_ready = False
            self._cleanup_minitouch()
            return self._mt_fallback_swipe(x1, y1, x2, y2, duration_ms)

    def _mt_press(self, x: int, y: int, duration_ms: int = 100) -> bool:
        """通过 minitouch 长按。v5.2: 套接字故障自动降级。"""
        if not self._minitouch_socket:
            return self._mt_fallback_press(x, y, duration_ms)
        try:
            sx = int(x * self._mt_scale_x)
            sy = int(y * self._mt_scale_y)
            cmd = f"d 0 {sx} {sy} 50\nc\n"
            self._minitouch_socket.sendall(cmd.encode())
            time.sleep(duration_ms / 1000.0)
            cmd = f"u 0\nc\n"
            self._minitouch_socket.sendall(cmd.encode())
            return True
        except (socket.error, OSError, BrokenPipeError) as e:
            logger.warning(f"minitouch press 失败: {e}, 自动降级到 ADB input")
            self._mt_ready = False
            self._cleanup_minitouch()
            return self._mt_fallback_press(x, y, duration_ms)

    def _mt_fallback_tap(self, x, y):
        """minitouch 不可用时的回退: 使用 ADB input tap。"""
        return self._adb_tap(x, y)

    def _mt_fallback_swipe(self, x1, y1, x2, y2, duration_ms):
        return self._adb_swipe(x1, y1, x2, y2, duration_ms)

    def _mt_fallback_press(self, x, y, duration_ms):
        return self._adb_swipe(x, y, x, y, duration_ms)

    def _cleanup_minitouch(self):
        """清理 minitouch 进程和 socket。"""
        if self._minitouch_socket:
            try:
                self._minitouch_socket.close()
            except Exception:
                pass
            self._minitouch_socket = None
        if self._minitouch_proc:
            try:
                self._minitouch_proc.terminate()
            except Exception:
                pass
            self._minitouch_proc = None
        self._mt_ready = False

    # ──────────────────────────────────────────
    # 触摸操作 (自动选择后端: minitouch > ADB)
    # ──────────────────────────────────────────

    # v5.2: 批量触摸缓存 — 在单帧内积累多个触摸操作,
    # 一次性发送 (减少 adb 进程启动次数, 提升吞吐量)
    _batched_touch_queue: list[str] = []
    _batch_enabled: bool = True
    _max_batch_size: int = 20

    def tap(self, x: int, y: int) -> bool:
        """在 (x, y) 位置点击。自动选择 minitouch 或 ADB。"""
        if self._mt_ready:
            return self._mt_tap(x, y)
        return self._adb_tap(x, y)

    def tap_batch(self, *coords: tuple[int, int]) -> bool:
        """
        批量点击: 一次性发送多个 tap 命令, 减少 adb 进程启动次数。
        比逐个 tap() 快 3-10x (节省 subprocess.Popen 开销)。

        Usage:
            adb.tap_batch((x1, y1), (x2, y2), (x3, y3))
        """
        if self._mt_ready:
            # minitouch 下逐个发送 (socket 已连接, 开销很小)
            ok = True
            for x, y in coords:
                if not self._mt_tap(x, y):
                    ok = False
            return ok

        if not coords:
            return True

        if len(coords) == 1:
            return self._adb_tap(coords[0][0], coords[0][1])

        # 构造批量 shell 命令: input tap x1 y1 && input tap x2 y2 && ...
        cmds = [f"input tap {int(x)} {int(y)}" for x, y in coords]
        shell_cmd = " && ".join(cmds)

        try:
            subprocess.run(
                self._adb_cmd("shell", shell_cmd),
                capture_output=True, timeout=10
            )
            return True
        except Exception as e:
            logger.warning(f"批量 tap 失败 ({len(coords)} taps): {e}")
            return False

    def flush_touch_batch(self) -> bool:
        """
        发送缓存的批量触摸命令并清空队列。
        用于帧结束时一次性发送所有积累的触摸操作。

        v5.6.1: 命令超长时自动分批发送，防止超出 shell 命令长度限制。
        """
        if not self._batched_touch_queue:
            return True

        queue = self._batched_touch_queue
        self._batched_touch_queue = []

        # 单条 shell 命令长度限制 (Windows: ~8191, Unix: ARG_MAX 通常 >128k)
        # 保守取 7600 字符, 超长自动分批
        MAX_SHELL_CMD_LEN = 7600
        batch = []
        batch_len = 0

        all_ok = True
        for cmd in queue:
            if batch_len + len(cmd) + 4 > MAX_SHELL_CMD_LEN and batch:
                if not self._send_touch_cmd(" && ".join(batch)):
                    all_ok = False
                batch = []
                batch_len = 0
            batch.append(cmd)
            batch_len += len(cmd) + 4  # " && " separator

        if batch:
            if not self._send_touch_cmd(" && ".join(batch)):
                all_ok = False

        return all_ok

    def _send_touch_cmd(self, cmd: str) -> bool:
        """发送单条 shell 命令。"""
        try:
            subprocess.run(
                self._adb_cmd("shell", cmd),
                capture_output=True, timeout=10
            )
            return True
        except Exception as e:
            logger.warning(f"批量触摸发送失败: {e}")
            return False

    def queue_tap(self, x: int, y: int) -> None:
        """
        将 tap 加入批量队列 (不与设备交互)。
        配合 flush_touch_batch() 使用, 在帧结束时一次性发送。
        """
        if self._mt_ready:
            self._mt_tap(x, y)  # minitouch 直接发送 (socket 低开销)
            return
        if len(self._batched_touch_queue) < self._max_batch_size:
            self._batched_touch_queue.append(f"input tap {int(x)} {int(y)}")

    def queue_swipe(self, x1: int, y1: int, x2: int, y2: int,
                    duration_ms: int = 50) -> None:
        """将 swipe 加入批量队列。"""
        if self._mt_ready:
            self._mt_swipe(x1, y1, x2, y2, duration_ms)
            return
        if len(self._batched_touch_queue) < self._max_batch_size:
            self._batched_touch_queue.append(
                f"input swipe {int(x1)} {int(y1)} {int(x2)} {int(y2)} {int(duration_ms)}"
            )

    def _adb_tap(self, x: int, y: int) -> bool:
        """在 (x, y) 位置点击。"""
        try:
            subprocess.run(
                self._adb_cmd("shell", "input", "tap", str(int(x)), str(int(y))),
                capture_output=True, timeout=5
            )
            return True
        except Exception as e:
            logger.warning(f"tap 失败 ({x}, {y}): {e}")
            return False

    def swipe(self, x1: int, y1: int, x2: int, y2: int,
              duration_ms: int = 50) -> bool:
        """从 (x1,y1) 滑动到 (x2,y2)。自动选择 minitouch 或 ADB。"""
        if self._mt_ready:
            return self._mt_swipe(x1, y1, x2, y2, duration_ms)
        return self._adb_swipe(x1, y1, x2, y2, duration_ms)

    def _adb_swipe(self, x1: int, y1: int, x2: int, y2: int,
              duration_ms: int = 50) -> bool:
        """从 (x1,y1) 滑动到 (x2,y2), 持续 duration_ms 毫秒。"""
        try:
            subprocess.run(
                self._adb_cmd(
                    "shell", "input", "swipe",
                    str(int(x1)), str(int(y1)),
                    str(int(x2)), str(int(y2)),
                    str(int(duration_ms))
                ),
                capture_output=True, timeout=5
            )
            return True
        except Exception as e:
            logger.warning(f"swipe 失败: {e}")
            return False

    def press(self, x: int, y: int, duration_ms: int = 100) -> bool:
        """长按 (x, y) 位置。自动选择 minitouch 或 ADB。"""
        if self._mt_ready:
            return self._mt_press(x, y, duration_ms)
        return self._adb_press(x, y, duration_ms)

    def _adb_press(self, x: int, y: int, duration_ms: int = 100) -> bool:
        """长按 (x, y) 位置, 持续 duration_ms 毫秒。"""
        return self.swipe(x, y, x, y, duration_ms)

    def flick_up(self, x: int, y: int,
                 distance: int = 150, duration_ms: int = 50) -> bool:
        """上划 (flick note)。"""
        return self.swipe(x, y, x, y - distance, duration_ms)

    def flick_down(self, x: int, y: int,
                   distance: int = 150, duration_ms: int = 50) -> bool:
        """下划。"""
        return self.swipe(x, y, x, y + distance, duration_ms)

    def flick_left(self, x: int, y: int,
                   distance: int = 150, duration_ms: int = 50) -> bool:
        """左划。"""
        return self.swipe(x, y, x - distance, y, duration_ms)

    def flick_right(self, x: int, y: int,
                    distance: int = 150, duration_ms: int = 50) -> bool:
        """右划。"""
        return self.swipe(x, y, x + distance, y, duration_ms)

    # ──────────────────────────────────────────
    # 延迟测量
    # ──────────────────────────────────────────

    def start_async_capture(self, target_fps: int = 30) -> bool:
        """
        启动异步截屏线程 (producer-consumer 模式)。

        后台线程持续截屏, 主线程通过 get_async_frame() 获取最新帧。
        相比同步 screencap() 可提升 30-50% 的帧率 (隐藏 ADB 调用延迟)。

        Usage:
            adb.start_async_capture(target_fps=30)
            while running:
                frame = adb.get_async_frame()  # 非阻塞, 总是获取最新帧
            adb.stop_async_capture()
        """
        if self._async_running:
            return True  # 已经启动

        self._async_running = True
        self._async_frame = None
        self._async_frame_count = 0
        self._async_last_time = time.time()
        self._async_fps = 0.0
        self._async_target_interval = 1.0 / max(1, target_fps)

        def _capture_loop():
            while self._async_running:
                loop_start = time.perf_counter()
                try:
                    frame = self.screencap()
                    if frame is not None:
                        with self._async_lock:
                            self._async_frame = frame
                            self._async_frame_count += 1
                            now = time.time()
                            dt = now - self._async_last_time
                            if dt >= 1.0:
                                self._async_fps = self._async_frame_count / dt
                                self._async_frame_count = 0
                                self._async_last_time = now
                except Exception:
                    pass

                elapsed = time.perf_counter() - loop_start
                sleep_time = self._async_target_interval - elapsed
                if sleep_time > 0:
                    time.sleep(sleep_time)

        self._async_thread = threading.Thread(
            target=_capture_loop,
            daemon=True,
            name="adb-async-capture"
        )
        self._async_thread.start()

        # 等待首帧
        for _ in range(50):
            with self._async_lock:
                if self._async_frame is not None:
                    logger.info(f"异步截屏线程已启动 (目标 {target_fps} FPS)")
                    return True
            time.sleep(0.02)

        logger.warning("异步截屏: 首帧超时")
        return True  # 继续运行, 让线程自行恢复

    def get_async_frame(self) -> Optional[np.ndarray]:
        """获取异步截取的最新帧 (非阻塞)。"""
        with self._async_lock:
            if self._async_frame is None:
                return None
            return self._async_frame.copy()

    def get_async_fps(self) -> float:
        """获取异步截屏的实际 FPS。"""
        with self._async_lock:
            return self._async_fps

    def stop_async_capture(self):
        """停止异步截屏线程。"""
        self._async_running = False
        if self._async_thread is not None:
            self._async_thread.join(timeout=2)
            self._async_thread = None
        logger.debug("异步截屏线程已停止")

    def measure_latency(self, samples: int = 5) -> dict:
        """
        测量 ADB 操作延迟。

        Returns:
            {
                "screencap_avg_ms": ...,
                "tap_avg_ms": ...,
                "total_avg_ms": ...,
            }
        """
        screencap_times = []
        tap_times = []

        for i in range(samples):
            t0 = time.perf_counter()
            frame = self.screencap()
            t1 = time.perf_counter()
            if frame is not None:
                screencap_times.append((t1 - t0) * 1000)

            cx, cy = self.screen["width"] // 2, self.screen["height"] // 2
            t2 = time.perf_counter()
            self.tap(cx, cy)
            t3 = time.perf_counter()
            tap_times.append((t3 - t2) * 1000)

            time.sleep(0.1)

        result = {}
        if screencap_times:
            result["screencap_avg_ms"] = sum(screencap_times) / len(screencap_times)
            result["screencap_min_ms"] = min(screencap_times)
            result["screencap_max_ms"] = max(screencap_times)
        if tap_times:
            result["tap_avg_ms"] = sum(tap_times) / len(tap_times)
            result["tap_min_ms"] = min(tap_times)
            result["tap_max_ms"] = max(tap_times)
        if screencap_times and tap_times:
            result["total_avg_ms"] = result["screencap_avg_ms"] + result["tap_avg_ms"]

        return result

    def close(self) -> None:
        """清理所有资源: scrcpy, minitouch, 异步截屏线程。"""
        try:
            self.stop_async_capture()
        except Exception:
            pass
        try:
            self.close_scrcpy()
        except Exception:
            pass
        try:
            self._cleanup_minitouch()
        except Exception:
            pass

    def __del__(self):
        """析构时自动清理资源。"""
        try:
            self.close()
        except Exception:
            pass
