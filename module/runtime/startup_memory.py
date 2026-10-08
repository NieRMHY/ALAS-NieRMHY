"""启动时记忆运行：退出时记下正在运行的实例，下次启动据此恢复。

开关与上次记录都是运行态，存放在部署配置同目录的 startup_memory.json（该路径在 .gitignore 内）；
更新触发重启时落的标记放在应用 root 的 cache/ 下，不混进部署配置目录。
"""
import json
import time
from pathlib import Path
from typing import Any, Iterable

from deploy.atomic import atomic_remove, atomic_write
from module.logger import logger
from module.runtime.setting import State

MEMORY_NAME = 'startup_memory.json'

# 更新触发重启时落这个标记，新进程据此只按记忆恢复，不套用启动时自动运行清单。
UPDATE_RESTART_NAME = 'webui-update-restart-pending'
UPDATE_RESTART_TTL = 1800


def memory_path() -> Path:
    """获取记忆文件路径，与部署配置同目录，跟随应用自身的根目录。

    Returns:
        Path: 记忆配置文件的路径对象。
    """
    file = getattr(State.deploy_config, 'file', None)
    return Path(file).with_name(MEMORY_NAME) if file else Path('config') / MEMORY_NAME


def update_restart_path() -> Path:
    """获取更新重启标记文件路径，位于应用根目录的 cache/ 下。

    Returns:
        Path: 重启标记文件的路径对象。
    """
    file = getattr(State.deploy_config, 'file', None)
    root = Path(file).parent.parent if file else Path('.')
    return root / 'cache' / UPDATE_RESTART_NAME


def mark_update_restart() -> None:
    """记下本次重启由更新触发；写不进去只记录日志，不阻断重启。

    标记里带上写入时间：若中间某次启动没有消费它，超时即视为过期，不会在很久以后误判。
    """
    path = update_restart_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(str(path), str(int(time.time())) + chr(10))
        logger.info(f'更新重启标记已写入: {path}')
    except OSError:
        logger.exception('更新重启标记无法写入，本次重启仍按配置清单恢复')

def consume_update_restart() -> bool:
    """读取并清除标记，使它只影响紧接着的那一次启动。

    由决定启动清单的那次启动消费（见 app.py）：只做依赖同步之类的中间启动不消费它，
    否则标记会被提前吃掉，真正拉起调度器时反而看不到；超时的标记按过期处理。

    Returns:
        bool: 存在未过期的更新标记返回 True，否则返回 False。
    """
    path = update_restart_path()
    if not path.is_file():
        logger.info(f'未找到更新重启标记: {path}')
        return False
    try:
        written = int(path.read_text(encoding='utf-8').strip())
    except (OSError, ValueError):
        written = int(time.time())
    try:
        atomic_remove(str(path))
    except OSError:
        logger.exception('更新重启标记无法清除，本次启动仍按记忆恢复')
    if time.time() - written > UPDATE_RESTART_TTL:
        logger.info(f'更新重启标记已过期（{int(time.time() - written)} 秒前），按普通启动处理: {path}')
        return False
    logger.info(f'读到更新重启标记，本次按更新重启处理: {path}')
    return True

def startup_runs(configured: Iterable[str], update_restart: bool = False) -> list[str]:
    """计算本次启动需要运行的实例列表。

    更新重启只认记忆，未启用记忆的实例仍按配置清单运行。

    Args:
        configured: 配置清单中指定启动的实例列表。
        update_restart: 本次启动是否由更新操作触发。

    Returns:
        list[str]: 经去重计算后最终应启动的实例名称列表。
    """
    data = _read()
    configured = list(configured)
    if not update_restart:
        return list(dict.fromkeys([*configured, *remembered_runs()]))
    kept = [name for name in configured if name not in data['remember']]
    remembered = [name for name in data['last'] if name in data['remember']]
    return list(dict.fromkeys([*kept, *remembered]))


def _names(value: Any) -> list[str]:
    """过滤并提取字符串列表。

    Args:
        value: 待提取的原始值。

    Returns:
        list[str]: 包含的纯字符串列表。
    """
    return [name for name in value if isinstance(name, str)] if isinstance(value, list) else []


def _read() -> dict[str, list[str]]:
    """读取记忆配置文件。文件缺失或损坏都按未启用处理，不让记忆影响启动。

    Returns:
        dict[str, list[str]]: 包含 'remember' 和 'last' 列表的字典。
    """
    try:
        data = json.loads(memory_path().read_text(encoding='utf-8'))
    except FileNotFoundError:
        data = None
    except (OSError, ValueError):
        logger.exception('启动时记忆运行的文件无法读取，按未启用处理')
        data = None
    if not isinstance(data, dict):
        return {'remember': [], 'last': []}
    return {'remember': _names(data.get('remember')), 'last': _names(data.get('last'))}


def _write(remember: list[str], last: list[str]) -> None:
    """将记忆数据持久化写入 JSON 文件。

    Args:
        remember: 开启记忆运行的实例名称列表。
        last: 上次退出时仍在运行的实例名称列表。
    """
    path = memory_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({'remember': remember, 'last': last}, ensure_ascii=False, indent=2)
        path.write_text(payload, encoding='utf-8')
    except OSError:
        logger.exception('启动时记忆运行的文件无法写入')


def get_startup_remember(instance: str) -> bool:
    """获取指定实例是否开启了记忆运行。

    Args:
        instance: 实例名称。

    Returns:
        bool: 已开启返回 True，否则返回 False。
    """
    return instance in _read()['remember']


def set_startup_remember(instance: str, remember: bool) -> bool:
    """设置指定实例是否开启记忆运行。

    Args:
        instance: 实例名称。
        remember: 是否开启。

    Returns:
        bool: 设置后的状态布尔值。

    Raises:
        PermissionError: 处于演示模式时禁止修改。
    """
    from module.runtime.deploy_settings import is_demo_mode
    if is_demo_mode():
        raise PermissionError('演示模式下不能修改启动时记忆运行')

    data = _read()
    names = data['remember']
    if remember:
        if instance not in names:
            names.append(instance)
    else:
        names = [name for name in names if name != instance]
    _write(names, data['last'])
    return instance in names


def remembered_runs() -> list[str]:
    """获取上次退出时正在运行且当前仍启用记忆的实例列表。

    Returns:
        list[str]: 匹配的实例名称列表。
    """
    data = _read()
    return [name for name in data['last'] if name in data['remember']]


def record_running(instances: Iterable[str]) -> None:
    """记下退出那一刻仍在运行的实例，只保留启用记忆的那些。

    Args:
        instances: 当前正在运行的实例名称集合。
    """
    remember = _read()['remember']
    if not remember:
        return
    _write(remember, sorted({name for name in instances if name in remember}))
