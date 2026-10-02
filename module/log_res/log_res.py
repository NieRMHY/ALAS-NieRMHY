"""资源变动记录与同步模块。

当各项游戏资源数值（如石油、物资、钻石、魔方等）发生变化时，
负责更新配置文件中对应的 Dashboard 项及记录时间戳。

使用示例：
    >>> log_res = LogRes(config)
    >>> log_res.Oil = 12345  # 自动更新 Dashboard.Oil.Value 和记录时间
    >>> log_res.Coin = {'Value': 50000, 'Limit': 99999}  # 同时记录值和上限

Dashboard 数据结构：
    Dashboard.<资源名> = {
        'Value': int,      # 当前值
        'Record': datetime, # 最后更新时间
        'Limit': int,      # 上限（可选）
    }
"""

# 此文件实现了资源变动的记录与同步功能。
# 当各项资源数值（如石油、魔方等）发生变化时，负责更新配置文件中对应的 Dashboard 项及记录时间戳。
from cached_property import cached_property
from module.logger import logger
from module.config.deep import deep_get
from datetime import datetime


class LogRes:
    """资源变动记录器。

    通过属性赋值语法动态更新 Dashboard 配置中的资源值和更新时间戳，
    并同步写入统计数据库快照。

    示例:
        LogRes(config).Oil = 12000
        LogRes(config).ActionPoint = {'Total': 200, 'Value': 150}
    """
    YellowCoin: list

    def __init__(self, config):
        """初始化资源记录器。

        Args:
            config: AzurLaneConfig 配置实例。
        """
        self.__dict__['config'] = config

    def __setattr__(self, key, value):
        """设置资源属性值，并自动同步更新 Dashboard 及历史快照。

        Args:
            key (str): 资源名称。
            value (int | dict): 资源数值，或包含 Value/Total/Limit 的字典。
        """
        if key in self.groups:
            if self.__dict__.get('_observation_enabled', True):
                self._observe(key, value)
            _key_group = f'Dashboard.{key}'
            _mod = False
            original = deep_get(self.config.data, keys=_key_group)
            if isinstance(value, int):
                if original['Value'] != value:
                    _key = _key_group + '.Value'
                    self.config.modified[_key] = value
                    _time = datetime.now().replace(microsecond=0)
                    _key_time = _key_group + f'.Record'
                    self.config.modified[_key_time] = _time
                    if key == 'YellowCoin':
                        try:
                            from module.statistics.cl1_database import db as cl1_db
                            instance_name = getattr(self.config, 'config_name', 'default')
                            cl1_db.async_add_yellow_coin_snapshot(instance_name, int(value), source='dashboard')
                        except Exception:
                            logger.exception('[日志资源] 保存金币快照失败')
                    # 记录全量资源快照
                    self._record_all_resource_snapshot({key: value})
            elif isinstance(value, dict):
                _mod = False
                for value_name, _value in value.items():
                    if _value == original[value_name]:
                        continue
                    _key = _key_group + f'.{value_name}'
                    self.config.modified[_key] = _value
                    _key_time = _key_group + f'.Record'
                    _time = datetime.now().replace(microsecond=0)
                    self.config.modified[_key_time] = _time
                    _mod = True
                if _mod:
                    if key == 'ActionPoint':
                        try:
                            from module.statistics.opsi_runtime import record_ap_snapshot
                            source = 'dashboard'
                            task = getattr(getattr(self.config, 'task', None), 'command', None)
                            if task:
                                source = task
                            # 统计口径使用始终含体力箱的总行动力，避免被 OS_ACTION_POINT_BOX_USE
                            # 的临时关闭（如防止行动力溢出任务）污染快照
                            ap_total = getattr(self.config, '_action_point_total_with_box', None)
                            if ap_total is None:
                                ap_total = value.get('Total')
                            record_ap_snapshot(
                                self.config,
                                ap_current=value.get('Value'),
                                ap_total=ap_total,
                                source=source,
                            )
                        except Exception:
                            logger.exception('保存行动力快照失败')
                    # 记录全量资源快照
                    value_to_record = value.get('Value') if isinstance(value, dict) else None
                    if value_to_record is not None:
                        self._record_all_resource_snapshot({key: value_to_record})
                    else:
                        self._record_all_resource_snapshot()
        else:
            logger.info('[日志资源] 仪表盘中无此资源')
            super().__setattr__(name=key, value=value)

    def record(self, name, value, *, observed=True, source=None):
        """缓存回退与失败读数可以保留旧记录，但不能更新成功观察时间。"""
        self.__dict__['_observation_enabled'] = observed
        self.__dict__['_observation_source'] = source
        try:
            setattr(self, name, value)
        finally:
            self.__dict__.pop('_observation_enabled', None)
            self.__dict__.pop('_observation_source', None)

    def _observe(self, name, value):
        from pathlib import Path
        from module.config.utils import filepath_config
        instance = getattr(self.config, 'config_name', None)
        if not isinstance(instance, str) or not Path(filepath_config(instance)).exists():
            return
        current = value.get('Value') if isinstance(value, dict) else value
        if type(current) not in (int, float) or current < 0 or (current == 0 and '_observation_enabled' not in self.__dict__):
            return
        from module.scheduler.store import ProgramStore
        from module.config.time_source import now
        task = getattr(getattr(self.config, 'task', None), 'command', None)
        source = self.__dict__.get('_observation_source') or task or 'task_observation'
        ProgramStore().observe(instance, name, value, now().isoformat(sep=' '), source)

    def _record_all_resource_snapshot(self, overrides=None):
        """读取当前所有 Dashboard 资源值并记录快照。

        Args:
            overrides (dict, optional): 需要覆盖的资源键值对。
        """
        try:
            from module.statistics.resource_stats import record_resource_snapshot
            instance_name = getattr(self.config, 'config_name', 'default')
            overrides = overrides or {}
            resources = {}
            for group_name in self.groups:
                if group_name in overrides:
                    value = overrides[group_name]
                elif f'Dashboard.{group_name}.Value' in self.config.modified:
                    value = self.config.modified[f'Dashboard.{group_name}.Value']
                else:
                    group_data = deep_get(self.config.data, f'Dashboard.{group_name}')
                    if not isinstance(group_data, dict):
                        continue
                    value = group_data.get('Value')
                if value is not None:
                    try:
                        resources[group_name] = int(value)
                    except (TypeError, ValueError):
                        pass
            record_resource_snapshot(instance_name, resources)
        except Exception:
            logger.exception('[日志资源] 记录资源快照失败')

    def group(self, name):
        """获取指定资源的 Dashboard 数据。

        Args:
            name (str): 资源名称。

        Returns:
            dict: 包含 Value、Record 等字段的数据字典。
        """
        return deep_get(self.config.data, f'Dashboard.{name}')

    @cached_property
    def groups(self) -> dict:
        """获取仪表盘中定义的所有资源组字典。

        Returns:
            dict: 仪表盘资源配置字典。
        """
        from module.config.utils import read_file, filepath_argument
        return deep_get(d=read_file(filepath_argument("dashboard")), keys='Dashboard')

    """
    def log_res(self, name, modified: dict, update=True):
        if name in self.groups:
            key = f'Dashboard.{name}'
            original = deep_get(self.config.data, keys=key)
            _mod = False
            for value_name, value in modified.items():
                if value == original[value_name]:
                    continue
                _key = key + f'.{value_name}'
                self.config.modified[_key] = value
                _mod = True
            if _mod:
                _key_time = key + f'.Record'
                _time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self.config.modified[_key_time] = _time
                if update:
                    self.config.update()
        else:
            logger.warning('[日志资源] 没有此资源！')
        return True
        """
if __name__ == '__main__':
    from module.config.config import AzurLaneConfig
    config = AzurLaneConfig('alas2')
    LogRes(config=config).ActionPoint = {'Total': 99999, 'Value': 99999}
    config.update()
    exit(0)
