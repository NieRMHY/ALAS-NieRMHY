"""运行状态、日志和截图适配层，浏览器断开不会停止任务。"""
import io
import re
import threading
from datetime import datetime, timedelta

from rich.console import Console

from module.api.protocol import ApiError
from module.runtime.process_manager import ProcessManager

STATES = {1: 'running', 2: 'stopped', 3: 'error', 4: 'updating'}


class RuntimeService:
    def __init__(self, configs):
        self.configs = configs
        self.logs_cache = {}
        self.lock = threading.RLock()

    def manager(self, instance):
        self.configs.path(instance)
        return ProcessManager.get_manager(instance)

    def instances(self):
        result = []
        for name in self.configs.names():
            data, _ = self.configs.read(name)
            emulator = data.get('Alas', {}).get('Emulator', {})
            manager = ProcessManager._processes.get(name)
            result.append({'name': name, 'status': STATES.get(manager.state, 'stopped') if manager else 'stopped',
                           'currentTask': getattr(manager, 'current_task', None) if manager and manager.state == 1 else None,
                           'serial': emulator.get('Serial', 'auto'), 'server': emulator.get('ServerName', 'cn')})
        return result

    def overview(self, instance):
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
        return {'instance': instance, 'revision': revision,
                'status': STATES.get(manager.state, 'stopped') if manager else 'stopped',
                'tasks': tasks, 'resources': resources,
                'emulator': data.get('Alas', {}).get('Emulator', {})}

    def start(self, instance, task=None):
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

    def stop(self, instance):
        with ProcessManager._get_lifecycle_lock(instance):
            if not self.manager(instance).stop_by_user():
                raise ApiError('STOP_FAILED', '尚未确认全部工作进程停止，请检查日志后重试')
        return self.overview(instance)

    def logs(self, instance, after=0):
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

    def capture(self, instance):
        """兼容旧方法名，只返回运行器已产生的最新帧，绝不主动截图。"""
        self.configs.path(instance)
        from module.runtime.preview import hub
        return hub.get(instance)

    def statistics(self, instance, days, resource):
        self.configs.path(instance)
        from module.statistics.resource_stats import get_resource_timeline, RESOURCE_COLUMNS
        key = RESOURCE_COLUMNS[resource]
        cutoff = (datetime.now() - timedelta(days=days)).isoformat(sep=' ')
        rows = get_resource_timeline(instance=instance, limit=5000)
        points = [{'time': row['ts'], 'value': row.get(key)} for row in rows
                  if str(row['ts']).replace('T', ' ') >= cutoff and row.get(key) is not None]
        return {'instance': instance, 'resource': resource, 'points': points,
                'limit': 5000, 'truncated': len(rows) == 5000}
