# PJSK Auto Player — 一站式傻瓜版游戏助手 VISION

> 基于 MAA/ALAS/MaaFramework 设计理念的全面重构计划
> 当前版本: v5.12.0 | 更新日期: 2026-06-01

---

## 🎯 总体目标

从"自动执行工具"升级为 **一站式 Project Sekai 游戏助手**：
- **傻瓜化**：插上手机 → 运行 → 自动执行，零配置
- **全功能**：选歌/执行/连续执行/活动熔于一炉
- **可视化**：现代 Web 控制面板，实时监控一切
- **可靠**：分级异常处理 + 自动恢复，7x24 不崩溃

---

## 📐 架构蓝图

```
┌─────────────────────────────────────────────────┐
│                 前端层 (Web GUI)                   │
│  现代暗色仪表盘 · 实时帧预览 · 配置编辑 · 统计     │
├─────────────────────────────────────────────────┤
│                 CLI / 守护进程层                    │
│  daemon 模式 · 命令行操控 · JSON 输出 · 热键      │
├─────────────────────────────────────────────────┤
│                Agent 扩展层 (Python)               │
│  CustomRecognition · CustomAction · AI 模型      │
├─────────────────────────────────────────────────┤
│              任务调度层 (Pipeline V2 + DSL)        │
│  任务继承 (@语法) · 生命周期钩子 · 插件系统        │
│  🆕 DSL 声明式任务 (@task 装饰器)                  │
├──────────┬──────────┬──────────┬────────────────┤
│ 场景检测   │ 识别引擎  │ 触控引擎   │ 状态管理      │
│ SceneCls. │ Vision   │ Controller│ Status        │
│ (多算法)   │ (OCR/TM  │ (ADB/     │ (运行时状态    │
│           │  /Color) │ scrcpy/   │  /统计/计时)  │
│           │          │ minitouch)│              │
├──────────┴──────────┴──────────┴────────────────┤
│                  配置层 (Config V2.1)             │
│  分层: 默认 < profile < 运行时 · 热加载 · YAML    │
│  🆕 Pydantic 严格校验                             │
├─────────────────────────────────────────────────┤
│              模拟器管理层 (Simulator)              │
│  🆕 MuMu/LDPlayer/BlueStacks 自动检测 + 启停     │
├─────────────────────────────────────────────────┤
│                  异常体系 (Exception)              │
│  GameStuckError · GameBugError · 自动恢复 · 截图  │
└─────────────────────────────────────────────────┘
```

---

## 🧱 模块设计

### 1. 配置系统 V2.1 (`config/`)
- `config/default.yaml` — 默认配置（内置，只读）
- `config/profiles/<name>.yaml` — 用户配置档案
- `config/local.yaml` — 本地覆盖（不提交 git）
- `config/models.py` 🆕 — Pydantic v2 严格校验模型 (14 个 BaseModel)
- `config/schema.py` — JSON Schema + Pydantic 双引擎校验
- **热加载**：修改文件后自动重载（`ConfigWatcher` 模式）
- **分层覆盖**：默认 → profile → 局部 → 运行时

### 2. Pipeline V2 + DSL (`pipeline/`)
从当前 `pipeline.py` 升级为完整模块：
- `pipeline/base.py` — AbstractTask / PackageTask / InterfaceTask
- `pipeline/process.py` — ProcessTask 执行引擎
- `pipeline/plugins.py` — AbstractTaskPlugin + 内置插件
- `pipeline/task_data.py` — JSON 加载 + @继承解析
- `pipeline/scheduler.py` — 任务调度器（按时间/状态）
- `pipeline/node.py` — 节点生命周期
- `pipeline/dsl.py` 🆕 — DSL 声明式任务定义 (@task 装饰器)

### 3. 识别引擎 V2 (`vision/`)
- `vision/matcher.py` — OpenCV 模板匹配
- `vision/ocr.py` — OCR 识别
- `vision/color.py` — 颜色检测
- `vision/scene.py` — 场景分类器（多算法投票）
- `vision/button.py` — UI 元素声明式定义

### 4. 场景检测 V2 (`scene/`)
ALAS 启发式场景分类，多算法投票：
- `scene/classifier.py` — 主分类器
- `scene/states.py` — 场景状态机定义
- `scene/transitions.py` — 场景转换检测

### 5. 异常体系 (`exceptions.py`)
ALAS 式分级异常 + 自动恢复，11 种异常类型 + 8 种恢复策略。

### 6. 控制器 V2 + 模拟器管理 (`controller/`)
- `controller/base.py` — `BaseController` 抽象类
- `controller/adb.py` — ADB 截图 + 点击
- `controller/scrcpy.py` — scrcpy 视频流 + minitouch
- `controller/combined.py` — 智能路由 + Benchmark 引擎 🆕
- `controller/simulator.py` 🆕 — MuMu/LDPlayer/BlueStacks 模拟器管理

### 7. Web GUI V2 (`web/`)
- 暗色/亮色双主题
- 实时帧预览 (SSE 推送)
- FPS/点击量实时折线图
- 配置在线编辑 + 日志查看器
- 🆕 Benchmark 后端性能面板 (v5.10.0)
- 📱 PWA 手机控制面板 (v5.1.0)

### 8. 设置向导 + 通知 + 守护进程
- `wizard/setup.py` — 5 步傻瓜式设置
- `notification/` — macOS/Windows 桌面通知
- `cli.py` — daemon 模式 + Unix Socket

---

## 📋 实施路线 (已完成)

| 阶段 | 内容 | 版本 | 状态 |
|------|------|------|------|
| Phase 1 | 新目录结构 + 配置系统 V2 + 异常体系 + CLI | v4.9.0 | ✅ |
| Phase 2 | Pipeline V2 (@继承 + 生命周期 + 插件) | v4.9.0 | ✅ |
| Phase 3 | 场景检测 V2 + 识别引擎 V2 | v4.9.0 | ✅ |
| Phase 4 | Web GUI V2 (一站式控制面板) | v4.9.0 | ✅ |
| Phase 5 | 设置向导 V2 + 通知系统 | v4.9.0 | ✅ |
| Phase 6 | 文档 + 测试 + 打包 | v4.9.0 | ✅ |
| Phase 7 | Bugfix + 接口统一 + 恢复策略 | v4.9.1 | ✅ |
| Phase 8 | ALAS 工具库 (cached_property/Resource/Benchmark/Schema) | v4.10.0 | ✅ |
| Phase 9 | 开箱即用桌面体验 (双击启动/自动浏览器/系统托盘) | v4.11.0 | ✅ |
| Phase 10 | i18n 国际化 (中/英/日) + PWA | v5.1.0 | ✅ |
| Phase 11 | Pydantic 配置校验 (Config V2.1) | v5.8.0 | ✅ |
| Phase 12 | CI/CD 完善 (build.spec 同步 + SHA256 checksums) | v5.9.0 | ✅ |
| Phase 13 | Benchmark 面板 (Web 后端性能对比) | v5.10.0 | ✅ |
| Phase 14 | Pipeline DSL 原型 (@task 装饰器) | v5.11.0 | ✅ |
| Phase 15 | 模拟器管理 (MuMu/LDPlayer/BlueStacks) | v5.12.0 | ✅ |

---

## 🚀 未来发展方向

### P0 — 质量与可靠性
- [ ] **单元测试增强** — pytest 覆盖率从 ~40% 提升到 80%+
- [ ] **集成测试框架** — mock ADB 设备的自动化测试
- [ ] **错误遥测** — 崩溃自动上报 + 分析面板

### P1 — 功能增强
- [ ] **AI 音符识别** — 轻量 ONNX 模型替代传统 CV，提高弱光/特效场景识别率
- [ ] **执行回放分析** — 录屏 + 判定时间线可视化，分析每次判定时机
- [ ] **自动特殊任务** — 检测当前活动类型 → 自动选歌 → 循环连续执行
- [ ] **原生 Qt 桌面 GUI** — 从 tkinter 迁移到 PySide6/QML
- [ ] **多服 UI 适配** — JP/TW/CN/KR/EN 不同 UI 自动适配

### P2 — 工程化
- [ ] **Prefab 资源系统** — 模板图片自动生成代码引用（KotoneBot 启发）
- [ ] **声明式任务注册表** — Registry 模式，CLI/GUI 自动发现 DSL 任务
- [ ] **Pydantic 配置校验** — CLI `pjsk config validate --pydantic` 命令
- [ ] **CI/CD 自动构建增强** — Windows 签名 + macOS 公证

### P3 — 社区与生态
- [ ] **插件市场** — 社区贡献的任务包/算法插件
- [ ] **任务热更新** — CDN 下发 JSON 任务配置，无需发版
- [ ] **多语言完善** — 繁体中文、韩语、法语社区翻译

---

## 📚 同类开源项目调研 (2026-05-29)

> 调研 GitHub 上 Project Sekai / 音游自动化 / CV 游戏辅助相关的开源项目，
> 学习社区中优秀的工程实践，取长补短。

### 项目详情

#### 1. ichikas-auto-assistant (⭐36, GPLv3, Python)
- **定位**: PJSK 日常任务全自动化 (登录/商店/任务/CM/区域对话/LIVE)
- **框架**: 基于自研 KotoneBot (⭐4)
- **GUI**: PySide6 + QML 原生桌面, DSL 自动生成配置表单
- **识别**: KotoneBot 内置 OpenCV + RapidOCR, Prefab 模板图片代码生成
- **控制器**: MuMu IPC / ADB / uiautomator / scrcpy 四通道
- **任务系统**: 声明式 DSL (@action, @sleep, @ocr), Registry 注册表
- **配置**: Pydantic 模型严格校验, 多 Profile
- **可学习**: 原生桌面 GUI (PySide6/QML), DSL 任务系统, Pydantic 配置校验, 模拟器 IPC 通信

#### 2. MaaFramework (⭐4.1k, AGPLv3, C++/Python)
- **定位**: 通用 CV 自动化框架 (MAA 的泛化版本)
- **生态**: MaaNTE (异环, ⭐1.6k), MFABD2 (棕色尘埃2, ⭐394) 等
- **架构**: Controller-Resource-Agent 三层 + Pipeline JSON
- **可学习**: i18n 国际化, CI/CD 自动构建, 任务热更新, 社区运营

#### 3. KotoneBot (⭐4, GPLv3, Python)
- **定位**: 轻量 CV 自动化框架 (ichikas 的底层引擎)
- **特性**: 声明式 DSL, 平台无关 IO, Prefab 资源系统, 模拟器管理
- **识别 API**: find()/ocr()/color()
- **可学习**: DSL 语法设计, Prefab 图片代码生成, 模拟器管理

### 能力矩阵 (v5.12 对比)

| 能力维度 | 本项目 v5.12 | ichikas | MaaFW | ALAS |
|---------|-------------|---------|-------|------|
| 真自动执行 | ✅ 预测引擎 | ❌ 仅 AUTO | N/A | N/A |
| Pipeline 任务引擎 | ✅ V2 @继承 + DSL | ⚠️ DSL | ✅ JSON | ❌ |
| 多算法场景检测 | ✅ 投票 | ⚠️ find() | ✅ | ✅ |
| 分级异常恢复 | ✅ 11种 | ⚠️ | ❌ | ✅ |
| 原生桌面 GUI | ⚠️ tkinter | ✅ QML | ⚠️ WPF | ✅ Qt |
| Web 控制面板 | ✅ SSE + Benchmark | ❌ | ❌ | ✅ Flask |
| 声明式任务 DSL | ✅ @task 装饰器 | ✅ @action | ❌ | ❌ |
| 配置校验 | ✅ Pydantic + Schema | ✅ Pydantic | ❌ | ✅ Schema |
| i18n 国际化 | ✅ 中/英/日 | ⚠️ JP/TW/CN | ✅ | ❌ |
| PWA 手机控制 | ✅ | ❌ | ❌ | ❌ |
| CI/CD 自动构建 | ✅ 3 平台 | ✅ | ✅ | ❌ |
| 模拟器管理 | ✅ MuMu/LD/BS | ✅ MuMu | ✅ | ✅ |
| Prefab 资源系统 | ❌ | ✅ | ❌ | ✅ Resource |
| 单元测试 | ⚠️ ~40% | ❌ | ⚠️ | ✅ |

### 特色对比 (v5.12 新增)

| 特性 | 本项目 | MAA | ALAS |
|------|--------|-----|------|
| Pipeline JSON + @继承 | ✅ | ✅ | ❌ |
| DSL 声明式任务 | ✅ 🆕 | ❌ | ❌ |
| 插件系统 (AOP) | ✅ | ✅ | ❌ |
| 分级异常 + 恢复 | ✅ 11 种 | ❌ | ✅ |
| 配置 Pydantic 校验 | ✅ 🆕 | ❌ | ❌ |
| Web Benchmark 面板 | ✅ 🆕 | ❌ | ❌ |
| 模拟器自动管理 | ✅ 🆕 | ❌ | ✅ |
| SHA256 发布校验 | ✅ 🆕 | ❌ | ❌ |
| CI/CD 三平台构建 | ✅ | ✅ | ❌ |
| PWA 手机控制 | ✅ | ❌ | ❌ |
