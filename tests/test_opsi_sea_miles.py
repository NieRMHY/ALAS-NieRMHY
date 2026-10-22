"""海里检测间隔、旧配置迁移及重启持久化回归，不连接游戏设备。"""

import json
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.api.config_service import ConfigService, ROOT
from module.api.protocol import ApiError, ConfigChange
from module.config.config import AzurLaneConfig, Function
from module.config.config_updater import ConfigUpdater
from module.config.deep import deep_get, deep_set
from module.os.tasks.hazard_leveling import OpsiHazard1Leveling
from module.os.tasks.task_context import opsi_task_context


SEA_MILES_PATH = 'OpsiHazard1Leveling.OpsiHazard1Leveling.RecordSeaMiles'
LAST_RECORD_PATH = 'OpsiHazard1Leveling.OpsiHazard1Leveling.SeaMilesLastRecord'


class SeaMilesIntervalTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 16, 12)
        self.runner = OpsiHazard1Leveling.__new__(OpsiHazard1Leveling)
        self.runner.config = SimpleNamespace(
            OpsiHazard1Leveling_RecordSeaMiles=-1,
            OpsiHazard1Leveling_SeaMilesLastRecord=None,
            OpsiHazard1Leveling_TargetZone=0,
            OpsiFleet_Fleet=1,
            override=Mock(),
            is_task_enabled=Mock(return_value=False),
            # 单轮入口会读隐藏的事件续查记录，桩配置保持无待续查。
            cross_get=Mock(return_value=None),
            cross_set=Mock(),
        )
        self.runner.zone = SimpleNamespace(zone_id=22, hazard_level=1)
        self.runner.is_zone_name_hidden = True
        clock = patch('module.os.tasks.hazard_leveling.current_time', return_value=self.now)
        clock.start()
        self.addCleanup(clock.stop)

    def run_once(self, result=123456, error=None):
        """走真实单轮入口，只替换设备交互和统计提交。"""
        with (
            patch.object(self.runner, '_prepare_scheduling_action_point', return_value=(1000, 120)),
            patch.object(self.runner, 'get_current_zone'),
            patch.object(self.runner, 'fleet_set'),
            patch.object(self.runner, 'is_running_smart_scheduling_task', return_value=True),
            patch.object(self.runner, 'detect_and_record_sea_miles', return_value=result,
                         side_effect=error) as detect,
            patch.object(self.runner, '_record_ap_and_coins') as record,
            patch.object(self.runner, '_cl1_run_battle') as battle,
        ):
            self.runner.run_hazard1_leveling_once(ap_preserve=0)
        battle.assert_called_once()
        return detect, record

    def test_disabled_skips_detection_but_keeps_resource_recording_and_battle(self):
        detect, record = self.run_once()
        detect.assert_not_called()
        record.assert_called_once_with(sea_miles=None)
        self.assertIsNone(self.runner.config.OpsiHazard1Leveling_SeaMilesLastRecord)

    def test_zero_detects_every_round(self):
        self.runner.config.OpsiHazard1Leveling_RecordSeaMiles = 0
        for _ in range(2):
            detect, record = self.run_once()
            detect.assert_called_once()
            record.assert_called_once_with(sea_miles=123456)
            self.assertEqual(self.runner.config.OpsiHazard1Leveling_SeaMilesLastRecord, self.now)

    def test_positive_interval_detects_immediately_without_previous_success(self):
        self.runner.config.OpsiHazard1Leveling_RecordSeaMiles = 3
        self.run_once()[0].assert_called_once()
        detect, record = self.run_once()
        detect.assert_not_called()
        record.assert_called_once_with(sea_miles=None)

    def test_full_days_boundary_and_changed_interval(self):
        self.runner.config.OpsiHazard1Leveling_SeaMilesLastRecord = self.now - timedelta(days=2)
        for interval, expected in ((3, False), (2, True), (1, True), (10**12, False)):
            with self.subTest(interval=interval):
                self.runner.config.OpsiHazard1Leveling_RecordSeaMiles = interval
                self.assertEqual(self.runner._sea_miles_record_due(), expected)
        self.runner.config.OpsiHazard1Leveling_RecordSeaMiles = 2
        self.runner.config.OpsiHazard1Leveling_SeaMilesLastRecord += timedelta(seconds=1)
        self.assertFalse(self.runner._sea_miles_record_due())

    def test_failed_detection_does_not_start_a_new_interval(self):
        self.runner.config.OpsiHazard1Leveling_RecordSeaMiles = 2
        last_record = self.now - timedelta(days=3)
        self.runner.config.OpsiHazard1Leveling_SeaMilesLastRecord = last_record
        for error in (None, RuntimeError('离线识别失败')):
            with self.subTest(error=error):
                detect, record = self.run_once(result=None, error=error)
                detect.assert_called_once()
                record.assert_called_once_with(sea_miles=None)
                self.assertEqual(self.runner.config.OpsiHazard1Leveling_SeaMilesLastRecord, last_record)
                self.assertTrue(self.runner._sea_miles_record_due())


class SeaMilesConfigTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix='sea-miles-config-')
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        for relative in (
            'module/config/argument/args.json', 'module/config/argument/menu.json',
            'module/config/i18n/zh-CN.json', 'config/template.json',
        ):
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, target)
        self.path = self.root / 'config/sea_miles.json'
        shutil.copyfile(self.root / 'config/template.json', self.path)
        self.service = ConfigService(self.root)

    def test_runner_migrates_booleans_and_preserves_numeric_values_on_reload(self):
        updater = ConfigUpdater()
        for old, expected in (
            (True, 0), (False, -1), ([], -1), ([True], 0), ([False], -1),
            (None, -1), (-1, -1), (0, 0), (1, 1), (7, 7),
        ):
            with self.subTest(old=old):
                data = {'OpsiHazard1Leveling': {'OpsiHazard1Leveling': {'RecordSeaMiles': old}}}
                migrated = updater.config_update(data)
                self.assertEqual(deep_get(migrated, SEA_MILES_PATH), expected)
                self.assertIs(type(deep_get(migrated, SEA_MILES_PATH)), int)
                self.assertEqual(deep_get(updater.config_update(migrated), SEA_MILES_PATH), expected)
        self.assertEqual(deep_get(updater.config_update({}), SEA_MILES_PATH), -1)

    def test_webui_migrates_before_runner_start_without_writing_on_read(self):
        for old, expected in (
            (True, 0), (False, -1), ([], -1), ([True], 0), ([False], -1),
            (None, -1), (-1, -1), (0, 0), (4, 4),
        ):
            with self.subTest(old=old):
                data = self.service.read_json(self.path)
                deep_set(data, SEA_MILES_PATH, old)
                self.path.write_text(json.dumps(data), encoding='utf-8')
                before = self.path.read_bytes()
                values, revision = self.service.read('sea_miles')
                self.assertEqual(deep_get(values, SEA_MILES_PATH), expected)
                self.assertIs(type(deep_get(values, SEA_MILES_PATH)), int)
                self.assertEqual(self.path.read_bytes(), before)
                self.service.patch('sea_miles', revision, [ConfigChange(path=SEA_MILES_PATH, value=3)])
                self.assertEqual(deep_get(self.service.read_json(self.path), SEA_MILES_PATH), 3)

    def test_schema_defaults_and_strict_integer_validation(self):
        field = deep_get(self.service.args, SEA_MILES_PATH)
        self.assertEqual((field['type'], field['value']), ('input', -1))
        self.assertNotIn('option', field)
        for value in (-1, 0, 1, 7, 365):
            self.service.validate(SEA_MILES_PATH, value)
        for value in (-2, 1.5, True, False, '2', None):
            with self.subTest(value=value), self.assertRaises(ApiError):
                self.service.validate(SEA_MILES_PATH, value)
        with self.assertRaises(ApiError):
            self.service.validate(LAST_RECORD_PATH, '2026-10-16 12:00:00')

    def test_success_time_persists_across_restart_and_scheduling_task_context(self):
        now = datetime(2026, 10, 16, 12)
        deep_set(data := self.service.read_json(self.path), SEA_MILES_PATH, 2)
        self.path.write_text(json.dumps(data), encoding='utf-8')
        # 配置初始化和自动保存只访问临时实例，使用真实的迁移、绑定与事务写入。
        with (
            patch('module.config.config.filepath_config', return_value=str(self.path)),
            patch('module.config.config_updater.filepath_config', return_value=str(self.path)),
            patch('module.config.config.current_time', return_value=now),
        ):
            config = AzurLaneConfig('sea_miles', task='OpsiHazard1Leveling')
            config.OpsiHazard1Leveling_SeaMilesLastRecord = now
            restarted = AzurLaneConfig('sea_miles', task='OpsiHazard1Leveling')
            self.assertEqual(restarted.OpsiHazard1Leveling_SeaMilesLastRecord, now)
            runner = OpsiHazard1Leveling.__new__(OpsiHazard1Leveling)
            runner.config = restarted
            with patch('module.os.tasks.hazard_leveling.current_time', return_value=now + timedelta(days=1)):
                self.assertFalse(runner._sea_miles_record_due())
            scheduled = AzurLaneConfig('sea_miles', task='OpsiScheduling')
            task = Function(scheduled.data['OpsiHazard1Leveling'])
            with opsi_task_context(scheduled, task, bind_task='OpsiHazard1Leveling', disable_task_switch=True):
                scheduled.OpsiHazard1Leveling_SeaMilesLastRecord = now + timedelta(days=2)
            self.assertEqual(scheduled.task.command, 'OpsiScheduling')
            restarted = AzurLaneConfig('sea_miles', task='OpsiHazard1Leveling')
            self.assertEqual(restarted.OpsiHazard1Leveling_SeaMilesLastRecord, now + timedelta(days=2))


if __name__ == '__main__':
    unittest.main()
