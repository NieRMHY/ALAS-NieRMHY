"""赛季进度：仓库读数 -> 当前数量（纯逻辑，不需要设备）。

背景：赛季页 OCR 会把拿铁的 82 误读成 282 并错发达标邮件，所以改成每次收取生产、
核对销售时直接用仓库读数。读数是准确的库存，直接覆盖「当前数量」。
"""
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, '.')

from module.island import island_season_progress as P
from module.island.island_economy import ECONOMY_PRODUCTS

SHOP_ITEMS = set(ECONOMY_PRODUCTS)


class TestParseAndFormat(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(P.parse_progress_text('latte=82/100\nsalad = 100 / 100'),
                         {'latte': [82, 100], 'salad': [100, 100]})

    def test_comments_and_garbage_skipped(self):
        text = '# 说明\nlatte=82/100  # 行内注释\nbad line\nfoo=1\nbar=x/y\n=3/4'
        self.assertEqual(P.parse_progress_text(text), {'latte': [82, 100]})

    def test_empty_and_none(self):
        self.assertEqual(P.parse_progress_text(''), {})
        self.assertEqual(P.parse_progress_text(None), {})

    def test_negative_clamped(self):
        self.assertEqual(P.parse_progress_text('latte=-5/100'), {'latte': [0, 100]})

    def test_roundtrip(self):
        progress = {'salad': [100, 100], 'latte': [82, 100]}
        self.assertEqual(P.parse_progress_text(P.format_progress_text(progress)), progress)


class TestDefaults(unittest.TestCase):
    def test_only_shop_items(self):
        """材料类（小麦/牛奶等）不需要规划，不进进度。"""
        defaults = P.default_progress('autumn', SHOP_ITEMS)
        self.assertEqual(defaults['latte'], [0, 100])
        self.assertEqual(defaults['steak_bowl'], [0, 50])
        self.assertNotIn('wheat', defaults)
        self.assertNotIn('milk', defaults)

    def test_unknown_season(self):
        self.assertEqual(P.default_progress('winter', SHOP_ITEMS), {})


class TestMergeReadings(unittest.TestCase):
    def test_reading_overwrites_current(self):
        """读数是仓库真实库存：直接覆盖，不累加。"""
        progress = {'latte': [10, 100]}
        changed = P.merge_readings(progress, {'latte': 82}, 'autumn', SHOP_ITEMS)
        self.assertEqual(progress['latte'], [82, 100])
        self.assertEqual(changed, {'latte': (10, 82)})

    def test_real_stock_above_need_is_kept(self):
        """蔬菜沙拉真实库存 2100：高于需求不能被封顶。"""
        progress = {}
        P.merge_readings(progress, {'salad': 2100}, 'autumn', SHOP_ITEMS)
        self.assertEqual(progress['salad'], [2100, 100])

    def test_drop_after_submit_is_reflected(self):
        progress = {'salad': [120, 100]}
        P.merge_readings(progress, {'salad': 20}, 'autumn', SHOP_ITEMS)
        self.assertEqual(progress['salad'][0], 20)

    def test_manual_need_is_preserved(self):
        """需求数量可以手动改，读数只动当前数量。"""
        progress = {'latte': [0, 150]}
        P.merge_readings(progress, {'latte': 82}, 'autumn', SHOP_ITEMS)
        self.assertEqual(progress['latte'], [82, 150])

    def test_non_season_items_ignored(self):
        """顾客商品（不在赛季任务里）的读数不进进度。"""
        progress = {}
        changed = P.merge_readings(progress, {'tofu': 310, 'cheese': 6}, 'autumn', SHOP_ITEMS)
        self.assertEqual(changed, {})
        self.assertNotIn('tofu', progress)

    def test_zero_reading_is_real(self):
        """读到 0 是真实的 0（没货），要如实记录。"""
        progress = {'latte': [82, 100]}
        P.merge_readings(progress, {'latte': 0}, 'autumn', SHOP_ITEMS)
        self.assertEqual(progress['latte'][0], 0)

    def test_unread_items_untouched(self):
        progress = {'latte': [82, 100], 'salad': [100, 100]}
        P.merge_readings(progress, {'latte': 90}, 'autumn', SHOP_ITEMS)
        self.assertEqual(progress['salad'], [100, 100])

    def test_negative_reading_ignored(self):
        """-1 表示库存未知（没有仓库模板），不能当成 0 覆盖。"""
        progress = {'latte': [82, 100]}
        P.merge_readings(progress, {'latte': -1}, 'autumn', SHOP_ITEMS)
        self.assertEqual(progress['latte'][0], 82)


class TestReadyAndGaps(unittest.TestCase):
    def test_ready_and_gaps_partition(self):
        progress = {'salad': [100, 100], 'latte': [82, 100], 'apple_juice': [300, 250]}
        self.assertEqual([i for i, _, _ in P.ready_items(progress)], ['apple_juice', 'salad'])
        self.assertEqual(P.gaps(progress), {'latte': (82, 100)})

    def test_zero_need_is_neither(self):
        progress = {'latte': [5, 0]}
        self.assertEqual(P.ready_items(progress), [])
        self.assertEqual(P.gaps(progress), {})


class TestRecordReadings(unittest.TestCase):
    """配置读写：只在有变化时才写，避免每次读仓库都保存配置。"""

    def _config(self, text=''):
        config = MagicMock()
        store = {P.PROGRESS_KEY: text}
        config.cross_get.side_effect = lambda key, default=None: store.get(key, default)
        config.cross_set.side_effect = lambda key, value: store.__setitem__(key, value)
        config.store = store
        return config

    def test_first_reading_fills_defaults_and_saves(self):
        config = self._config()
        changed = P.record_readings(config, {'latte': 82}, 'autumn')
        self.assertEqual(changed, {'latte': (0, 82)})
        saved = P.parse_progress_text(config.store[P.PROGRESS_KEY])
        self.assertEqual(saved['latte'], [82, 100])
        self.assertEqual(saved['steak_bowl'], [0, 50], '没读到的任务按赛季数据补齐')
        config.update.assert_called_once()

    def test_no_change_does_not_save(self):
        config = self._config('latte=82/100')
        self.assertEqual(P.record_readings(config, {'latte': 82}, 'autumn'), {})
        config.cross_set.assert_not_called()
        config.update.assert_not_called()

    def test_manual_edit_survives_next_reading(self):
        """你手动改了需求数量，后面的仓库读数只会更新当前数量。"""
        config = self._config('latte=0/200')
        P.record_readings(config, {'latte': 82}, 'autumn')
        self.assertEqual(P.parse_progress_text(config.store[P.PROGRESS_KEY])['latte'], [82, 200])

    def test_empty_readings_or_season_is_noop(self):
        config = self._config()
        self.assertEqual(P.record_readings(config, {}, 'autumn'), {})
        self.assertEqual(P.record_readings(config, {'latte': 1}, ''), {})
        config.cross_set.assert_not_called()

    def test_save_failure_does_not_raise(self):
        config = self._config()
        config.update.side_effect = RuntimeError('disk full')
        P.record_readings(config, {'latte': 82}, 'autumn')


class TestSeasonPlanTask(unittest.TestCase):
    """任务是纯逻辑：不碰设备，异常也必须排下次运行（否则会被调度器连环重启）。"""

    def _task(self, tmp):
        from module.island.island_season_plan import IslandSeasonPlan
        task = IslandSeasonPlan(config=MagicMock(), device=None)
        task.LAST_RUN_FILE = tmp
        return task

    def test_always_schedules_next_run(self):
        import os
        import tempfile
        from unittest import mock
        from module.island import island_season_plan as M

        tmp = os.path.join(tempfile.mkdtemp(), 'last.json')
        task = self._task(tmp)
        with mock.patch.object(M, 'current_progress', side_effect=RuntimeError('boom')):
            with self.assertRaises(RuntimeError):
                task.run()
        task.config.task_delay.assert_called_once_with(minute=task.DELAY_MINUTE)

    def test_ready_progress_sends_mail_and_requests_refresh(self):
        import os
        import tempfile
        from unittest import mock
        from module.island import island_season_plan as M

        tmp = os.path.join(tempfile.mkdtemp(), 'last.json')
        task = self._task(tmp)
        with mock.patch.object(M, 'SeasonConfig') as season_cls, \
                mock.patch.object(M, 'current_progress', return_value={'latte': [100, 100]}), \
                mock.patch.object(M, 'request_refresh_on_gap_change', return_value=True) as refresh, \
                mock.patch.object(M, 'notify_ready_from_progress') as notify:
            season_cls.return_value.season = 'autumn'
            task.run()
        refresh.assert_called_once_with(task.config, 'autumn')
        notify.assert_called_once_with(task.config, 'autumn', {'latte': [100, 100]})

    def test_never_touches_device(self):
        """不再进游戏：没有设备也能跑完。"""
        import os
        import tempfile
        from unittest import mock
        from module.island import island_season_plan as M

        tmp = os.path.join(tempfile.mkdtemp(), 'last.json')
        task = self._task(tmp)
        self.assertIsNone(task.device)
        with mock.patch.object(M, 'SeasonConfig') as season_cls, \
                mock.patch.object(M, 'current_progress', return_value={}), \
                mock.patch.object(M, 'request_refresh_on_gap_change', return_value=False), \
                mock.patch.object(M, 'notify_ready_from_progress'):
            season_cls.return_value.season = 'autumn'
            task.run()


if __name__ == '__main__':
    unittest.main()
