"""
PJSK Auto Player — Obstruction & Recovery System v1 (v5.5.0)

检测游戏运行中所有阻塞正常执行的画面事件。

安全设计:
  - 弹窗自动关闭只操作右上角 X 按钮，不点中央 OK/确认
  - OCR 验证按钮文字为安全列表 (閉じる/关闭/close) 后才点击
  - 消费类弹窗 (抽卡/购买/課金) 不自动关闭，改走 ESCALATED 告警
  - 未知类型弹窗不自动关闭，跳过等待用户处理
"""

from recovery.detector import ObstructionDetector, ObstructionEvent
from recovery.machine import RecoveryStateMachine, RecoveryState
from recovery.scheduler import HealthScheduler

__all__ = [
    "ObstructionEngine",
    "ObstructionDetector", "ObstructionEvent",
    "RecoveryStateMachine", "RecoveryState",
    "HealthScheduler",
]


class ObstructionEngine:
    """阻塞检测与恢复引擎 — 顶层协调器。"""

    RESULT_OK = "OK"
    RESULT_DISMISSED = "DISMISSED"
    RESULT_CONSUMPTION = "CONSUMPTION"  # 消费弹窗, 不自动关闭
    RESULT_RECOVERING = "RECOVERING"
    RESULT_ESCALATED = "ESCALATED"

    def __init__(self, controller, config: dict):
        self.controller = controller
        self.config = config

        self.detector = ObstructionDetector(config)
        self.machine = RecoveryStateMachine(controller, config,
                                            on_escalated=self._on_escalated)
        self.scheduler = HealthScheduler(controller, config,
                                         on_unhealthy=self._on_unhealthy)

        self._frame_count = 0

    def process_frame(self, frame, scene_name: str, frame_hash: int) -> str:
        """处理一帧, 返回当前状态。

        Returns:
            "OK"          — 正常, 继续 pipeline
            "DISMISSED"   — 安全弹窗已关闭, 继续 pipeline
            "CONSUMPTION" — 消费类弹窗, 需要用户介入
            "RECOVERING"  — 恢复中, 跳过 pipeline
            "ESCALATED"   — 无法恢复, 需要停止
        """
        self._frame_count += 1

        import time
        self.scheduler.on_frame_received(time.time())

        # 恢复状态机正在运行
        if self.machine.state != RecoveryState.IDLE:
            self.machine.tick(frame, scene_name)
            if self.machine.state == RecoveryState.RECOVERED:
                self.machine.reset()
                return self.RESULT_OK
            elif self.machine.state == RecoveryState.ESCALATED:
                return self.RESULT_ESCALATED
            return self.RESULT_RECOVERING

        # 正常检测
        event = self.detector.analyze(frame, scene_name, frame_hash)
        if event is None:
            self.scheduler.on_tick(time.time())
            return self.RESULT_OK

        if event.type == "blocking_dialog":
            if event.dialog_is_consumption:
                # 🛑 消费弹窗 — 不自动关闭, 告警
                logger = __import__("logging").getLogger("pjsk.recovery")
                logger.critical(
                    "[安全] ⛔ 检测到消费类弹窗: 已跳过自动关闭, "
                    "请人工确认操作"
                )
                return self.RESULT_CONSUMPTION

            # 安全弹窗 — 只点右上角 X, 并用 OCR 验证
            if self._dismiss_dialog(frame):
                return self.RESULT_DISMISSED
            else:
                # 无法确认按钮安全 → 不点击, 跳过
                return self.RESULT_OK

        # 严重事件 → 状态机
        self.machine.report_crash(event.type, event.scene_before)
        return self.RESULT_RECOVERING

    def _dismiss_dialog(self, frame) -> bool:
        """尝试关闭安全弹窗。

        安全策略:
          1. 只点击右上角 close 按钮区域
          2. 点击前用 OCR 验证按钮文字是安全关键词
          3. 不点击中央区域的 OK/确认按钮
        """
        h, w = frame.shape[:2]

        # 右上角 close 按钮区域 (通用)
        close_region = (0.85, 0.02, 0.98, 0.08)

        # OCR 验证: 确认按钮文字为"关闭"/"閉じる"/"close"/"✕"
        if not self.detector.verify_close_button(frame, close_region):
            logger = __import__("logging").getLogger("pjsk.recovery")
            logger.warning("[安全] 右上角按钮文字未匹配安全列表, 跳过自动关闭")
            return False

        # 确认安全 → 点击
        if self.controller:
            rx, ry, rw, rh = close_region
            cx = int((rx + rw) / 2 * w)
            cy = int((ry + rh) / 2 * h)
            self.controller.click(cx / w, cy / h)
            return True

        return False

    def _on_unhealthy(self, issue: str):
        """HealthScheduler 回调 — 启动恢复。"""
        if self.machine.state == RecoveryState.IDLE:
            self.machine.report_crash(issue)

    def _on_escalated(self):
        """Recovery 回调 — 全部恢复级别耗尽。"""
        logger = __import__("logging").getLogger("pjsk.recovery")
        logger.critical("[Recovery] 🔴 无法自动恢复, 请求用户介入")

    @property
    def degraded_mode(self) -> bool:
        return self.machine.degraded_mode

    @property
    def state(self) -> str:
        return self.machine.state

    def stop(self):
        self.scheduler.stop()
        self.machine.reset()
