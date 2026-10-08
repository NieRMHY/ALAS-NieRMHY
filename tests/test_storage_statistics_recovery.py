"""仓库受限恢复的虚拟时间回归：不连接设备，也不读取真实用户配置。"""

from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

from module.exception import StorageStatisticsError
from module.statistics.storage_snapshot import save_snapshot
from module.storage.statistics import StorageStatistics
from module.storage.statistics_recognition import StorageCard, StorageRecognitionError


class VirtualClock:
    """按截图和操作的模拟耗时前进，继续使用真实 Timer 实现。"""

    def __init__(self):
        self.now = 100.

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class RecoveryDevice:
    """四次微调后显示末页；最后一次操作可模拟较慢后端。"""

    def __init__(self, clock):
        self.clock = clock
        self.image = np.zeros((720, 1280, 3), dtype=np.uint8)
        self.phase = 0
        self.nudges = 0
        self.frames = 0
        self.last_nudge_at = None
        self.click_record_clear = Mock()

    def swipe(self, start, end, **kwargs):
        # 端点手势只确认已经位于顶部或底部，不改变模拟材料顺序。
        if start[0] < 1235:
            self.drag(start, end, **kwargs)

    def drag(self, start, end, **kwargs):
        if start == (1180, 540):
            self.phase = 1
        else:
            self.nudges += 1
            self.phase = self.nudges + 1
            if self.nudges == 4:
                self.clock.advance(21)
            self.last_nudge_at = self.clock.now

    def screenshots(self, **kwargs):
        for _ in range(100):
            self.clock.advance(3)
            self.frames += 1
            yield self.image
        raise AssertionError('受限恢复不得无限获取截图')


class RecoveryScroll:
    """只隔离滚动条几何；稳定复读、唯一重叠和 Timer 均保留真实实现。"""

    total = 100
    length = 10

    def __init__(self, *args, **kwargs):
        pass

    def match_color(self, task):
        start = 0 if task.device.phase == 0 else 90 if task.device.phase == 5 else 30
        mask = np.zeros(self.total, dtype=bool)
        mask[start:start + self.length] = True
        return mask

    def cal_position(self, task):
        return 0. if task.device.phase == 0 else 1. if task.device.phase == 5 else .3

    def position_to_screen(self, position, *args):
        y = int(100 + position * 300)
        return 1256, y, 1265, y + 1


class StorageRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.module = __import__('module.storage.statistics', fromlist=['StorageStatistics'])
        self.clock = VirtualClock()
        self.enterContext(patch('module.base.timer.time', self.clock))
        self.enterContext(patch.object(self.module, 'Scroll', RecoveryScroll))
        self.enterContext(patch.object(self.module, 'logger'))
        self.task = StorageStatistics.__new__(StorageStatistics)
        self.task.config = SimpleNamespace(
            config_name='recovery_test', Emulator_ControlMethod='MaaTouch', task_delay=Mock())
        self.device = self.task.device = RecoveryDevice(self.clock)
        self.task.loop = self.device.screenshots
        self.task.handle_info_bar = Mock(return_value=False)
        self.task._storage_in_material = Mock(return_value=True)
        self.task.ui_goto_storage = Mock()
        self.task._storage_enter_material = Mock()
        self.catalog = SimpleNamespace(servers=['cn'], version='test')
        self.read_phases = []
        rng = np.random.default_rng(42)
        self.icons = [rng.integers(0, 256, (128, 128, 3), dtype=np.uint8) for _ in range(7)]

    def rows(self, indices):
        return [[StorageCard((130, 80 + index * 178, 258, 208 + index * 178),
                             self.icons[identity], identifier=f'item_{identity}', amount=identity + 1)]
                for index, identity in enumerate(indices)]

    def read_after_last_recovery(self, image, catalog):
        self.read_phases.append(self.device.phase)
        if self.device.phase == 0:
            return self.rows((0, 1, 2))
        if self.device.phase < 5:
            raise StorageRecognitionError('数量字形暂时无法确认')
        return self.rows((1, 2, 3))

    def test_last_allowed_recovery_gets_stable_reads_and_unique_overlap(self):
        with patch.object(self.module, 'recognize_rows', side_effect=self.read_after_last_recovery):
            result = self.task._scan_pass(self.catalog)
        self.assertEqual(self.device.nudges, 4)
        # 新页必须经过初读及两次稳定检查；不能在发出最后手势后直接接受或超时。
        self.assertGreaterEqual(self.read_phases.count(5), 3)
        self.assertEqual([row[0].identifier for row in result.rows],
                         ['item_0', 'item_1', 'item_2', 'item_3'])
        self.assertEqual(result.pages, 2)
        self.assertEqual(self.device.click_record_clear.call_count, 2)

    def test_four_failed_recoveries_stop_and_keep_old_snapshot_and_protection(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / 'warehouse.db'
            save_snapshot('recovery_test', 'cn',
                          [dict(id='old', name='旧物品', group='材料', amount=99)],
                          started_at='2026-10-01', pages=2, catalog_version='old', database=database)
            before = database.read_bytes()
            writer = self.enterContext(patch.object(self.module, 'save_snapshot'))
            self.enterContext(patch.object(self.module, 'StorageCatalog', return_value=self.catalog))
            self.enterContext(patch.object(self.module.server, 'server', 'cn'))

            def read(image, catalog):
                if self.device.phase == 0:
                    return self.rows((0, 1, 2))
                self.read_phases.append(self.device.phase)
                raise StorageRecognitionError('数量字形持续无法确认')

            with patch.object(self.module, 'recognize_rows', side_effect=read):
                with self.assertRaisesRegex(StorageStatisticsError, '数量字形持续无法确认'):
                    self.task.run()
            self.assertEqual(self.device.nudges, 4)
            self.assertGreater(self.read_phases.count(5), 0)
            self.assertLess(self.clock.now - self.device.last_nudge_at, 20)
            self.assertEqual(self.device.click_record_clear.call_count, 1)
            self.assertEqual(before, database.read_bytes())
            writer.assert_not_called()
            self.task.config.task_delay.assert_called_once_with(success=False)

    def test_slow_frames_expire_read_window_without_waiting_forty_frames(self):
        self.task._storage_in_material.return_value = False
        start = self.clock.now
        with patch.object(self.module, 'recognize_rows') as reader:
            with self.assertRaisesRegex(StorageRecognitionError, '等待材料仓库稳定'):
                self.task._scan_pass(self.catalog)
        self.assertEqual(self.clock.now - start, 21)
        self.assertEqual(self.device.frames, 7)
        self.assertEqual(self.device.nudges, 0)
        self.device.click_record_clear.assert_not_called()
        reader.assert_not_called()

    def test_slow_stable_reads_do_not_start_action_count_only_at_overlap_failure(self):
        original_drag = self.device.drag

        def drag(start, end, **kwargs):
            if start == (1180, 540):
                original_drag(start, end, **kwargs)
            else:
                self.device.nudges += 1
                self.device.phase = 5

        self.device.drag = drag

        def read(image, catalog):
            if self.device.phase == 0:
                return self.rows((0, 1, 2))
            if self.device.phase == 1:
                # 正常读取已消耗大部分窗口，首次拼接失败前仍有多个真实截图帧。
                self.clock.advance(4)
                return self.rows((4, 5, 6))
            return self.rows((1, 2, 3))

        with patch.object(self.module, 'recognize_rows', side_effect=read):
            result = self.task._scan_pass(self.catalog)
        self.assertEqual(self.device.nudges, 1)
        self.assertEqual(result.pages, 2)
        self.assertEqual([row[0].identifier for row in result.rows],
                         ['item_0', 'item_1', 'item_2', 'item_3'])


if __name__ == '__main__':
    unittest.main()
