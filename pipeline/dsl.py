"""
PJSK Auto Player — Pipeline DSL (声明式任务定义) (v5.11.0+)

受 KotoneBot @action 装饰器启发，提供 Pythonic 的 Pipeline 任务定义方式。
DSL 定义自动生成与 Pipeline V2 JSON 引擎兼容的任务配置。

用法:
    from pipeline.dsl import task, algorithm, retry, delay, next_step, failed_next, TaskRegistry

    @task("DismissResult")
    @algorithm("TemplateMatch", template="result_ok.png")
    @retry(3)
    @delay(pre=500, post=1000)
    @next_step("DetectMenuScreen")
    @failed_next("HandleError")
    def dismiss_result():
        '''关闭结算画面，点击 OK 按钮后等待返回菜单。'''
        pass

    # 生成 JSON
    registry = TaskRegistry()
    registry.register(dismiss_result)
    json_str = registry.to_json()

    # 导出到文件
    registry.save("tasks/my_pipeline.json")
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


# ── 任务元数据 ──────────────────────────────────────────────────

@dataclass
class TaskMeta:
    """DSL 任务元数据，映射为 Pipeline V2 JSON 任务节点。"""

    name: str
    doc: str = ""
    action: str = "DoNothing"
    algorithm: str = ""
    template: str = ""
    roi: list[int] = field(default_factory=list)
    max_retries: int = 3
    pre_delay: int = 0
    post_delay: int = 0
    next_tasks: list[str] = field(default_factory=list)
    failed_next_tasks: list[str] = field(default_factory=list)
    exceeded_next_tasks: list[str] = field(default_factory=list)
    sub_tasks: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """导出为 Pipeline V2 JSON 兼容格式。"""
        d: dict[str, Any] = {
            "action": self.action,
            "doc": self.doc,
        }
        if self.algorithm:
            d["algorithm"] = self.algorithm
        if self.template:
            d["template"] = self.template
        if self.roi:
            d["roi"] = self.roi
        d["maxRetries"] = self.max_retries
        d["preDelay"] = self.pre_delay
        d["postDelay"] = self.post_delay
        d["next"] = self.next_tasks if self.next_tasks else ["#next"]
        if self.failed_next_tasks:
            d["failed_next"] = self.failed_next_tasks
        if self.exceeded_next_tasks:
            d["exceeded_next"] = self.exceeded_next_tasks
        if self.sub_tasks:
            d["sub"] = self.sub_tasks
        d.update(self.extra)
        return d


# ── 任务注册表 ──────────────────────────────────────────────────

class TaskRegistry:
    """全局任务注册表，管理所有 DSL 定义的 Pipeline 任务。

    用法:
        registry = TaskRegistry()
        registry.register(my_task_func)
        registry.to_json()  # 生成 Pipeline V2 JSON
    """

    def __init__(self):
        self._tasks: dict[str, TaskMeta] = {}

    def register(self, func: Callable) -> TaskMeta:
        """注册一个被 @task 装饰的函数。

        Args:
            func: 被 @task 装饰的函数

        Returns:
            注册的 TaskMeta 对象

        Raises:
            ValueError: 如果任务名已存在
        """
        meta = getattr(func, "_pjsk_task_meta", None)
        if meta is None:
            raise TypeError(
                f"函数 '{func.__name__}' 未被 @task 装饰。"
                f" 请使用 @task('TaskName') 装饰。"
            )
        if meta.name in self._tasks:
            raise ValueError(f"任务 '{meta.name}' 已注册")
        self._tasks[meta.name] = meta
        return meta

    def get(self, name: str) -> Optional[TaskMeta]:
        """按名称获取任务元数据。"""
        return self._tasks.get(name)

    def list_tasks(self) -> list[str]:
        """列出所有已注册任务名。"""
        return sorted(self._tasks.keys())

    def to_dict(self) -> dict[str, dict]:
        """导出为 Pipeline V2 JSON 兼容的字典。"""
        result: dict[str, dict] = {}
        # Add doc header
        result["doc"] = "PJSK Auto Player — DSL-generated Pipeline"
        result["version"] = "3.0.0"
        for name, meta in self._tasks.items():
            result[name] = meta.to_dict()
        return result

    def to_json(self, indent: int = 2) -> str:
        """导出为格式化的 JSON 字符串。"""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def save(self, path: str, indent: int = 2):
        """保存到 JSON 文件。"""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=indent, ensure_ascii=False)


# ── 装饰器 ──────────────────────────────────────────────────────


def task(name: str, action: str = "DoNothing"):
    """注册一个 Pipeline 任务。

    Args:
        name: 任务名 (对应 JSON 中的 key)
        action: 动作类型 (DoNothing / ClickSelf / ClickXY / Swipe / Tap / Wait)
    """

    def decorator(func: Callable):
        meta = TaskMeta(
            name=name,
            doc=func.__doc__ or "",
            action=action,
        )
        func._pjsk_task_meta = meta
        return func

    return decorator


def algorithm(algo: str, template: str = "", **kwargs):
    """设置识别算法。

    Args:
        algo: 算法名 (DirectHit / OcrDetect / BrightnessDetect / ColorDetect / TemplateMatch)
        template: 模板图片路径 (DirectHit / TemplateMatch 时使用)
    """

    def decorator(func: Callable):
        meta = getattr(func, "_pjsk_task_meta", None)
        if meta is None:
            raise TypeError(f"@algorithm 必须在 @task 之后使用")
        meta.algorithm = algo
        meta.template = template
        meta.extra.update(kwargs)
        return func

    return decorator


def retry(max_retries: int):
    """设置最大重试次数。"""

    def decorator(func: Callable):
        meta = getattr(func, "_pjsk_task_meta", None)
        if meta is None:
            raise TypeError(f"@retry 必须在 @task 之后使用")
        meta.max_retries = max_retries
        return func

    return decorator


def delay(pre: int = 0, post: int = 0):
    """设置前后延迟 (毫秒)。

    Args:
        pre: 动作前等待 (ms)
        post: 动作后等待 (ms)
    """

    def decorator(func: Callable):
        meta = getattr(func, "_pjsk_task_meta", None)
        if meta is None:
            raise TypeError(f"@delay 必须在 @task 之后使用")
        meta.pre_delay = pre
        meta.post_delay = post
        return func

    return decorator


def next_step(*task_names: str):
    """设置成功后的跳转目标。

    Args:
        *task_names: 跳转目标任务名 (可多个，按顺序尝试)
    """

    def decorator(func: Callable):
        meta = getattr(func, "_pjsk_task_meta", None)
        if meta is None:
            raise TypeError(f"@next_step 必须在 @task 之后使用")
        meta.next_tasks = list(task_names)
        return func

    return decorator


def failed_next(*task_names: str):
    """设置失败后的跳转目标。"""

    def decorator(func: Callable):
        meta = getattr(func, "_pjsk_task_meta", None)
        if meta is None:
            raise TypeError(f"@failed_next 必须在 @task 之后使用")
        meta.failed_next_tasks = list(task_names)
        return func

    return decorator


def exceeded_next(*task_names: str):
    """设置重试耗尽后的跳转目标。"""

    def decorator(func: Callable):
        meta = getattr(func, "_pjsk_task_meta", None)
        if meta is None:
            raise TypeError(f"@exceeded_next 必须在 @task 之后使用")
        meta.exceeded_next_tasks = list(task_names)
        return func

    return decorator


def roi(x: int, y: int, w: int, h: int):
    """设置识别区域。

    Args:
        x, y: 区域左上角坐标
        w, h: 区域宽度和高度
    """

    def decorator(func: Callable):
        meta = getattr(func, "_pjsk_task_meta", None)
        if meta is None:
            raise TypeError(f"@roi 必须在 @task 之后使用")
        meta.roi = [x, y, w, h]
        return func

    return decorator


def subtasks(*task_names: str):
    """设置并行子任务。"""

    def decorator(func: Callable):
        meta = getattr(func, "_pjsk_task_meta", None)
        if meta is None:
            raise TypeError(f"@subtasks 必须在 @task 之后使用")
        meta.sub_tasks = list(task_names)
        return func

    return decorator


# ── 便捷工厂 ────────────────────────────────────────────────────


def create_click_task(
    name: str,
    doc: str = "",
    next_tasks: list[str] | None = None,
    failed_tasks: list[str] | None = None,
    max_retries: int = 3,
    pre_delay: int = 0,
    post_delay: int = 0,
    algorithm: str = "",
    template: str = "",
    **extra,
) -> TaskMeta:
    """快捷创建点击类任务。

    不需要定义函数，直接返回 TaskMeta 对象。
    """
    return TaskMeta(
        name=name,
        doc=doc,
        action="ClickSelf",
        algorithm=algorithm,
        template=template,
        max_retries=max_retries,
        pre_delay=pre_delay,
        post_delay=post_delay,
        next_tasks=next_tasks or ["#next"],
        failed_next_tasks=failed_tasks or [],
        extra=extra,
    )


def create_wait_task(
    name: str,
    doc: str = "",
    duration_ms: int = 1000,
    next_tasks: list[str] | None = None,
) -> TaskMeta:
    """快捷创建等待任务。"""
    return TaskMeta(
        name=name,
        doc=doc,
        action="Wait",
        post_delay=duration_ms,
        next_tasks=next_tasks or ["#next"],
    )


# ── 示例 ────────────────────────────────────────────────────────

if __name__ == "__main__":
    # 演示 DSL 用法
    @task("DismissResult", action="ClickSelf")
    @algorithm("TemplateMatch", template="result_ok.png")
    @retry(3)
    @delay(pre=500, post=1000)
    @next_step("DetectMenuScreen")
    @failed_next("RetryDismiss", "HandleError")
    def dismiss_result():
        """关闭结算画面，点击 OK 按钮后等待返回菜单。"""
        pass

    @task("DetectGameScreen", action="DoNothing")
    @algorithm("BrightnessDetect")
    @retry(5)
    @next_step("PlaySong", "DetectResultScreen")
    @failed_next("DetectResultScreen", "DetectMenuScreen")
    def detect_game_screen():
        """检测是否在游戏执行画面。"""
        pass

    @task("HandleError", action="DoNothing")
    @delay(post=2000)
    @next_step("DetectGameScreen")
    def handle_error():
        """错误处理：等待 2 秒后重新检测场景。"""
        pass

    # 注册并导出
    registry = TaskRegistry()
    registry.register(dismiss_result)
    registry.register(detect_game_screen)
    registry.register(handle_error)

    # 添加工厂任务
    registry._tasks["WaitForMenu"] = create_wait_task(
        "WaitForMenu", "等待菜单加载", duration_ms=3000,
        next_tasks=["DetectGameScreen"],
    )

    print(f"已注册 {len(registry._tasks)} 个任务:")
    for name in registry.list_tasks():
        print(f"  - {name}")

    print("\n--- JSON ---")
    print(registry.to_json())
