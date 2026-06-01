"""
PJSK Auto Player — Pydantic 配置模型 (Config V2.1)

用 Pydantic v2 严格定义所有配置节，提供:
  - 启动时类型校验 + 范围约束 (Field ge/le)
  - IDE 自动补全和类型检查
  - model_dump() / model_validate() 序列化
  - 与现有 dict-based ConfigLoader 完全兼容

用法:
    from config.models import PjskConfig
    cfg = PjskConfig.model_validate(some_dict)  # 严格校验
    cfg_dict = cfg.model_dump()                 # 转回 dict
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ── ADB 配置 ────────────────────────────────────────────────────

class AdbConfig(BaseModel):
    """ADB 连接配置。"""

    executable: str = Field("adb", description="ADB 可执行文件路径")
    device_serial: str = Field("", description="设备序列号 (空则自动检测)")
    screencap_method: Literal["auto", "exec-out", "file", "scrcpy"] = Field(
        "auto", description="截图方法"
    )
    temp_dir: str = Field("/sdcard/", description="截图临时目录")
    auto_connect: bool = Field(True, description="启动时自动连接设备")
    reconnect_delay: float = Field(2.0, ge=0.1, description="重连延迟 (秒)")
    max_reconnect_attempts: int = Field(30, ge=1, description="最大重连次数")


# ── scrcpy 配置 ─────────────────────────────────────────────────

class ScrcpyConfig(BaseModel):
    """scrcpy 视频流后端配置。"""

    executable: str = Field("scrcpy", description="scrcpy 路径")
    max_fps: int = Field(60, ge=1, le=120, description="最大帧率")
    bit_rate: int = Field(12_000_000, ge=1_000_000, description="视频码率 (bps)")
    scale: float = Field(0.5, ge=0.1, le=1.0, description="缩放比例")
    frame_skip: bool = Field(True, description="允许跳帧")
    auto_install: bool = Field(True, description="自动安装 minitouch")


# ── minitouch 配置 ──────────────────────────────────────────────

class MinitouchConfig(BaseModel):
    """minitouch 触摸注入配置。"""

    auto_push: bool = Field(True, description="自动推送 minitouch 到设备")
    binary_path: str = Field("bin/minitouch", description="本地 minitouch 路径")
    port: int = Field(1111, ge=1024, le=65535, description="minitouch 端口")


# ── 屏幕配置 ────────────────────────────────────────────────────

class ScreenConfig(BaseModel):
    """屏幕参数配置。"""

    width: int = Field(1080, ge=1, description="屏幕宽度 (px)")
    height: int = Field(2400, ge=1, description="屏幕高度 (px)")
    judgment_line_y: float = Field(0.78, ge=0.0, le=1.0, description="判定线 Y 坐标 (相对)")
    detection_top_ratio: float = Field(0.35, ge=0.0, le=1.0, description="检测区域上边界 (相对)")
    lane_count: int = Field(5, ge=1, le=10, description="轨道数")
    lane_start_ratio: float = Field(0.05, ge=0.0, le=1.0, description="轨道起始 X (左, 相对)")
    lane_end_ratio: float = Field(0.95, ge=0.0, le=1.0, description="轨道结束 X (右, 相对)")

    @field_validator("lane_end_ratio")
    @classmethod
    def lanes_must_be_ordered(cls, v, info):
        start = info.data.get("lane_start_ratio")
        if start is not None and v <= start:
            raise ValueError(
                f"lane_end_ratio ({v}) 必须大于 lane_start_ratio ({start})"
            )
        return v

    @field_validator("detection_top_ratio")
    @classmethod
    def detection_above_judgment(cls, v, info):
        line = info.data.get("judgment_line_y")
        if line is not None and v >= line:
            raise ValueError(
                f"detection_top_ratio ({v}) 必须在 judgment_line_y ({line}) 之上"
            )
        return v


# ── 执行配置 ────────────────────────────────────────────────────

class PlayConfig(BaseModel):
    """自动化执行参数。"""

    mode: Literal["ap", "fc", "live", "auto", "safe", "precision"] = Field(
        "live", description="执行模式"
    )
    infinite: bool = Field(False, description="无限循环执行")
    combo_songs: list[str] = Field(default_factory=list, description="连击歌曲列表")
    randomize_clicks: bool = Field(True, description="操作随机化")
    jitter_ms: int = Field(15, ge=0, le=200, description="时机抖动 (ms)")
    position_jitter_px: int = Field(5, ge=0, le=50, description="坐标抖动 (px)")
    miss_rate: float = Field(0.001, ge=0.0, le=0.2, description="随机漏键率")
    hold_jitter_ms: int = Field(30, ge=0, le=200, description="长按微动 (ms)")
    result_click_delay_min: float = Field(0.5, ge=0.0, description="结算点击最小延迟 (s)")
    result_click_delay_max: float = Field(2.0, ge=0.0, description="结算点击最大延迟 (s)")

    @field_validator("result_click_delay_max")
    @classmethod
    def delay_range_valid(cls, v, info):
        dmin = info.data.get("result_click_delay_min")
        if dmin is not None and v < dmin:
            raise ValueError(
                f"result_click_delay_max ({v}) 不能小于 result_click_delay_min ({dmin})"
            )
        return v


# ── PID 配置 ────────────────────────────────────────────────────

class PidConfig(BaseModel):
    """PID 自适应延迟补偿。"""

    enabled: bool = Field(True, description="启用 PID")
    kp: float = Field(0.3, ge=0.0, le=10.0, description="比例系数")
    ki: float = Field(0.05, ge=0.0, le=10.0, description="积分系数")
    kd: float = Field(0.1, ge=0.0, le=10.0, description="微分系数")
    auto_tune: bool = Field(True, description="自动整定")
    samples_per_song: int = Field(50, ge=10, le=500, description="每首歌采样数")


# ── Pipeline 配置 ───────────────────────────────────────────────

class PipelineConfig(BaseModel):
    """Pipeline V2 任务引擎配置。"""

    task_timeout: int = Field(300, ge=1, description="任务超时 (秒)")
    default_retry_times: int = Field(5, ge=0, description="默认重试次数")
    screenshot_interval: float = Field(0.1, ge=0.01, le=5.0, description="截图间隔 (秒)")


# ── 场景检测配置 ────────────────────────────────────────────────

class SceneConfig(BaseModel):
    """场景检测参数。"""

    detection_interval: float = Field(0.05, ge=0.01, le=5.0, description="检测间隔 (秒)")
    stuck_threshold: int = Field(15, ge=3, description="卡住判定帧数")
    confidence_threshold: float = Field(0.85, ge=0.5, le=1.0, description="置信度阈值")
    algorithms: list[str] = Field(
        default_factory=lambda: ["template", "brightness", "color"],
        description="启用的检测算法",
    )


# ── Web 配置 ────────────────────────────────────────────────────

class WebConfig(BaseModel):
    """Web 控制面板配置。"""

    enabled: bool = Field(True, description="启用 Web 面板")
    port: int = Field(8080, ge=1, le=65535, description="监听端口")
    host: str = Field("0.0.0.0", description="监听地址")
    dark_mode: bool = Field(True, description="暗色模式")
    auto_open_browser: bool = Field(False, description="启动时自动打开浏览器")


# ── 通知配置 ────────────────────────────────────────────────────

class NotificationConfig(BaseModel):
    """桌面通知配置。"""

    desktop: bool = Field(True, description="桌面通知")
    sound: bool = Field(True, description="完成音效")
    on_complete: bool = Field(True, description="执行完成时通知")
    on_error: bool = Field(True, description="出错时通知")


# ── 日志配置 ────────────────────────────────────────────────────

class LoggingConfig(BaseModel):
    """日志配置。"""

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        "INFO", description="日志级别"
    )
    file: str = Field("logs/pjsk.log", description="日志文件路径")
    max_bytes: int = Field(10_485_760, ge=1024, description="单文件最大字节")
    backup_count: int = Field(5, ge=1, le=100, description="备份文件数")
    save_screenshots_on_error: bool = Field(True, description="错误时保存截图")


# ── 热键配置 ────────────────────────────────────────────────────

class HotkeysConfig(BaseModel):
    """运行时热键绑定。"""

    pause: str = Field("p", description="暂停/继续")
    quit: str = Field("q", description="退出")
    delay_up: str = Field("=", description="增加延迟")
    delay_down: str = Field("-", description="减少延迟")
    threshold_up: str = Field(".", description="提高阈值")
    threshold_down: str = Field(",", description="降低阈值")
    mode_cycle: str = Field("m", description="切换模式")


# ── 游戏设置配置 ────────────────────────────────────────────────

class GameSettingsConfig(BaseModel):
    """游戏内设置自动读取与校准。"""

    auto_read: bool = Field(True, description="启动时自动读取游戏设置")
    frequency: Literal["once", "every_song"] = Field("once", description="读取频率")
    server: Literal["auto", "jp", "tw", "cn", "kr", "en"] = Field(
        "auto", description="目标服务器"
    )
    timing_unit_ms: float = Field(1.0, ge=0.1, description="Timing 单位对应毫秒")
    default_note_speed: float = Field(10.0, ge=1.0, le=20.0, description="基准音符速度")
    auto_calibrate: bool = Field(True, description="自动校准预测引擎")
    last_read_timing_offset: int = Field(0, description="上次读取的 timing offset")
    last_read_note_speed: float = Field(10.0, description="上次读取的音符速度")
    last_calibration_time: str = Field("", description="上次校准时间 (ISO)")
    detected_server: str = Field("", description="自动检测到的服务器")


# ── 控制器配置 ──────────────────────────────────────────────────

class ControllerConfig(BaseModel):
    """控制器路由与性能监控配置。"""

    switch_cooldown: float = Field(30.0, ge=5.0, description="后端切换冷却 (秒)")
    perf_sample_size: int = Field(10, ge=3, le=100, description="性能采样数")


# ── 顶层配置 ────────────────────────────────────────────────────

class PjskConfig(BaseModel):
    """PJSK Auto Player 完整配置根模型。

    用法:
        # 从 dict 校验
        cfg = PjskConfig.model_validate(config_dict)
        # 导出为 dict
        cfg_dict = cfg.model_dump()
        # 部分校验某一节
        adb_cfg = AdbConfig.model_validate(config_dict.get("adb", {}))
    """

    adb: AdbConfig = Field(default_factory=AdbConfig, description="ADB 连接配置")
    scrcpy: ScrcpyConfig = Field(default_factory=ScrcpyConfig, description="scrcpy 后端配置")
    minitouch: MinitouchConfig = Field(default_factory=MinitouchConfig, description="minitouch 配置")
    screen: ScreenConfig = Field(default_factory=ScreenConfig, description="屏幕参数")
    play: PlayConfig = Field(default_factory=PlayConfig, description="执行参数")
    pid: PidConfig = Field(default_factory=PidConfig, description="PID 自适应")
    pipeline: PipelineConfig = Field(default_factory=PipelineConfig, description="Pipeline 配置")
    scene: SceneConfig = Field(default_factory=SceneConfig, description="场景检测")
    web: WebConfig = Field(default_factory=WebConfig, description="Web 面板")
    notification: NotificationConfig = Field(default_factory=NotificationConfig, description="通知")
    logging: LoggingConfig = Field(default_factory=LoggingConfig, description="日志")
    hotkeys: HotkeysConfig = Field(default_factory=HotkeysConfig, description="热键")
    game_settings: GameSettingsConfig = Field(
        default_factory=GameSettingsConfig, description="游戏设置读取"
    )
    controller: ControllerConfig = Field(
        default_factory=ControllerConfig, description="控制器"
    )

    @model_validator(mode="after")
    def check_screen_orientation(self):
        """警告: 横屏检测 (PJSK 是竖屏游戏)。"""
        if self.screen.width > self.screen.height:
            raise ValueError(
                f"屏幕宽度 ({self.screen.width}) 大于高度 ({self.screen.height})，"
                f"可能是横屏? PJSK 是竖屏游戏。"
            )
        return self

    @model_validator(mode="after")
    def warn_high_miss_rate(self):
        """警告: 高漏键率影响 AP。"""
        if self.play.miss_rate > 0.05:
            raise ValueError(
                f"play.miss_rate={self.play.miss_rate} 较大 (>5%)，会显著影响 AP 率"
            )
        return self

    @classmethod
    def from_dict(cls, data: dict) -> "PjskConfig":
        """从字典构建配置 (宽松模式: 忽略未知字段)。

        这是推荐的入口方法，与 ConfigLoader 返回的 dict 完全兼容。
        """
        # 提取已知字段，忽略未知字段
        valid_data = {}
        for field_name in cls.model_fields:
            if field_name in data:
                valid_data[field_name] = data[field_name]
        return cls.model_validate(valid_data)

    def to_dict(self) -> dict:
        """导出为扁平字典 (与 ConfigLoader.config 格式一致)。"""
        return self.model_dump()


# ── 校验辅助 ────────────────────────────────────────────────────

def validate_with_pydantic(config: dict) -> list[dict]:
    """使用 Pydantic 校验配置字典。

    Args:
        config: 待校验配置字典 (与 ConfigLoader.config 格式一致)

    Returns:
        错误列表，每个错误为 {"path": str, "message": str, "severity": str}
        空列表表示通过校验
    """
    errors: list[dict] = []

    # 1. 逐节校验 (更精确的错误定位)
    section_models = {
        "adb": AdbConfig,
        "scrcpy": ScrcpyConfig,
        "minitouch": MinitouchConfig,
        "screen": ScreenConfig,
        "play": PlayConfig,
        "pid": PidConfig,
        "pipeline": PipelineConfig,
        "scene": SceneConfig,
        "web": WebConfig,
        "notification": NotificationConfig,
        "logging": LoggingConfig,
        "hotkeys": HotkeysConfig,
        "game_settings": GameSettingsConfig,
        "controller": ControllerConfig,
    }

    for section_name, model_cls in section_models.items():
        section_data = config.get(section_name)
        if section_data is None:
            continue
        if not isinstance(section_data, dict):
            errors.append({
                "path": section_name,
                "message": f"应为 dict, 实际为 {type(section_data).__name__}",
                "severity": "error",
            })
            continue
        try:
            model_cls.model_validate(section_data)
        except Exception as e:
            # Pydantic v2 ValidationError 包含多个错误的详情
            errors.append({
                "path": section_name,
                "message": _format_pydantic_error(e),
                "severity": "error",
            })

    # 2. 顶层校验 (跨节约束)
    try:
        PjskConfig.from_dict(config)
    except Exception as e:
        errors.append({
            "path": "(root)",
            "message": _format_pydantic_error(e),
            "severity": "error",
        })

    return errors


def _format_pydantic_error(exc: Exception) -> str:
    """将 Pydantic 异常格式化为可读字符串。"""
    try:
        from pydantic import ValidationError
        if isinstance(exc, ValidationError):
            msgs = []
            for err in exc.errors():
                loc = ".".join(str(p) for p in err["loc"])
                msg = err["msg"]
                msgs.append(f"{loc}: {msg}")
            return "; ".join(msgs)
    except ImportError:
        pass
    return str(exc)


def generate_config_from_models() -> dict:
    """从 Pydantic 模型生成带默认值的完整配置字典。

    可替代 config/schema.py 中的 generate_config_template()。
    """
    return PjskConfig().model_dump()
