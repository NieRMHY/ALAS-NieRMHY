"""冻结大世界资源观察后串行落库，仅事务合并仪表盘字段。"""

from contextvars import copy_context
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from module.base.async_executor import async_executor
from module.config.deep import deep_get, deep_set
from module.config.transaction import config_transaction
from module.config.utils import filepath_config, read_file, write_file
from module.logger import logger


def _persist_resources(snapshot, values, observed_at):
    from module.log_res.log_res import LogRes

    try:
        recorder = LogRes(snapshot)
        for name, value in values.items():
            recorder.record(name, value, defer_history=True, observed_at=observed_at)
        path = Path(filepath_config(snapshot.config_name))
        if not path.is_file():
            return
        with config_transaction(path):
            current = read_file(str(path))
            for name, value in values.items():
                prefix = f'Dashboard.{name}'
                previous = deep_get(current, prefix + '.Record')
                if previous is not None and str(previous) > str(observed_at):
                    continue
                fields = value if isinstance(value, dict) else {'Value': value}
                for field, number in fields.items():
                    deep_set(current, prefix + '.' + field, number)
                deep_set(current, prefix + '.Record', observed_at)
            write_file(str(path), current)
    except Exception:
        logger.exception('[大世界-资源后台] 资源观察或仪表盘保存失败')
        raise


def record_resources_background(config, values, *, observed_at=None):
    """后台使用独立快照；运行中配置、任务绑定及待提交设置只由主线程操作。"""
    observed_at = observed_at or datetime.now()
    values = deepcopy(values)
    dashboard = deepcopy(deep_get(config.data, 'Dashboard', default={}))
    # 内存值立即可供本轮预算使用，后台不调用 live config.save()/update()。
    for name, value in values.items():
        fields = value if isinstance(value, dict) else {'Value': value}
        for field, number in fields.items():
            deep_set(config.data, f'Dashboard.{name}.{field}', number)
        deep_set(config.data, f'Dashboard.{name}.Record', observed_at)
    snapshot = SimpleNamespace(
        config_name=getattr(config, 'config_name', 'default'),
        task=deepcopy(getattr(config, 'task', None)),
        _bind_task_override=getattr(config, '_bind_task_override', None),
        data={'Dashboard': dashboard}, modified={},
    )
    context = copy_context()
    return async_executor.submit(context.run, _persist_resources, snapshot, values, observed_at)
