"""启动时记忆运行：开关与记忆的落盘、退出时的记录、启动时的合并。"""
import json
import os
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from starlette.testclient import TestClient

from module.api import lifecycle
from module.api.app import create_app
from module.runtime import startup_memory
from module.runtime.setting import State
from module.runtime.task_handler import TaskHandler
from tests.test_api import fixture


class StartupMemoryStoreTests(unittest.TestCase):
    """落盘与读取；用临时目录充当部署配置所在处。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'config').mkdir()
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(
            State, '_deploy_config_',
            SimpleNamespace(file=self.root / 'config' / 'deploy.yaml'), create=True))

    @property
    def memory_file(self) -> Path:
        return self.root / 'config' / 'startup_memory.json'

    def test_memory_path_follows_deploy_config(self):
        self.assertEqual(self.memory_file, startup_memory.memory_path())

    def test_remember_flag_round_trip(self):
        self.assertFalse(startup_memory.get_startup_remember('demo'))
        self.assertTrue(startup_memory.set_startup_remember('demo', True))
        self.assertTrue(startup_memory.get_startup_remember('demo'))
        self.assertFalse(startup_memory.set_startup_remember('demo', False))
        self.assertFalse(startup_memory.get_startup_remember('demo'))

    def test_memory_survives_reload(self):
        startup_memory.set_startup_remember('demo', True)
        startup_memory.record_running(['demo', 'other'])
        self.assertEqual(['demo'], startup_memory.remembered_runs())
        self.assertEqual({'remember': ['demo'], 'last': ['demo']},
                         json.loads(self.memory_file.read_text(encoding='utf-8')))

    def test_update_restart_follows_memory_instead_of_configured(self):
        startup_memory.set_startup_remember('demo', True)
        startup_memory.record_running([])
        self.assertEqual([], startup_memory.startup_runs(['demo'], update_restart=True))
        self.assertEqual(['demo'], startup_memory.startup_runs(['demo']))

    def test_update_restart_restores_remembered_instance(self):
        startup_memory.set_startup_remember('demo', True)
        startup_memory.record_running(['demo'])
        self.assertEqual(['demo'], startup_memory.startup_runs([], update_restart=True))

    def test_update_restart_keeps_instances_without_memory(self):
        startup_memory.record_running([])
        self.assertEqual(['demo'], startup_memory.startup_runs(['demo'], update_restart=True))

    def test_update_restart_mark_lives_in_cache(self):
        marker = self.root / 'cache' / startup_memory.UPDATE_RESTART_NAME
        self.assertEqual(marker, startup_memory.update_restart_path())
        startup_memory.mark_update_restart()
        self.assertTrue(marker.is_file())
        self.assertFalse((self.root / 'config' / startup_memory.UPDATE_RESTART_NAME).exists())

    def test_update_restart_mark_is_consumed_once(self):
        startup_memory.mark_update_restart()
        self.assertTrue(startup_memory.consume_update_restart())
        self.assertFalse(startup_memory.consume_update_restart())

    def test_record_writes_nothing_when_nobody_enabled(self):
        startup_memory.record_running(['demo'])
        self.assertFalse(self.memory_file.exists())

    def test_turning_off_after_recording_stops_resuming(self):
        startup_memory.set_startup_remember('demo', True)
        startup_memory.record_running(['demo'])
        startup_memory.set_startup_remember('demo', False)
        self.assertEqual([], startup_memory.remembered_runs())

    def test_broken_file_means_disabled(self):
        self.memory_file.write_text('{不是 JSON', encoding='utf-8')
        self.assertFalse(startup_memory.get_startup_remember('demo'))
        self.assertEqual([], startup_memory.remembered_runs())

    def test_demo_mode_cannot_change_remember(self):
        with patch.dict(os.environ, {'DEMO': '1'}):
            with self.assertRaises(PermissionError):
                startup_memory.set_startup_remember('demo', True)


class StartupMemoryLifecycleTests(unittest.TestCase):
    """退出时记录、下次启动合并；只挡住真实进程，其余走真实 lifespan。"""

    def run_once(self, root, started, remember=None, run='', update_restart=False):
        def schedule():
            yield
            while True:
                yield

        settings = SimpleNamespace(Run=run, StartOcrServer=False, EnableRemoteAccess=False,
                                   DiscordRichPresence=False, file=root / 'config' / 'deploy.yaml')
        running = [SimpleNamespace(config_name='demo', stop=lambda: True)]
        with ExitStack() as stack:
            stack.enter_context(patch.object(State, '_deploy_config_', settings, create=True))
            stack.enter_context(patch.multiple(State, _init=False, _clearup=False, manager=None,
                                               process_registry=None, _restart_requested=False))
            stack.enter_context(patch('module.runtime.worker_registry.WORKER_REGISTRY_FILE', root / 'workers.json'))
            stack.enter_context(patch('module.runtime.worker_registry.LEGACY_WORKER_REGISTRY_FILE', root / 'old.json'))
            stack.enter_context(patch('module.runtime.updater.updater',
                                      SimpleNamespace(delay=0, schedule_update=schedule)))
            stack.enter_context(patch.object(lifecycle, 'task_handler', TaskHandler()))
            stack.enter_context(patch.object(
                lifecycle.ProcessManager, 'restart_processes',
                side_effect=lambda instances=None, ev=None: started.append(list(instances or []))))
            stack.enter_context(patch.object(lifecycle.ProcessManager, 'running_instances',
                                             return_value=running))
            if remember is not None:
                startup_memory.set_startup_remember('demo', remember)
            if update_restart:
                startup_memory.mark_update_restart()
            app = create_app(root=root, password='', mount_mcp=False)
            with TestClient(app) as client:
                self.assertEqual(200, client.get('/healthz').status_code)

    def test_update_restart_follows_memory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = fixture(directory)
            started = []
            self.run_once(root, started, remember=True, run='["demo"]', update_restart=True)
            self.assertEqual([], started[0])

    def test_full_restart_runs_configured_instance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = fixture(directory)
            started = []
            self.run_once(root, started, remember=True, run='["demo"]')
            self.assertEqual(['demo'], started[0])

    def last_recorded(self, root):
        return json.loads((root / 'config' / 'startup_memory.json').read_text(encoding='utf-8'))['last']

    def test_exit_records_and_next_start_resumes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = fixture(directory)
            started = []
            self.run_once(root, started, remember=True)
            self.assertEqual(['demo'], self.last_recorded(root))
            self.assertEqual([[]], started)

            started.clear()
            self.run_once(root, started)
            self.assertEqual([['demo']], started)

    def test_disabled_records_nothing_and_resumes_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = fixture(directory)
            started = []
            self.run_once(root, started)
            self.assertEqual([[]], started)
            self.assertFalse((root / 'config' / 'startup_memory.json').exists())
