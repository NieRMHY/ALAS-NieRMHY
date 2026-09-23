"""启动时记忆运行：退出时记下正在运行的实例，下次启动据此恢复。

开关与上次记录都是运行态，存放在部署配置同目录的 startup_memory.json（该路径在 .gitignore 内）；
更新触发重启时落的标记放在应用 root 的 cache/ 下，不混进部署配置目录。
"""
import json
from pathlib import Path
from typing import Any, Iterable

from deploy.atomic import atomic_remove, atomic_write
from module.logger import logger
from module.runtime.setting import State

MEMORY_NAME = 'startup_memory.json'

# 更新触发重启时落这个标记，新进程据此只按记忆恢复，不套用启动时自动运行清单。
UPDATE_RESTART_NAME = 'webui-update-restart-pending'


def memory_path() -> Path:
    """与部署配置同目录，跟随应用自己的 root。"""
    file = getattr(State.deploy_config, 'file', None)
    return Path(file).with_name(MEMORY_NAME) if file else Path('config') / MEMORY_NAME


def update_restart_path() -> Path:
    """与记忆同一来源：应用 root 下的 cache/。"""
    file = getattr(State.deploy_config, 'file', None)
    root = Path(file).parent.parent if file else Path('.')
    return root / 'cache' / UPDATE_RESTART_NAME


def mark_update_restart() -> None:
    """记下本次重启由更新触发；写不进去只记录，不阻断重启。"""
    path = update_restart_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(str(path), 'pending\n')
    except OSError:
        logger.exception('更新重启标记无法写入，本次重启仍按配置清单恢复')


def consume_update_restart() -> bool:
    """读取并清除标记，使它只影响紧接着的那一次启动。"""
    path = update_restart_path()
    if not path.is_file():
        return False
    try:
        atomic_remove(str(path))
    except OSError:
        logger.exception('更新重启标记无法清除，本次启动仍按记忆恢复')
    return True


def startup_runs(configured: Iterable[str], update_restart: bool = False) -> list[str]:
    """本次启动要运行的实例：更新重启只认记忆，未启用记忆的实例仍按配置清单运行。"""
    data = _read()
    configured = list(configured)
    if not update_restart:
        return list(dict.fromkeys([*configured, *remembered_runs()]))
    kept = [name for name in configured if name not in data['remember']]
    remembered = [name for name in data['last'] if name in data['remember']]
    return list(dict.fromkeys([*kept, *remembered]))


def _names(value: Any) -> list[str]:
    return [name for name in value if isinstance(name, str)] if isinstance(value, list) else []


def _read() -> dict[str, list[str]]:
    """文件缺失或损坏都按未启用处理，不让记忆影响启动。"""
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
    path = memory_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({'remember': remember, 'last': last}, ensure_ascii=False, indent=2)
        path.write_text(payload, encoding='utf-8')
    except OSError:
        logger.exception('启动时记忆运行的文件无法写入')


def get_startup_remember(instance: str) -> bool:
    return instance in _read()['remember']


def set_startup_remember(instance: str, remember: bool) -> bool:
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
    """上次退出时正在运行、且现在仍启用记忆的实例。"""
    data = _read()
    return [name for name in data['last'] if name in data['remember']]


def record_running(instances: Iterable[str]) -> None:
    """记下退出那一刻仍在运行的实例，只保留启用记忆的那些。"""
    remember = _read()['remember']
    if not remember:
        return
    _write(remember, sorted({name for name in instances if name in remember}))
