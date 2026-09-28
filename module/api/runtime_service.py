"""运行状态、日志和截图适配层，浏览器断开不会停止任务。"""
import io
import re
import threading
from datetime import datetime, timedelta

from rich.console import Console

from module.api.protocol import ApiError
from module.runtime.process_manager import ProcessManager

STATES = {1: 'running', 2: 'stopped', 3: 'error', 4: 'updating'}


def timeline_latest(timeline: list[dict], field: str) -> dict:
    """获取时间线中指定字段按时间最近的一个非空值所在记录。

    时间线末尾的数据点未必包含该字段，因此向前查找最新记录。

    Args:
        timeline: 时间线记录列表。
        field: 目标属性字段名称。

    Returns:
        dict: 匹配到的最新记录字典；若不存在则返回空字典。
    """
    best = None
    for row in timeline:
        if row.get(field) is None:
            continue
        if best is None or (row.get('ts') or '') >= (best.get('ts') or ''):
            best = row
    return best or {}


def monthly_statistics_resources(instance: str) -> list[dict]:
    """获取大世界总览本月累计统计资源（海里数与行动力资产）。

    Args:
        instance: 配置实例名称。

    Returns:
        list[dict]: 格式化后的资源字典列表。
    """
    from module.config.time_source import now as current_time
    from module.statistics.opsi_month import get_ap_timeline

    today = current_time()
    timeline = get_ap_timeline(today.year, today.month, instance)
    if not timeline:
        return []
    distance = timeline_latest(timeline, 'distance')
    asset = timeline_latest(timeline, 'asset')
    return [
        {'name': 'Distance', 'label': '海里数', 'value': distance.get('distance'),
         'limit': None, 'total': None, 'record': str(distance.get('ts', '')).replace('T', ' ')[:19]},
        {'name': 'ActionAsset', 'label': '行动力资产', 'value': asset.get('asset'),
         'limit': None, 'total': None, 'record': str(asset.get('ts', '')).replace('T', ' ')[:19]},
    ]


class RuntimeService:
    """运行时管理服务。

    提供多实例进程状态查询、启动停止控制、日志流缓存以及运行截图适配。

    Attributes:
        configs: 配置管理服务实例。
        logs_cache: 各实例日志游标及历史项缓存。
        lock: 日志缓存访问的可重入互斥锁。
    """

    def __init__(self, configs):
        """初始化运行时管理服务。

        Args:
            configs: 配置服务实例。
        """
        self.configs = configs
        self.logs_cache = {}
        self.lock = threading.RLock()

    def manager(self, instance: str) -> ProcessManager:
        """获取指定实例的进程管理器。

        Args:
            instance: 实例名称。

        Returns:
            ProcessManager: 进程管理器实例。
        """
        self.configs.path(instance)
        return ProcessManager.get_manager(instance)

    def instances(self) -> list[dict]:
        """获取所有配置实例的状态列表。

        Returns:
            list[dict]: 包含实例名、运行状态、当前任务、模拟器序列号及服务器信息的列表。
        """
        result = []
        for name in self.configs.names():
            data, _ = self.configs.read(name)
            emulator = data.get('Alas', {}).get('Emulator', {})
            manager = ProcessManager._processes.get(name)
            result.append({'name': name, 'status': STATES.get(manager.state, 'stopped') if manager else 'stopped',
                           'currentTask': getattr(manager, 'current_task', None) if manager and manager.state == 1 else None,
                           'serial': emulator.get('Serial', 'auto'), 'server': emulator.get('ServerName', 'cn')})
        return result

    def overview(self, instance: str) -> dict:
        """获取指定实例的总览信息。

        汇总实例的运行状态、任务队列计划、看板统计资源及模拟器配置。

        Args:
            instance: 实例名称。

        Returns:
            dict: 实例总览数据字典。
        """
        data, revision = self.configs.read(instance)
        manager = ProcessManager._processes.get(instance)
        tasks = []
        from module.config.time_source import now as current_time
        now = current_time().isoformat(sep=' ')
        running = getattr(manager, 'current_task', None) if manager and manager.state == 1 else None
        for task, groups in data.items():
            scheduler = groups.get('Scheduler', {})
            if scheduler.get('Enable') or task == running:
                next_run = str(scheduler.get('NextRun', ''))
                tasks.append({'name': task, 'nextRun': next_run, 'pending': next_run.replace('T', ' ') <= now,
                              'state': 'running' if task == running else 'pending' if next_run.replace('T', ' ') <= now else 'waiting'})
        from module.config.task_priority import parse_task_priority
        priority = parse_task_priority(data.get('General', {}).get('YukikazeTaskManager', {}).get('TaskPriorityAdjustment'))
        order = {task: index for index, task in enumerate(priority)}
        tasks.sort(key=lambda item: (-1, 0) if item['state'] == 'running' else
                   (0, order.get(item['name'], len(order))) if item['pending'] else (1, item['nextRun']))
        resources = [{'name': name, 'label': self.configs.translate(f'{name}._info.name'),
                      'value': values.get('Value'), 'limit': values.get('Limit'), 'total': values.get('Total'),
                      'record': values.get('Record')}
                     for name, values in data.get('Dashboard', {}).items() if 'Value' in values]
        resources.extend(monthly_statistics_resources(instance))
        return {'instance': instance, 'revision': revision,
                'status': STATES.get(manager.state, 'stopped') if manager else 'stopped',
                'tasks': tasks, 'resources': resources,
                'emulator': data.get('Alas', {}).get('Emulator', {})}

    def start(self, instance: str, task: str = None) -> dict:
        """启动实例的调度器或指定独立任务。

        Args:
            instance: 实例名称。
            task: 可选的任务名称；若为 None 则启动主调度器。

        Returns:
            dict: 启动后的最新实例总览数据。

        Raises:
            ApiError: 实例已在运行 (INSTANCE_RUNNING)、任务不支持单独运行 (INVALID_PARAMS)
                或进程启动失败 (START_FAILED)。
        """
        with ProcessManager._get_lifecycle_lock(instance):
            manager = self.manager(instance)
            if manager.alive:
                raise ApiError('INSTANCE_RUNNING', '实例已在运行，请先停止当前任务')
            if task:
                from module.submodule.utils import get_available_func
                if task not in get_available_func():
                    raise ApiError('INVALID_PARAMS', '该任务不支持单独运行')
            from module.runtime.updater import updater
            manager.start(task or 'alas', ev=updater.event)
            if not manager.alive:
                raise ApiError('START_FAILED', '任务未启动，请检查服务是否正在重启')
        return self.overview(instance)

    def stop(self, instance: str) -> dict:
        """停止实例的运行。

        Args:
            instance: 实例名称。

        Returns:
            dict: 停止后的最新实例总览数据。

        Raises:
            ApiError: 进程未能全部正常终止时抛出 STOP_FAILED。
        """
        with ProcessManager._get_lifecycle_lock(instance):
            if not self.manager(instance).stop_by_user():
                raise ApiError('STOP_FAILED', '尚未确认全部工作进程停止，请检查日志后重试')
        return self.overview(instance)

    def logs(self, instance: str, after: int = 0) -> dict:
        """获取指定实例增量日志记录。

        Args:
            instance: 实例名称。
            after: 客户端当前的日志序列号游标。

        Returns:
            dict: 包含最新游标、是否重置标志及日志条目列表的字典。
        """
        self.configs.path(instance)
        with self.lock:
            manager = ProcessManager._processes.get(instance)
            renderables = list(manager.renderables) if manager else []
            # 用对象身份匹配重叠区，旧管理器裁剪日志后仍保持单调递增游标。
            cache = self.logs_cache.setdefault(instance, {'last': None, 'sequence': 0, 'entries': []})
            start = 0
            if cache['last'] is not None:
                for index in range(len(renderables) - 1, -1, -1):
                    if renderables[index] is cache['last']:
                        start = index + 1
                        break
            console = Console(file=io.StringIO(), width=160, color_system=None)
            for renderable in renderables[start:]:
                with console.capture() as capture:
                    console.print(renderable)
                content = capture.get().rstrip('\r\n')
                cache['sequence'] += 1
                match = re.search(r'\b(DEBUG|INFO|WARNING|ERROR|CRITICAL)\b', content)
                cache['entries'].append({'id': cache['sequence'], 'level': match[1] if match else 'INFO',
                                         'text': content[:12000]})
            if renderables:
                cache['last'] = renderables[-1]
            cache['entries'] = cache['entries'][-400:]
            entries = cache['entries']
            reset = after > cache['sequence'] or (entries and after < entries[0]['id'] - 1)
            return {'instance': instance, 'cursor': cache['sequence'], 'reset': bool(reset),
                    'entries': [entry for entry in entries if reset or entry['id'] > after]}

    def capture(self, instance: str) -> dict:
        """获取运行器已产生的最新一帧预览截图。

        兼容旧方法名，只返回已有帧，绝不主动触发设备截图。

        Args:
            instance: 实例名称。

        Returns:
            dict: 包含截图 Base64 数据或状态信息的字典。
        """
        self.configs.path(instance)
        from module.runtime.preview import hub
        return hub.get(instance)

    def statistics(self, instance: str, days: int, resource: str) -> dict:
        """获取指定时间范围内的资源趋势历史数据。

        Args:
            instance: 实例名称。
            days: 查询最近的天数。
            resource: 资源键名。

        Returns:
            dict: 包含资源名称、历史数据点及截断标识的统计字典。
        """
        self.configs.path(instance)
        from module.statistics.resource_stats import get_resource_timeline, RESOURCE_COLUMNS
        key = RESOURCE_COLUMNS[resource]
        cutoff = (datetime.now() - timedelta(days=days)).isoformat(sep=' ')
        rows = get_resource_timeline(instance=instance, limit=5000)
        points = [{'time': row['ts'], 'value': row.get(key)} for row in rows
                  if str(row['ts']).replace('T', ' ') >= cutoff and row.get(key) is not None]
        return {'instance': instance, 'resource': resource, 'points': points,
                'limit': 5000, 'truncated': len(rows) == 5000}
