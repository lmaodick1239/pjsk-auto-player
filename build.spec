# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 打包配置 —— 将 PJSK Auto Player 打包为单文件可执行。

用法:
    pip install pyinstaller
    pyinstaller build.spec

包含 v4.11.0 模块:
    config/ controller/ pipeline/ scene/ vision/ web/ wizard/ notification/ handlers/ lib/ desktop_app
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent.absolute()

# 预下载 minitouch 二进制
minitouch_dir = ROOT / "bin" / "minitouch"
if not any(minitouch_dir.iterdir()) if minitouch_dir.exists() else True:
    import subprocess
    download_script = ROOT / "scripts" / "download_minitouch.sh"
    if download_script.exists():
        print("📥 Pre-downloading minitouch binaries...")
        subprocess.run(["bash", str(download_script)], cwd=str(ROOT))

# 收集数据文件
datas = [
    (str(ROOT / "tasks"), "tasks"),
    (str(ROOT / "templates"), "templates"),
    (str(ROOT / "bin"), "bin"),
    (str(ROOT / "config" / "default.yaml"), "config"),
    (str(ROOT / "resource"), "resource"),
    (str(ROOT / "web" / "dashboard.html"), "web"),
    (str(ROOT / "README.md"), "."),
    (str(ROOT / "TERMS.md"), "."),
    (str(ROOT / "CHANGELOG.md"), "."),
    (str(ROOT / "VERSION"), "."),
]

# 所有隐式导入（v4.11.0 模块）
hiddenimports = [
    # 核心依赖
    "cv2", "numpy", "yaml",
    # 旧模块
    "pipeline", "adb_controller", "screen_analyzer",
    "auto_play", "ocr_reader", "web_dashboard",
    "scene_classifier", "capture_optimizer", "setup_wizard",
    "scrcpy_controller", "combo_player", "team_builder",
    # v4.9.0+ 新模块
    "app", "cli", "exceptions", "desktop_app",
    "config", "config.schema",
    "controller", "controller.base", "controller.adb",
    "controller.scrcpy", "controller.combined",
    "pipeline.base", "pipeline.process", "pipeline.node",
    "pipeline.plugins", "pipeline.task_data", "pipeline.scheduler",
    "pipeline.timer",
    "scene.classifier", "scene.states", "scene.transitions",
    "vision.matcher", "vision.ocr", "vision.color", "vision.scene",
    "vision.button",
    "web.app", "web.websocket",
    "wizard.setup",
    "notification.desktop", "notification.web",
    "handlers", "handlers.goto_game", "handlers.handle_result",
    # v4.10.0+ 工具库
    "lib", "lib.decorators", "lib.resource",
    # v5.8.0+ Pydantic 配置模型
    "pydantic", "config.models",
]

excludes = [
    "tkinter", "matplotlib", "scipy", "PIL", "easyocr",
    "pytesseract", "tensorflow", "torch", "pandas",
    "notebook", "IPython", "jupyter",
]

block_cipher = None

a = Analysis(
    ["main.py"],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

app = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="pjsk-auto-player",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    app,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="pjsk-auto-player",
)
