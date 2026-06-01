"""
PJSK Auto Player — 模拟器管理模块 (v5.12.0+)

自动检测、管理 Android 模拟器实例。
受 ALAS Emulator 管理和 ichikas 模拟器集成启发。

支持的模拟器:
  - MuMu Player (macOS / Windows)
  - LDPlayer (Windows)
  - Android Emulator / AVD (跨平台)
  - BlueStacks (macOS / Windows)

用法:
    from controller.simulator import SimulatorManager

    mgr = SimulatorManager()
    emulators = mgr.detect()           # 自动检测已安装模拟器
    running = mgr.list_running()       # 列出运行中的实例
    mgr.start("MuMu")                  # 启动模拟器
    mgr.stop("MuMu")                   # 停止模拟器
"""

from __future__ import annotations

import logging
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("pjsk.controller.simulator")


# ── 数据结构 ────────────────────────────────────────────────────

@dataclass
class SimulatorInfo:
    """模拟器实例信息。"""

    name: str
    display_name: str = ""
    vendor: str = ""
    executable: str = ""
    process_name: str = ""
    adb_port: int = 0
    adb_serial: str = ""
    installed: bool = False
    running: bool = False
    config_dir: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def status(self) -> str:
        if self.running:
            return "running"
        if self.installed:
            return "stopped"
        return "not_installed"


# ── 已知模拟器定义 ──────────────────────────────────────────────

_SYSTEM = platform.system().lower()

# 各平台已知模拟器配置
_KNOWN_SIMULATORS: list[dict] = [
    # MuMu Player (macOS)
    {
        "name": "mumu",
        "display_name": "MuMu Player",
        "vendor": "NetEase",
        "executable": {
            "darwin": "/Applications/MuMuPlayer.app",
            "win32": "C:\\Program Files\\MuMu\\emulator\\nemu\\EmulatorShell\\NemuPlayer.exe",
        }.get(_SYSTEM, ""),
        "process_name": {
            "darwin": "MuMuPlayer",
            "win32": "NemuPlayer.exe",
        }.get(_SYSTEM, ""),
        "adb_port": 7555,
        "adb_serial": "127.0.0.1:7555",
        "config_dir": {
            "darwin": os.path.expanduser("~/Library/Application Support/MuMuPlayer"),
            "win32": os.path.expandvars("%APPDATA%\\MuMu\\emulator\\nemu"),
        }.get(_SYSTEM, ""),
    },
    # MuMu Player Pro (macOS, newer version)
    {
        "name": "mumu_pro",
        "display_name": "MuMu Player Pro",
        "vendor": "NetEase",
        "executable": {
            "darwin": "/Applications/MuMuPlayer Pro.app",
        }.get(_SYSTEM, ""),
        "process_name": {
            "darwin": "MuMuPlayer Pro",
        }.get(_SYSTEM, ""),
        "adb_port": 7555,
        "adb_serial": "127.0.0.1:7555",
    },
    # LDPlayer (Windows)
    {
        "name": "ldplayer",
        "display_name": "LDPlayer",
        "vendor": "XUANZHI",
        "executable": {
            "win32": "C:\\LDPlayer\\ldplayer9\\dnplayer.exe",
        }.get(_SYSTEM, ""),
        "process_name": {
            "win32": "dnplayer.exe",
        }.get(_SYSTEM, ""),
        "adb_port": 5555,
        "adb_serial": "127.0.0.1:5555",
    },
    # BlueStacks (macOS / Windows)
    {
        "name": "bluestacks",
        "display_name": "BlueStacks",
        "vendor": "BlueStacks",
        "executable": {
            "darwin": "/Applications/BlueStacks.app",
            "win32": "C:\\Program Files\\BlueStacks_nxt\\HD-Player.exe",
        }.get(_SYSTEM, ""),
        "process_name": {
            "darwin": "BlueStacks",
            "win32": "HD-Player.exe",
        }.get(_SYSTEM, ""),
        "adb_port": 5555,
        "adb_serial": "127.0.0.1:5555",
    },
]


# ── 管理器 ──────────────────────────────────────────────────────

class SimulatorManager:
    """模拟器管理器。

    自动检测已安装的模拟器，提供启停和 ADB 连接管理。
    """

    def __init__(self, adb_path: str = "adb"):
        self._adb_path = adb_path
        self._simulators: dict[str, SimulatorInfo] = {}
        self._detected = False

    # ── 检测 ─────────────────────────────────────────────────

    def detect(self, force: bool = False) -> list[SimulatorInfo]:
        """检测系统上所有已安装的模拟器。

        Args:
            force: 强制重新检测 (默认使用缓存)

        Returns:
            所有已知模拟器的信息列表
        """
        if self._detected and not force:
            return list(self._simulators.values())

        self._simulators = {}
        for entry in _KNOWN_SIMULATORS:
            info = SimulatorInfo(
                name=entry["name"],
                display_name=entry.get("display_name", entry["name"]),
                vendor=entry.get("vendor", ""),
                executable=entry.get("executable", ""),
                process_name=entry.get("process_name", ""),
                adb_port=entry.get("adb_port", 0),
                adb_serial=entry.get("adb_serial", ""),
                config_dir=entry.get("config_dir", ""),
                extra=entry.get("extra", {}),
            )
            # Check if installed
            info.installed = self._check_installed(info)
            # Check if running
            info.running = self._check_running(info)
            self._simulators[info.name] = info

        self._detected = True
        logger.info(
            "Detected %d simulators: %s",
            len([s for s in self._simulators.values() if s.installed]),
            ", ".join(
                s.display_name for s in self._simulators.values() if s.installed
            ),
        )
        return list(self._simulators.values())

    def _check_installed(self, info: SimulatorInfo) -> bool:
        """检查模拟器是否已安装。"""
        if not info.executable:
            return False
        if _SYSTEM == "darwin":
            return os.path.isdir(info.executable) or os.path.isfile(info.executable)
        return os.path.exists(info.executable)

    def _check_running(self, info: SimulatorInfo) -> bool:
        """检查模拟器进程是否在运行。"""
        if not info.process_name:
            # Fallback: try ADB connect
            if info.adb_serial:
                return self._adb_ping(info.adb_serial)
            return False

        try:
            if _SYSTEM == "darwin":
                result = subprocess.run(
                    ["pgrep", "-x", info.process_name],
                    capture_output=True, timeout=5,
                )
                return result.returncode == 0
            elif _SYSTEM == "win32":
                result = subprocess.run(
                    ["tasklist", "/FI", f"IMAGENAME eq {info.process_name}"],
                    capture_output=True, timeout=5, shell=True,
                )
                return info.process_name.lower() in result.stdout.decode().lower()
        except Exception:
            pass
        return False

    # ── ADB ──────────────────────────────────────────────────

    def _adb_ping(self, serial: str) -> bool:
        """通过 ADB 检查设备是否可达。"""
        try:
            result = subprocess.run(
                [self._adb_path, "-s", serial, "shell", "echo", "ok"],
                capture_output=True, timeout=5,
            )
            return result.returncode == 0 and b"ok" in result.stdout
        except Exception:
            return False

    def adb_devices(self) -> list[str]:
        """列出所有 ADB 连接的设备序列号。"""
        try:
            result = subprocess.run(
                [self._adb_path, "devices"],
                capture_output=True, timeout=5, text=True,
            )
            devices = []
            for line in result.stdout.strip().split("\n")[1:]:
                if "\tdevice" in line:
                    devices.append(line.split("\t")[0])
            return devices
        except Exception:
            return []

    # ── 控制 ─────────────────────────────────────────────────

    def start(self, name: str) -> bool:
        """启动指定模拟器。

        Args:
            name: 模拟器名称 (如 'mumu', 'ldplayer')

        Returns:
            启动成功返回 True
        """
        info = self._simulators.get(name)
        if not info:
            info = self._find_by_name(name)
        if not info:
            logger.warning("Simulator '%s' not found", name)
            return False

        if info.running:
            logger.info("Simulator '%s' is already running", info.display_name)
            return True

        if not info.installed:
            logger.warning("Simulator '%s' is not installed", info.display_name)
            return False

        if not info.executable:
            logger.warning("No executable path for simulator '%s'", info.display_name)
            return False

        try:
            logger.info("Starting %s: %s", info.display_name, info.executable)
            if _SYSTEM == "darwin":
                subprocess.Popen(
                    ["open", "-a", info.executable],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            elif _SYSTEM == "win32":
                subprocess.Popen(
                    [info.executable],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            info.running = True
            logger.info("Started %s", info.display_name)
            return True
        except Exception as e:
            logger.error("Failed to start %s: %s", info.display_name, e)
            return False

    def stop(self, name: str) -> bool:
        """停止指定模拟器。

        Args:
            name: 模拟器名称

        Returns:
            停止成功返回 True
        """
        info = self._simulators.get(name)
        if not info:
            info = self._find_by_name(name)
        if not info:
            logger.warning("Simulator '%s' not found", name)
            return False

        if not info.running:
            logger.info("Simulator '%s' is not running", info.display_name)
            return True

        try:
            logger.info("Stopping %s", info.display_name)
            if info.process_name:
                if _SYSTEM == "darwin":
                    subprocess.run(
                        ["pkill", "-x", info.process_name],
                        capture_output=True, timeout=10,
                    )
                elif _SYSTEM == "win32":
                    subprocess.run(
                        ["taskkill", "/F", "/IM", info.process_name],
                        capture_output=True, timeout=10,
                    )
            info.running = False
            logger.info("Stopped %s", info.display_name)
            return True
        except Exception as e:
            logger.error("Failed to stop %s: %s", info.display_name, e)
            return False

    def connect_adb(self, name: str) -> bool:
        """通过 ADB 连接到指定模拟器。

        Args:
            name: 模拟器名称

        Returns:
            连接成功返回 True
        """
        info = self._simulators.get(name)
        if not info:
            info = self._find_by_name(name)
        if not info:
            return False

        if not info.adb_serial:
            logger.warning("No ADB serial for '%s'", name)
            return False

        if self._adb_ping(info.adb_serial):
            logger.info("Already connected to %s (%s)", name, info.adb_serial)
            return True

        try:
            logger.info("Connecting ADB to %s (%s)...", name, info.adb_serial)
            result = subprocess.run(
                [self._adb_path, "connect", info.adb_serial],
                capture_output=True, timeout=5, text=True,
            )
            if "connected" in result.stdout.lower() or result.returncode == 0:
                logger.info("Connected to %s", info.adb_serial)
                return True
            else:
                logger.warning("Failed to connect: %s", result.stdout.strip())
                return False
        except Exception as e:
            logger.error("ADB connect error: %s", e)
            return False

    def list_running(self) -> list[SimulatorInfo]:
        """列出所有运行中的模拟器。"""
        if not self._detected:
            self.detect()
        return [s for s in self._simulators.values() if s.running]

    def list_installed(self) -> list[SimulatorInfo]:
        """列出所有已安装的模拟器。"""
        if not self._detected:
            self.detect()
        return [s for s in self._simulators.values() if s.installed]

    def list_all(self) -> list[SimulatorInfo]:
        """列出所有已知模拟器。"""
        if not self._detected:
            self.detect()
        return list(self._simulators.values())

    def to_dict(self) -> list[dict]:
        """导出所有模拟器信息为可序列化字典。"""
        result = []
        for info in self.list_all():
            result.append({
                "name": info.name,
                "display_name": info.display_name,
                "vendor": info.vendor,
                "installed": info.installed,
                "running": info.running,
                "status": info.status,
                "executable": info.executable,
                "adb_serial": info.adb_serial,
                "adb_port": info.adb_port,
            })
        return result

    # ── 辅助 ─────────────────────────────────────────────────

    def _find_by_name(self, name: str) -> Optional[SimulatorInfo]:
        """按名称或显示名称查找模拟器。"""
        for info in self._simulators.values():
            if info.name == name or info.display_name == name:
                return info
        return None


# ── 全局实例 ────────────────────────────────────────────────────

_mgr: Optional[SimulatorManager] = None


def get_simulator_manager(adb_path: str = "adb") -> SimulatorManager:
    """获取全局 SimulatorManager 实例。"""
    global _mgr
    if _mgr is None:
        _mgr = SimulatorManager(adb_path=adb_path)
    return _mgr
