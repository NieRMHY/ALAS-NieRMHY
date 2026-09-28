"""任务优先级解析模块。

提供 parse_task_priority 函数，解析用户配置中的任务优先级文本，
支持 Unicode 全角分隔符规范化、注释去除和去重处理。
"""

import re
from typing import Any, Iterable, Optional

from module.config.deep import deep_get, deep_iter

PRIORITY_SEPARATOR = "\n> "


def parse_task_priority(value: Any) -> list[str]:
    """解析任务优先级文本，返回去重后的任务名列表。

    Args:
        value: 原始优先级配置文本。

    Returns:
        list[str]: 解析提取出的有序唯一任务名称列表。
    """
    if not value:
        return []

    text = str(value)
    text = re.sub(r"[＞﹥›˃ᐳ❯]", ">", text)
    tasks = []
    seen = set()
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        for raw_task in line.split(">"):
            task = raw_task.strip()
            if not task or task in seen:
                continue
            seen.add(task)
            tasks.append(task)
    return tasks


def format_task_priority(tasks: Iterable[str]) -> str:
    """将任务名列表格式化为配置文件中的优先级字符串。

    Args:
        tasks: 任务名称可迭代集合。

    Returns:
        str: 拼接后的优先级配置字符串。
    """
    return PRIORITY_SEPARATOR.join(str(task).strip() for task in tasks if str(task).strip())


def normalize_task_priority(value: Any) -> str:
    """标准化优先级文本，清除注释、空行和重复任务。

    Args:
        value: 原始优先级配置值。

    Returns:
        str: 标准化后的优先级格式文本。
    """
    return format_task_priority(parse_task_priority(value))


def get_scheduler_tasks(args: dict[str, Any]) -> list[str]:
    """从 args.json 结构中提取实际参与调度的任务。

    Args:
        args: 完整的参数定义字典。

    Returns:
        list[str]: 参与调度的命令标识列表。
    """
    tasks = []
    for path, data in deep_iter(args, depth=3):
        if path[-2:] != ["Scheduler", "Command"]:
            continue
        if not isinstance(data, dict):
            continue
        command = data.get("value")
        if isinstance(command, str) and command and command not in tasks:
            tasks.append(command)
    return tasks


def _insert_by_default_neighbors(ordered: list[str], task: str, default_order: list[str]) -> None:
    """参考默认顺序将新任务插入到既有排序列表的邻近相对位置。

    Args:
        ordered: 目标任务排序列表（就地修改）。
        task: 待插入的新任务名称。
        default_order: 官方默认的任务优先级列表。
    """
    if task in ordered:
        return

    try:
        default_index = default_order.index(task)
    except ValueError:
        ordered.append(task)
        return

    prev_task = None
    for candidate in reversed(default_order[:default_index]):
        if candidate in ordered:
            prev_task = candidate
            break

    next_task = None
    for candidate in default_order[default_index + 1:]:
        if candidate in ordered:
            next_task = candidate
            break

    if prev_task is not None:
        ordered.insert(ordered.index(prev_task) + 1, task)
    elif next_task is not None:
        ordered.insert(ordered.index(next_task), task)
    else:
        ordered.append(task)


def merge_task_priority(
    current: Any,
    default: Any,
    available_tasks: Optional[Iterable[str]] = None,
) -> str:
    """合并用户优先级与默认优先级，并按默认位置补入新增任务。

    Args:
        current: 用户当前配置的优先级字符串。
        default: 系统默认的模板优先级字符串。
        available_tasks: 当前所有有效可调度的任务名称集合。

    Returns:
        str: 合并并重新格式化后的优先级配置文本。
    """
    default_order = parse_task_priority(default)
    available = list(available_tasks or default_order)
    available_set = set(available)

    current_order = [
        task
        for task in parse_task_priority(current)
        if task in available_set
    ]
    ordered = list(dict.fromkeys(current_order))

    default_available = [task for task in default_order if task in available_set]
    for task in default_available:
        if task not in ordered:
            _insert_by_default_neighbors(ordered, task, default_available)

    for task in available:
        if task not in ordered:
            _insert_by_default_neighbors(ordered, task, default_available)

    return format_task_priority(ordered)


def task_priority_from_config(config: dict[str, Any], args: dict[str, Any]) -> str:
    """根据配置和 args 模板得到可保存、可展示的任务优先级。

    Args:
        config: 当前用户配置字典。
        args: 系统 args 参数字典。

    Returns:
        str: 规整后的任务优先级文本。
    """
    current = deep_get(config, "General.YukikazeTaskManager.TaskPriorityAdjustment")
    default = deep_get(args, "General.YukikazeTaskManager.TaskPriorityAdjustment.value")
    return merge_task_priority(current, default, get_scheduler_tasks(args))
