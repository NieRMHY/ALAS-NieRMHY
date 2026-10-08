"""仓库统计运行间隔：只验证调度、配置迁移和输入校验，不连接游戏。"""

from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from module.api.config_service import ConfigService
from module.api.protocol import ApiError, ConfigChange
from module.config.config import AzurLaneConfig
from module.config.config_updater import ConfigUpdater
from module.exception import StorageStatisticsError
from module.storage.statistics import StorageStatistics
from module.storage.statistics_recognition import StorageRecognitionError
from tests.test_api import fixture


class StorageScheduleTests(unittest.TestCase):
    def setUp(self):
        self.module = __import__('module.storage.statistics', fromlist=['StorageStatistics'])
        self.task = StorageStatistics.__new__(StorageStatistics)
        self.config = self.task.config = SimpleNamespace(
            config_name='schedule_test', StorageStatistics_RunIntervalDays=7,
            Scheduler_SuccessInterval=1440, Scheduler_FailureInterval=60,
            task=SimpleNamespace(command='StorageStatistics'), cross_set=Mock())
        self.config.task_delay = lambda **kwargs: AzurLaneConfig.task_delay(self.config, **kwargs)
        self.now = datetime(2026, 10, 7, 12, 0, 0)
        self.enterContext(patch('module.config.config.current_time', return_value=self.now))
        self.enterContext(patch.object(self.module.logger, 'info'))
        self.enterContext(patch.object(self.module.logger, 'hr'))
        self.catalog = Mock(servers=['cn'], version='schedule')
        self.catalog.snapshot_items.return_value = []
        self.enterContext(patch.object(self.module, 'StorageCatalog', return_value=self.catalog))
        self.enterContext(patch.object(self.module.server, 'server', 'cn'))
        self.writer = self.enterContext(patch.object(self.module, 'save_snapshot'))
        self.task.ui_goto_storage = Mock()
        self.task._storage_enter_material = Mock()
        self.task._scan_pass = Mock(return_value=SimpleNamespace(rows=[], pages=10))

    def test_default_and_custom_days_schedule_from_successful_completion(self):
        for days in (7, 1, 14, 3650):
            with self.subTest(days=days):
                self.config.StorageStatistics_RunIntervalDays = days
                self.config.cross_set.reset_mock()
                self.task.run()
                self.config.cross_set.assert_called_once_with(
                    'StorageStatistics.Scheduler.NextRun', self.now + timedelta(days=days))
        # 保留旧配置的 1440 分钟，证明它不会截短自定义的 7/14 天间隔。
        self.assertEqual(self.config.Scheduler_SuccessInterval, 1440)

    def test_failed_scan_preserves_failure_interval_and_does_not_save(self):
        self.task._scan_pass.side_effect = StorageRecognitionError('数量无法确认')
        with self.assertRaisesRegex(StorageStatisticsError, '数量无法确认'):
            self.task.run()
        self.writer.assert_not_called()
        self.config.cross_set.assert_called_once_with(
            'StorageStatistics.Scheduler.NextRun', self.now + timedelta(minutes=60))

    def test_invalid_local_interval_stops_before_scanning(self):
        for value in (0, -1, True, 1.5, '7', 3651):
            with self.subTest(value=value):
                self.config.StorageStatistics_RunIntervalDays = value
                self.config.cross_set.reset_mock()
                with self.assertRaisesRegex(StorageStatisticsError, '整数天数'):
                    self.task.run()
                self.config.cross_set.assert_called_once_with(
                    'StorageStatistics.Scheduler.NextRun', self.now + timedelta(minutes=60))
        self.task.ui_goto_storage.assert_not_called()
        self.task._scan_pass.assert_not_called()
        self.writer.assert_not_called()

    def test_legacy_configuration_gets_seven_day_default_and_preserves_schedule(self):
        updater = ConfigUpdater()
        template = json.loads(Path('config/template.json').read_text(encoding='utf-8'))
        task = template['StorageStatistics']
        task.pop('StorageStatistics')
        task['Scheduler'].update(Enable=True, NextRun='2026-10-09 12:00:00')
        migrated = updater.config_update(template)
        self.assertEqual(migrated['StorageStatistics']['StorageStatistics']['RunIntervalDays'], 7)
        self.assertTrue(migrated['StorageStatistics']['Scheduler']['Enable'])
        self.assertEqual(migrated['StorageStatistics']['Scheduler']['NextRun'], datetime(2026, 10, 9, 12, 0, 0))

    def test_api_reads_saves_and_validates_interval_in_temporary_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            service = ConfigService(fixture(directory))
            path = 'StorageStatistics.StorageStatistics.RunIntervalDays'
            self.assertEqual(service.get('testpilot')['values']['StorageStatistics']['StorageStatistics']['RunIntervalDays'], 7)
            for days in (1, 14, 3650):
                result = service.patch('testpilot', None, [ConfigChange(path=path, value=days)])
                self.assertEqual(result['values']['StorageStatistics']['StorageStatistics']['RunIntervalDays'], days)
            for value in (0, -1, True, 1.5, '7', 3651):
                with self.subTest(value=value), self.assertRaises(ApiError):
                    service.validate(path, value)

    def test_generated_default_task_group_and_all_translations_exist(self):
        from module.config.config_generated import GeneratedConfig
        self.assertEqual(GeneratedConfig.StorageStatistics_RunIntervalDays, 7)
        args = json.loads(Path('module/config/argument/args.json').read_text(encoding='utf-8'))
        field = args['StorageStatistics']['StorageStatistics']['RunIntervalDays']
        self.assertEqual(field['value'], 7)
        self.assertEqual(field['validate'], [1, 3650])
        self.assertNotEqual(field.get('display'), 'hide')
        for language in ('zh-CN', 'en-US', 'ja-JP', 'zh-TW'):
            data = json.loads(Path(f'module/config/i18n/{language}.json').read_text(encoding='utf-8'))
            field = data['StorageStatistics']['RunIntervalDays']
            self.assertTrue(field['name'])
            self.assertIn('7', field['help'])
            self.assertNotIn('StorageStatistics.RunIntervalDays', field['help'])


if __name__ == '__main__':
    unittest.main()
