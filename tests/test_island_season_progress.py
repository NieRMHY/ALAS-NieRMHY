"""赛季进度：配置槽位 + 仓库读数（纯逻辑，不需要设备）。

背景：赛季页 OCR 会把拿铁的 82 误读成 282 并错发达标邮件，所以改成每次收取生产、
核对销售时直接用仓库读数。清单来自 10 个配置槽位（餐品/需求/已完成）；已完成的槽位
不再排产、不再提醒，空闲产能自动转去做下一个缺口最大的。
"""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, '.')

from module.island import island_season_progress as P
from module.island.island_economy import ECONOMY_PRODUCTS

SHOP_ITEMS = set(ECONOMY_PRODUCTS)


def fake_config(slots=None, notify=True):
    """slots: [(物品, 需求, 已完成)]，从槽位 1 起依次填充。"""
    store = {P.NOTIFY_KEY: notify}
    for n, (item, need, done) in enumerate(slots or [], start=1):
        k_item, k_need, k_done = P.slot_keys(n)
        store.update({k_item: item, k_need: need, k_done: done})
    config = MagicMock()
    config.store = store
    config.cross_get.side_effect = lambda key, default=None: store.get(key, default)
    config.cross_set_many.side_effect = lambda values: store.update(values)
    return config


class TestReadSlots(unittest.TestCase):
    def test_reads_only_selected_slots(self):
        config = fake_config([('latte', 100, False), ('None', 50, False), ('salad', 100, True)])
        slots = P.read_slots(config)
        self.assertEqual([(s['n'], s['item'], s['need'], s['done']) for s in slots],
                         [(1, 'latte', 100, False), (3, 'salad', 100, True)])

    def test_bad_need_becomes_zero(self):
        config = fake_config([('latte', 'abc', False)])
        self.assertEqual(P.read_slots(config)[0]['need'], 0)

    def test_negative_need_clamped(self):
        config = fake_config([('latte', -5, False)])
        self.assertEqual(P.read_slots(config)[0]['need'], 0)

    def test_empty_config(self):
        self.assertEqual(P.read_slots(fake_config()), [])


class TestEnsureSlots(unittest.TestCase):
    def test_presets_from_season_table_when_empty(self):
        config = fake_config()
        slots = P.ensure_slots(config, 'autumn', SHOP_ITEMS)
        by_item = {s['item']: s for s in slots}
        self.assertEqual(len(slots), 8)
        self.assertEqual(by_item['latte']['need'], 100)
        self.assertEqual(by_item['steak_bowl']['need'], 50)
        self.assertNotIn('wheat', by_item, '材料类交给农田牧场，不进槽位')
        self.assertFalse(any(s['done'] for s in slots))
        config.update.assert_called_once()

    def test_does_not_overwrite_user_slots(self):
        """你选过任一槽位就不会被预置覆盖。"""
        config = fake_config([('latte', 150, False)])
        slots = P.ensure_slots(config, 'autumn', SHOP_ITEMS)
        self.assertEqual([(s['item'], s['need']) for s in slots], [('latte', 150)])
        config.cross_set_many.assert_not_called()

    def test_unknown_season_leaves_empty(self):
        config = fake_config()
        self.assertEqual(P.ensure_slots(config, 'winter', SHOP_ITEMS), [])
        config.cross_set_many.assert_not_called()

    def test_save_failure_does_not_raise(self):
        config = fake_config()
        config.update.side_effect = RuntimeError('disk full')
        self.assertEqual(len(P.ensure_slots(config, 'autumn', SHOP_ITEMS)), 8)

    def test_preset_is_idempotent(self):
        config = fake_config()
        P.ensure_slots(config, 'autumn', SHOP_ITEMS)
        config.reset_mock()
        P.ensure_slots(config, 'autumn', SHOP_ITEMS)
        config.cross_set_many.assert_not_called()


class TestDoneExcludesFromPlanning(unittest.TestCase):
    """已完成 = 不再生产、不再提醒，空闲产能转去做下一个。"""

    def setUp(self):
        self.slots = P.read_slots(fake_config([
            ('salad', 100, True),            # 提交过了
            ('latte', 100, False),
            ('steak_bowl', 50, False),
            ('iced_coffee', 0, False),       # 需求 0
        ]))

    def test_done_and_zero_need_are_inactive(self):
        self.assertEqual([s['item'] for s in P.active_slots(self.slots)],
                         ['latte', 'steak_bowl'])

    def test_done_item_not_in_progress_even_with_huge_stock(self):
        """蔬菜沙拉库存 2100：已完成不再出现在进度里，也就不会再发邮件或排产。"""
        progress = P.build_progress(self.slots, {'salad': 2100, 'latte': 82})
        self.assertNotIn('salad', progress)
        self.assertEqual(progress, {'latte': [82, 100], 'steak_bowl': [0, 50]})

    def test_done_item_stays_excluded_when_stock_drops(self):
        progress = P.build_progress(self.slots, {'salad': 3})
        self.assertNotIn('salad', progress)

    def test_unticking_done_resumes(self):
        slots = P.read_slots(fake_config([('salad', 100, False)]))
        self.assertEqual(P.build_progress(slots, {'salad': 20}), {'salad': [20, 100]})

    def test_next_gap_becomes_active_after_done(self):
        """做完一个标记完成后，缺口自然落到下一个。"""
        from module.island.island_away_cook import pick_away_cook
        before = P.read_slots(fake_config([('latte', 100, False), ('iced_coffee', 250, False)]))
        after = P.read_slots(fake_config([('latte', 100, False), ('iced_coffee', 250, True)]))
        have = {'latte': 0, 'iced_coffee': 0}
        self.assertEqual(pick_away_cook('juu_coffee', 'autumn', have, slots=before), 'iced_coffee')
        self.assertEqual(pick_away_cook('juu_coffee', 'autumn', have, slots=after), 'latte')


class TestReadyAndGaps(unittest.TestCase):
    def test_partition(self):
        progress = {'salad': [100, 100], 'latte': [82, 100], 'apple_juice': [300, 250]}
        self.assertEqual([i for i, _, _ in P.ready_items(progress)], ['apple_juice', 'salad'])
        self.assertEqual(P.gaps(progress), {'latte': (82, 100)})

    def test_zero_need_is_neither(self):
        self.assertEqual(P.ready_items({'latte': [5, 0]}), [])
        self.assertEqual(P.gaps({'latte': [5, 0]}), {})


class TestRecordReadings(unittest.TestCase):
    """仓库读数：直接覆盖，不累加、不封顶。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, 'have.json')

    def test_overwrite_not_accumulate(self):
        P.record_readings({'latte': 10}, self.path)
        P.record_readings({'latte': 82}, self.path)
        self.assertEqual(P.load_have(self.path), {'latte': 82})

    def test_real_stock_above_need_is_kept(self):
        P.record_readings({'salad': 2100}, self.path)
        self.assertEqual(P.load_have(self.path)['salad'], 2100)

    def test_zero_reading_is_real(self):
        P.record_readings({'latte': 82}, self.path)
        P.record_readings({'latte': 0}, self.path)
        self.assertEqual(P.load_have(self.path)['latte'], 0)

    def test_negative_reading_ignored(self):
        """-1 表示库存未知（没有仓库模板），不能当成 0 覆盖。"""
        P.record_readings({'latte': 82}, self.path)
        P.record_readings({'latte': -1}, self.path)
        self.assertEqual(P.load_have(self.path)['latte'], 82)

    def test_unread_items_untouched(self):
        P.record_readings({'latte': 82, 'salad': 100}, self.path)
        P.record_readings({'latte': 90}, self.path)
        self.assertEqual(P.load_have(self.path), {'latte': 90, 'salad': 100})

    def test_no_change_does_not_write(self):
        P.record_readings({'latte': 82}, self.path)
        mtime = os.path.getmtime(self.path)
        self.assertEqual(P.record_readings({'latte': 82}, self.path), {})
        self.assertEqual(os.path.getmtime(self.path), mtime)

    def test_returns_changes(self):
        P.record_readings({'latte': 10}, self.path)
        self.assertEqual(P.record_readings({'latte': 82, 'salad': 5}, self.path),
                         {'latte': (10, 82), 'salad': (None, 5)})

    def test_corrupt_file_is_empty(self):
        with open(self.path, 'w', encoding='utf-8') as f:
            f.write('{broken')
        self.assertEqual(P.load_have(self.path), {})
        P.record_readings({'latte': 1}, self.path)
        self.assertEqual(P.load_have(self.path), {'latte': 1})

    def test_state_file_not_exposed_as_instance(self):
        self.assertTrue(P.HAVE_FILE.startswith(os.path.join('config', 'island')))


class TestNotifySwitch(unittest.TestCase):
    def _run(self, config, progress):
        from unittest import mock
        from module.island import island_away_cook as away_cook
        sent = []
        config.config_name = 'ALAS'
        with mock.patch.object(away_cook, 'load_notified', return_value={}), \
                mock.patch.object(away_cook, 'save_notified'), \
                mock.patch('module.notify.notify.handle_notify',
                           side_effect=lambda *a, **k: sent.append(k) or True):
            fired = away_cook.notify_ready_from_progress(config, 'autumn', progress)
        return fired, sent

    def test_switch_off_sends_nothing(self):
        fired, sent = self._run(fake_config(notify=False), {'salad': [100, 100]})
        self.assertEqual((fired, sent), ([], []))

    def test_switch_on_sends(self):
        fired, sent = self._run(fake_config(notify=True), {'salad': [100, 100]})
        self.assertEqual(fired, ['salad'])
        self.assertEqual(len(sent), 1)

    def test_done_slot_never_reaches_notify(self):
        """已完成的槽位不在进度里，邮件函数根本看不到它。"""
        config = fake_config([('salad', 100, True), ('latte', 100, False)])
        progress = P.build_progress(P.read_slots(config), {'salad': 2100, 'latte': 82})
        fired, sent = self._run(config, progress)
        self.assertEqual((fired, sent), ([], []))


class TestSeasonPlanTask(unittest.TestCase):
    """任务是纯逻辑：不碰设备，异常也必须排下次运行（否则会被调度器连环重启）。"""

    def _task(self, tmp):
        from module.island.island_season_plan import IslandSeasonPlan
        task = IslandSeasonPlan(config=MagicMock(), device=None)
        task.LAST_RUN_FILE = tmp
        return task

    def test_always_schedules_next_run(self):
        from unittest import mock
        from module.island import island_season_plan as M

        task = self._task(os.path.join(tempfile.mkdtemp(), 'last.json'))
        with mock.patch.object(M, 'current_progress', side_effect=RuntimeError('boom')):
            with self.assertRaises(RuntimeError):
                task.run()
        task.config.task_delay.assert_called_once_with(minute=task.DELAY_MINUTE)

    def test_ready_progress_sends_mail_and_requests_refresh(self):
        from unittest import mock
        from module.island import island_season_plan as M

        task = self._task(os.path.join(tempfile.mkdtemp(), 'last.json'))
        with mock.patch.object(M, 'SeasonConfig') as season_cls, \
                mock.patch.object(M, 'current_progress', return_value={'latte': [100, 100]}), \
                mock.patch.object(M, 'request_refresh_on_gap_change', return_value=True) as refresh, \
                mock.patch.object(M, 'notify_ready_from_progress') as notify:
            season_cls.return_value.season = 'autumn'
            task.run()
        refresh.assert_called_once_with(task.config, 'autumn')
        notify.assert_called_once_with(task.config, 'autumn', {'latte': [100, 100]})

    def test_never_touches_device(self):
        from unittest import mock
        from module.island import island_season_plan as M

        task = self._task(os.path.join(tempfile.mkdtemp(), 'last.json'))
        self.assertIsNone(task.device)
        with mock.patch.object(M, 'SeasonConfig') as season_cls, \
                mock.patch.object(M, 'current_progress', return_value={}), \
                mock.patch.object(M, 'request_refresh_on_gap_change', return_value=False), \
                mock.patch.object(M, 'notify_ready_from_progress'):
            season_cls.return_value.season = 'autumn'
            task.run()


class TestConfigSchema(unittest.TestCase):
    """配置定义与代码里的槽位数、键名必须一致，否则界面上的槽位会读不到。"""

    def test_args_json_has_all_slots(self):
        with open('module/config/argument/args.json', encoding='utf-8') as f:
            group = json.load(f)['IslandSeasonPlan']['IslandSeasonPlan']
        self.assertIn('NotifyEnable', group)
        for n in range(1, P.SLOT_COUNT + 1):
            self.assertEqual(group[f'Item{n}']['type'], 'select')
            self.assertEqual(group[f'Need{n}']['type'], 'input')
            self.assertEqual(group[f'Done{n}']['type'], 'checkbox')
        self.assertNotIn(f'Item{P.SLOT_COUNT + 1}', group)

    def test_item_options_cover_economy_products(self):
        with open('module/config/argument/args.json', encoding='utf-8') as f:
            options = json.load(f)['IslandSeasonPlan']['IslandSeasonPlan']['Item1']['option']
        self.assertEqual(set(options), {'None'} | SHOP_ITEMS)

    def test_translations_in_all_languages(self):
        for lang in ('zh-CN', 'zh-TW', 'en-US', 'ja-JP'):
            with open(f'module/config/i18n/{lang}.json', encoding='utf-8') as f:
                group = json.load(f)['IslandSeasonPlan']
            with self.subTest(lang=lang):
                for n in range(1, P.SLOT_COUNT + 1):
                    for key in (f'Item{n}', f'Need{n}', f'Done{n}'):
                        self.assertNotEqual(group[key]['name'], f'IslandSeasonPlan.{key}.name')
                missing = [i for i in SHOP_ITEMS if i not in group['Item1']]
                self.assertEqual(missing, [], '下拉选项缺翻译')


if __name__ == '__main__':
    unittest.main()
