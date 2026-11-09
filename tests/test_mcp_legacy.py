"""旧工具名兼容回归：默认端点可发现、可调用，且文本输出保持旧格式。

Add by MHY, 现有 MCP 客户端按旧名称调用并解析旧文本，因此这里逐个锁住 18 个
旧名称的输出形态；新规范工具的契约由 test_mcp_tools 覆盖。
"""
import datetime
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from module.api.config_service import ConfigService
from module.api.runtime_service import RuntimeService
from module.mcp.tools import Tools
from module.runtime.setting import State


LEGACY_NAMES = [
    'list_instances', 'get_status', 'list_tasks', 'get_task_help', 'get_resources',
    'get_config', 'update_config', 'get_recent_logs', 'start_instance', 'stop_instance',
    'get_screenshot', 'get_current_running_task', 'get_scheduler_queue', 'trigger_task',
    'clear_scheduler_queue', 'restart_emulator', 'restart_adb', 'update_alas',
]


def fixture(directory):
    root = Path(directory)
    data = {'Alas': {}, 'Dashboard': {'Oil': {'Value': 123, 'Limit': 500,
                                              'Record': '2026-11-07 10:00:00'}},
            'Main': {'Scheduler': {'Enable': False, 'NextRun': '2026-01-01 00:00:00'},
                     'Option': {'Count': 2, 'Choice': 'a'}}}
    args = {'Main': {'Scheduler': {'Enable': {'type': 'checkbox', 'value': False},
                                   'NextRun': {'type': 'datetime', 'value': '2026-01-01 00:00:00'}},
                     'Option': {'Count': {'value': 2, 'validate': [1, 5]},
                                'Choice': {'value': 'a', 'option': ['a', 'b']}}}}
    for name, value in [('config/template.json', data), ('config/demo.json', data),
                        ('module/config/argument/args.json', args),
                        ('module/config/argument/menu.json', {}),
                        ('module/config/i18n/zh-CN.json', {})]:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding='utf-8')
    return root


class LegacyToolTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = fixture(self.directory.name)
        self.configs = ConfigService(self.root)
        self.runtime = RuntimeService(self.configs)
        # 默认端点：旧名称与新规范名称并存
        self.tools = Tools(self.configs, self.runtime, allow_legacy=True)
        self.addAsyncCleanup(self.tools.close)

    async def invoke(self, name, **arguments):
        return await self.tools.call(name, arguments)

    async def text(self, name, **arguments):
        result = await self.invoke(name, **arguments)
        self.assertFalse(result.isError, result.content[0].text)
        return result.content[0].text

    def test_legacy_names_and_descriptions_are_registered(self):
        tools = {tool.name: tool for tool in self.tools.definitions()}
        self.assertLessEqual(set(LEGACY_NAMES), set(tools))
        self.assertIn('azurpilot_get_context', tools)
        self.assertEqual('获取所有 AzurPilot 实例的运行状态及详细状态 (state)',
                         tools['get_status'].description)
        self.assertIsNotNone(tools['get_status'].outputSchema)

    def test_modern_registry_still_rejects_legacy_names(self):
        modern = Tools(self.configs, self.runtime)
        self.addAsyncCleanup(modern.close)
        self.assertTrue(set(LEGACY_NAMES).isdisjoint(
            {tool.name for tool in modern.definitions()}))

    async def test_list_instances_and_status_keep_old_shapes(self):
        self.assertEqual(['demo'], json.loads(await self.text('list_instances')))
        self.assertEqual([{'instance': 'demo', 'running': False, 'state': 2}],
                         json.loads(await self.text('get_status')))

    async def test_list_tasks_returns_every_configured_task(self):
        self.assertEqual(['Main'], json.loads(await self.text('list_tasks')))

    async def test_resources_and_config_are_plain_values(self):
        resources = json.loads(await self.text('get_resources', instance='demo'))
        self.assertEqual({'label': 'Oil', 'value': 123, 'limit': 500,
                          'last_update': '2026-11-07 10:00:00'}, resources['Oil'])
        config = json.loads(await self.text('get_config', instance='demo'))
        self.assertEqual(2, config['Main']['Option']['Count'])
        task = json.loads(await self.text('get_config', instance='demo', task='Main'))
        self.assertEqual(['Scheduler', 'Option'], list(task))

    async def test_task_help_keeps_group_and_option_shape(self):
        help_text = json.loads(await self.text('get_task_help', task_name='Main'))
        self.assertEqual('Main', help_text['task_name'])
        option = help_text['groups']['Option']['arguments']
        self.assertEqual({'a': 'a', 'b': 'b'}, option['Choice']['options'])
        self.assertEqual(2, option['Count']['default'])

    async def test_update_config_reports_path_and_rejects_unknown_argument(self):
        self.assertEqual('Success: Updated Main.Option.Count to 4',
                         await self.text('update_config', instance='demo', task='Main',
                                         group='Option', arg='Count', value=4))
        self.assertEqual(4, self.configs.read('demo')[0]['Main']['Option']['Count'])
        failed = await self.invoke('update_config', instance='demo', task='Main',
                                   group='Option', arg='Missing', value=1)
        self.assertTrue(failed.isError)
        self.assertTrue(failed.content[0].text.startswith('Error: '))
        self.assertEqual('NOT_FOUND', failed.structuredContent['error']['code'])
        self.assertEqual(4, self.configs.read('demo')[0]['Main']['Option']['Count'])

    async def test_queue_trigger_clear_and_schedule_text(self):
        self.assertEqual('Success: Task Main scheduled for immediately.',
                         await self.text('trigger_task', instance='demo', task='Main'))
        self.assertTrue(self.configs.read('demo')[0]['Main']['Scheduler']['Enable'])
        queue = json.loads(await self.text('get_scheduler_queue', instance='demo'))
        self.assertEqual('Main', queue[0]['task'])
        self.assertEqual('Success: Cleared tasks: Main',
                         await self.text('clear_scheduler_queue', instance='demo'))

    async def test_clear_queue_reports_retained_readonly_tasks(self):
        data = self.configs.read('demo')[0]
        data['Main']['Scheduler']['Enable'] = True
        data['Restart'] = {'Scheduler': {'Enable': True}}
        (self.root / 'config/demo.json').write_text(json.dumps(data), encoding='utf-8')
        self.configs.args['Restart'] = {'Scheduler': {
            'Enable': {'value': True, 'display': 'readonly'}}}
        text = await self.text('clear_scheduler_queue', instance='demo')
        self.assertIn('Success: Cleared tasks: Main', text)
        self.assertIn('保留不可编辑的任务: Restart', text)

    async def test_current_running_task_returns_task_name_only(self):
        self.assertEqual('Error: Instance is not running.',
                         await self.text('get_current_running_task', instance='demo'))
        overview = {'status': 'running', 'revision': 'a' * 64,
                    'tasks': [{'name': 'Main', 'state': 'running',
                               'nextRun': '2026-11-08 12:00:00'}],
                    'resources': []}
        with patch.object(self.runtime, 'overview', Mock(return_value=overview)), \
                patch.object(self.runtime, 'logs', Mock(return_value={
                    'cursor': 0, 'reset': False, 'entries': []})):
            self.assertEqual('Main', await self.text('get_current_running_task',
                                                     instance='demo'))

    async def test_recent_logs_reads_tail_of_instance_log(self):
        log = self.root / 'log' / f'{datetime.date.today()}_demo.txt'
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text('第一行\n第二行\n第三行\n', encoding='utf-8')
        with patch.object(self.runtime, 'logs', Mock(return_value={
                'cursor': 3, 'reset': False, 'entries': []})):
            self.assertEqual('第二行\n第三行\n',
                             await self.text('get_recent_logs', instance='demo', lines=2))

    async def test_screenshot_returns_image_content_only(self):
        raw = {'image': 'YWJj', 'frame_id': 'f' * 32, 'width': 1280, 'height': 720,
               'orientation': 'landscape', 'captured_at': '2026-11-08T10:00:00+00:00',
               'cached': False, 'backend': 'ADB'}
        with patch('module.mcp.tools.run_device', return_value=raw):
            result = await self.invoke('get_screenshot', instance='demo')
        self.assertEqual(1, len(result.content))
        self.assertEqual(('image', 'image/jpeg', 'YWJj'),
                         (result.content[0].type, result.content[0].mimeType,
                          result.content[0].data))

    async def test_lifecycle_and_update_keep_old_text(self):
        stopped = {'status': 'stopped', 'tasks': []}
        with patch.object(self.runtime, 'start', Mock(return_value={'status': 'running', 'tasks': []})), \
                patch.object(self.runtime, 'stop', Mock(return_value=stopped)):
            self.assertEqual('Success: Started demo (alas)',
                             await self.text('start_instance', instance='demo'))
            self.assertEqual('Success: Stopped demo',
                             await self.text('stop_instance', instance='demo'))
        with patch.object(State, 'restart_event', threading.Event()), \
                patch.object(State, 'dependency_sync_event', threading.Event()), \
                patch('module.mcp.tools.update_service.start', return_value={'accepted': True}):
            self.assertEqual('Success: Triggered AzurPilot update in background.',
                             await self.text('update_alas'))

    async def test_restart_tools_report_old_text(self):
        with patch('module.mcp.tools.run_device',
                   return_value={'text': 'Restarted emulator for demo'}):
            self.assertEqual('Success: Restarted emulator for demo',
                             await self.text('restart_emulator', instance='demo'))
        with patch('module.mcp.tools.run_device',
                   return_value={'adb_path': '/usr/bin/adb', 'devices': ['127.0.0.1:5555'],
                                 'reconnected': ['127.0.0.1:5555']}):
            self.assertEqual('Success: Restarted ADB service using /usr/bin/adb.',
                             await self.text('restart_adb'))


if __name__ == '__main__':
    unittest.main()
