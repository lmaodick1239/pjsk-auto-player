# Changelog

所有 notable 变更均记录在此文件。

格式基于 [Keep a Changelog](https://keepachangelog.com/),
版本号遵循 [Semantic Versioning](https://semver.org/).

## [4.3.0] - 2026-05-29

- **打歌模式系统**: AP (All Perfect) / FC (Full Combo) / LIVE (通关保底) 三种预设
- **冲榜模式浮动**: 每首歌自动随机切换模式 (默认 70% FC + 25% AP + 5% LIVE)
- **Per-lane 独立随机化**: 每个轨道独立取随机偏移, 不再是全局统一抖动
- **`_lane_to_x` 性能缓存**: 避免每帧重算轨道坐标
- **CLI `--mode` 参数**: `python main.py start --mode AP` 指定打歌模式
- **热键 M**: 运行时循环切换模式 (AP → FC → LIVE)
- **Web 仪表盘**: 打歌模式下拉选择器
- **config.yaml**: 新增 `batch_play.mode_weights` 配置

## [3.5.0] - 2026-05-28

- v3.5.0: Windows hotkeys + --version + config validation + web dashboard fix

## [3.4.0] - 2026-05-28

- v3.4.0: Interactive setup wizard + auto-reconnect

## [3.3.0] - 2026-05-28

- v3.3.0: ALAS-style scene classifier + scrcpy PPM 30-60 FPS

## [3.2.0] - 2026-05-28

- v3.2.0: PyInstaller build + GitHub Actions CI + Web dashboard

## [3.1.0] - 2026-05-28

- v3.1.0: Minitouch backend + OCR score reader + Pipeline sub-tasks

## [3.0.0] - 2026-05-28

- v3.0.0: MAA-inspired pipeline engine + JSON task definitions

## [2.0.0] - 2026-05-28

- v2.0.0: Batch play (冲榜) - auto-repeat songs, result screen navigation, session stats

## [1.0.0] - 2026-05-28

- Major upgrade: prediction engine + hotkeys + auto-save calibration + profiles + scrcpy backend

