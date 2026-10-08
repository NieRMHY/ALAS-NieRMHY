"""大世界模拟器的后台运行与独立日志缓冲，不接触游戏进程。"""

import base64
import logging
import threading
from collections import deque
from pathlib import Path

from module.config.deep import deep_get


class SimulatorConfig:
    """只读配置快照，避免加载 AzurLaneConfig 时迁移或保存用户配置。"""

    def __init__(self, instance, data):
        self.config_name = instance
        self.data = data

    def load(self):
        """每次启动已重新读取配置，运行期间沿用同一份快照。"""

    def cross_get(self, keys, default=None):
        return deep_get(self.data, keys, default)


class SimulatorLogs(logging.Handler):
    """按实例保存有界日志，游标在多次模拟间持续递增。"""

    def __init__(self):
        super().__init__()
        self.entries = deque(maxlen=400)
        self.cursor = self.floor = 0
        self.setFormatter(logging.Formatter(
            '%(levelname)-8s %(asctime)s.%(msecs)03d │ %(message)s', '%Y-%m-%d %H:%M:%S'))

    def emit(self, record):
        self.cursor += 1
        self.entries.append({'id': self.cursor, 'level': record.levelname,
                             'text': self.format(record)[:2000]})

    def clear(self):
        with self.lock:
            self.entries.clear()
            self.floor = self.cursor

    def snapshot(self, instance, after=0):
        with self.lock:
            reset = after <= self.floor or after > self.cursor or (
                bool(self.entries) and after < self.entries[0]['id'] - 1)
            return {'instance': instance, 'cursor': self.cursor, 'reset': reset,
                    'entries': [entry for entry in self.entries if reset or entry['id'] > after]}


class OSSimulatorManager:
    """让页面刷新与切换后仍可查询同一实例的模拟状态。"""

    def __init__(self, figure_directory):
        self.figure_directory = Path(figure_directory)
        self.runs = {}
        self.lock = threading.RLock()
        self.closed = False

    def start(self, instance, data):
        with self.lock:
            if self.closed:
                raise RuntimeError('模拟器服务已关闭')
            if instance not in self.runs:
                # Numba 和 matplotlib 只在首次启动模拟时加载。
                from module.os_simulator.simulator import OSSimulator
                simulator = OSSimulator(figure_directory=self.figure_directory)
                logs = SimulatorLogs()
                simulator.logger.addHandler(logs)
                self.runs[instance] = simulator, logs
            simulator, logs = self.runs[instance]
            if simulator.is_running:
                return False
            logs.clear()
            simulator.set_config(SimulatorConfig(instance, data))
            return simulator.start()

    def status(self, instance, after=0):
        with self.lock:
            run = self.runs.get(instance)
            if run is None:
                return {'instance': instance, 'state': 'idle', 'running': False,
                        'runId': 0,
                        'completedSamples': 0, 'totalSamples': 0, 'error': '',
                        'result': None, 'figure': None,
                        'logs': {'instance': instance, 'cursor': 0, 'entries': [], 'reset': True}}
            simulator, logs = run
            result = simulator.snapshot()
            result['instance'] = instance
            result['logs'] = logs.snapshot(instance, after)
            # 前端只需要图表标识，不暴露服务端文件路径。
            result['figure'] = Path(result['figure']).name if result['figure'] else None
            return result

    def stop(self, instance):
        with self.lock:
            if instance in self.runs:
                self.runs[instance][0].interrupt()

    def figure(self, instance):
        with self.lock:
            run = self.runs.get(instance)
            path = Path(run[0].figure) if run and run[0].figure else None
        if path is None or not path.is_file():
            return None
        if path.is_symlink() or path.resolve().parent != self.figure_directory.resolve():
            raise ValueError('模拟器图表路径无效')
        return 'data:image/png;base64,' + base64.b64encode(path.read_bytes()).decode('ascii')

    def discard(self, instance):
        with self.lock:
            run = self.runs.get(instance)
            if run and run[0].is_running:
                return False
            if run:
                self.runs.pop(instance)
                run[0].logger.removeHandler(run[1])
                run[1].close()
            return True

    def close(self):
        """关闭服务时通知所有模拟结束，并有界等待后台线程回收。"""
        with self.lock:
            self.closed = True
            runs = list(self.runs.items())
            for instance, _ in runs:
                self.stop(instance)
        for instance, (simulator, _) in runs:
            simulator._thread.join(timeout=5)
            self.discard(instance)
