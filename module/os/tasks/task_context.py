"""大世界代理任务的临时身份与延迟请求管理模块。"""

from contextlib import contextmanager
from dataclasses import dataclass, fields, replace
from datetime import datetime


@dataclass(frozen=True)
class TaskDelayRequest:
    """与 `config.task_delay` 同名的参数容器，避免延后提交时才发现参数拼写错误。

    Attributes:
        success (bool | None): 任务成功与否标记。
        server_update (bool | str | list | None): 是否延迟至服务器刷新。
        target (datetime | str | list | None): 目标延迟时间。
        minute (int | float | tuple | None): 延迟分钟数。
        task (str | None): 目标任务名称。
    """

    success: bool | None = None
    server_update: bool | str | list | None = None
    target: datetime | str | list | None = None
    minute: int | float | tuple | None = None
    task: str | None = None

    def apply(self, config):
        """仅提交已指定的参数，保留多个时间条件取最近值的原有语义。

        Args:
            config (AzurLaneConfig): 配置对象。
        """
        config.task_delay(**{
            field.name: value
            for field in fields(self)
            if (value := getattr(self, field.name)) is not None
        })


@dataclass
class OverflowDelay:
    """一轮防溢出任务中共享的延迟请求容器；退出本轮后不再保留。

    Attributes:
        request (TaskDelayRequest | None): 延迟请求对象。
    """

    request: TaskDelayRequest | None = None


@dataclass(frozen=True)
class OpsiTaskContext:
    """共享配置上的单一代理上下文，嵌套任务沿用防溢出延迟容器。

    Attributes:
        smart_scheduling (bool): 是否处于智能调度上下文中。
        overflow (OverflowDelay | None): 防溢出延迟容器。
        parent_task (str | None): 当前代理任务的直接来源，用于区分直接防溢出与嵌套智能调度。
    """

    smart_scheduling: bool = False
    overflow: OverflowDelay | None = None
    parent_task: str | None = None


def current_opsi_context(config):
    """让共享同一配置的任务对象读取同一个上下文。

    Args:
        config (AzurLaneConfig): 配置对象。

    Returns:
        OpsiTaskContext: 当前配置绑定的大世界任务上下文。
    """
    return getattr(config, '_opsi_task_context', None) or OpsiTaskContext()


_MISSING = object()


@contextmanager
def _temporary_attributes(config, **values):
    """精确恢复属性的缺失、None 和原值，不能把三者混为一谈。

    Args:
        config (AzurLaneConfig): 配置对象。
        **values: 需临时设置的键值对。

    Yields:
        None: 临时上下文期间的执行句柄。
    """
    previous = {key: getattr(config, key, _MISSING) for key in values}
    try:
        for key, value in values.items():
            setattr(config, key, value)
        yield
    finally:
        for key, value in previous.items():
            if value is _MISSING:
                if hasattr(config, key):
                    delattr(config, key)
            else:
                setattr(config, key, value)


@contextmanager
def _temporary_config_overrides(config):
    """代理子任务的强制覆盖只在本次调用生效，保留持久化修改与统计状态。

    Args:
        config (AzurLaneConfig): 配置对象；无强制覆盖字典的测试桩也可使用。

    Yields:
        None: 临时强制覆盖作用域。
    """
    attributes = dict(config.__dict__)
    snapshots = {
        name: (values, dict(values) if isinstance(values, dict) else None)
        for name in ('overridden', '_scheduler_overrides')
        for values in (attributes.get(name, _MISSING),)
    }
    try:
        yield
    finally:
        keys = set()
        for name, (original, snapshot) in snapshots.items():
            current = config.__dict__.get(name, _MISSING)
            if isinstance(current, dict):
                keys.update(current)
            if snapshot is not None:
                keys.update(snapshot)
                original.clear()
                original.update(snapshot)
            if original is _MISSING:
                if name in config.__dict__:
                    object.__delattr__(config, name)
            else:
                # 运行时持有调度覆盖字典的引用，恢复时必须保留原对象身份。
                object.__setattr__(config, name, original)

        for key in keys:
            if key in attributes:
                object.__setattr__(config, key, attributes[key])
            elif key in config.__dict__:
                object.__delattr__(config, key)


@contextmanager
def opsi_task_context(config, task, *, bind_task, disable_task_switch):
    """切换子任务身份；正常返回、TaskEnd 和绑定失败都恢复原身份。

    Args:
        config (AzurLaneConfig): 配置对象。
        task (Function): 子任务对象。
        bind_task (str): 需绑定的配置任务名。
        disable_task_switch (bool): 是否禁用任务切换。

    Yields:
        OpsiTaskContext: 新构造并绑定的任务上下文对象。
    """
    previous_task = config.task
    previous_bind = getattr(config, '_bind_task_override', None)
    # 嵌套代理仍由最外层调度任务占有运行时间，不能把中间代理误认为调度任务。
    task_switch_owner = getattr(config, '_task_switch_owner', None) or previous_task
    context = replace(
        current_opsi_context(config), smart_scheduling=True, parent_task=previous_task.command,
    )
    try:
        with _temporary_attributes(
            config,
            task=task,
            _bind_task_override=bind_task,
            _task_switch_owner=task_switch_owner,
            _disable_task_switch=disable_task_switch,
            _opsi_task_context=context,
        ):
            config.bind(bind_task)
            with _temporary_config_overrides(config):
                yield context
    finally:
        config.bind(previous_bind if previous_bind is not None else previous_task)


@contextmanager
def prevent_overflow_context(config):
    """防溢出代理共享本轮延迟，最外层退出后恢复原上下文。

    Args:
        config (AzurLaneConfig): 配置对象。

    Yields:
        OverflowDelay: 本轮防溢出共享延迟对象。
    """
    previous = current_opsi_context(config)
    overflow = previous.overflow if previous.overflow is not None else OverflowDelay()
    with _temporary_attributes(config, _opsi_task_context=replace(previous, overflow=overflow)):
        yield overflow
