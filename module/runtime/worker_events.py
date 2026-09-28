"""Worker 的任务边界和最终结果定义，通过已有可靠进程间队列传递。"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Callable, Optional


class WorkerResult(StrEnum):
    """Worker 运行结束状态枚举。

    Attributes:
        FINISHED: 正常执行完毕退出。
        MANUAL_STOP: 用户手动触发停止。
        UPDATE: 触发自动更新导致退出。
        ERROR: 出现未捕获异常崩溃退出。
    """
    FINISHED = "finished"
    MANUAL_STOP = "manual_stop"
    UPDATE = "update"
    ERROR = "error"


@dataclass(frozen=True)
class TaskEvent:
    """Worker 切换当前任务事件。

    Attributes:
        run_id: 实例运行生命周期标识。
        command: 当前切换执行的任务命令名称。
    """
    run_id: Optional[str]
    command: Optional[str]


@dataclass(frozen=True)
class ExitEvent:
    """Worker 退出事件。

    Attributes:
        run_id: 实例运行生命周期标识。
        result: 最终退出状态结果枚举。
    """
    run_id: Optional[str]
    result: WorkerResult


_sink: Optional[Callable[[Any], None]] = None
_run_id: Optional[str] = None


def initialize(sink: Callable[[Any], None], run_id: str) -> None:
    """仅在 worker 子进程中安装事件输出通道，独立脚本保持无操作。

    Args:
        sink: 接收事件消息的回调或队列管道方法。
        run_id: 当前子进程绑定的运行生命周期标识。
    """
    global _sink, _run_id
    _sink = sink
    _run_id = run_id


def set_task(command: Optional[str]) -> None:
    """向事件通道发布当前任务切换通知。

    Args:
        command: 切换的目标任务命令名称。
    """
    if _sink is not None:
        _sink(TaskEvent(_run_id, command))
