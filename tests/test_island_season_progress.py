"""赛季进度：赛季表（代码）+ 配置（需求/已完成）+ 仓库读数（纯逻辑，不需要设备）。

背景：赛季页 OCR 会把拿铁的 82 误读成 282 并错发达标邮件，所以改成每次收取生产、
核对销售时直接用仓库读数。餐品清单由代码赛季表固定，用户只填需求数量、勾选已完成；
已完成的餐品不再排产、不再提醒，空闲产能自动转去做下一个缺口最大的。
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
from module.island.island_season_plan_data import SEASON_PLAN_TASKS

SHOP_ITEMS = set(ECONOMY_PRODUCTS)
AUTUMN_DISHES = [i for _, i, _ in SEASON_PLAN_TASKS['autumn'] if i in SHOP_ITEMS]


def fake_config(need=None, done=(), notify=True):
    """need: {物品: 需求}；done: 已完成的物品。没写的键读不到，走默认值。"""
    store = {P.NOTIFY_KEY: notify}
    for item, value in (need or {}).items():
        store[P.need_key(item)] = value
    for item in done:
        store[P.done_key(item)] = True
    config = MagicMock()
    config.store = store
    config.cross_get.side_effect = lambda key, default=None: store.get(key, default)
    return config


class TestSeasonDishes(unittest.TestCase):
    def test_autumn_has_eight_shop_dishes(self):
        """餐品清单固定来自代码赛季表：8 个店铺餐品，材料类不在其中。"""
        dishes = dict(P.season_dishes('autumn', SHOP_ITEMS))
        self.assertEqual(len(dishes), 8)
        self.assertEqual(dishes['latte'], 100)
        self.assertEqual(dishes['steak_bowl'], 50)
        self.assertNotIn('wheat', dishes)
        self.assertNotIn('milk', dishes)

    def test_unknown_season_is_empty(self):
        self.assertEqual(P.season_dishes('winter', SHOP_ITEMS), [])

    def test_order_follows_season_table(self):
        self.assertEqual([i for i, _ in P.season_dishes('autumn', SHOP_ITEMS)], AUTUMN_DISHES)


class TestReadSlots(unittest.TestCase):
    def test_defaults_when_config_empty(self):
        slots = P.read_slots(fake_config(), 'autumn', SHOP_ITEMS)
        self.assertEqual(len(slots), 8)
        by_item = {s['item']: s for s in slots}
        self.assertEqual(by_item['apple_juice']['need'], 250)
        self.assertFalse(any(s['done'] for s in slots))

    def test_user_need_and_done_are_read(self):
        config = fake_config(need={'latte': 150}, done=['salad'])
        by_item = {s['item']: s for s in P.read_slots(config, 'autumn', SHOP_ITEMS)}
        self.assertEqual(by_item['latte']['need'], 150)
        self.assertTrue(by_item['salad']['done'])
        self.assertFalse(by_item['latte']['done'])

    def test_bad_need_falls_back_to_default(self):
        by_item = {s['item']: s for s in
                   P.read_slots(fake_config(need={'latte': 'abc'}), 'autumn', SHOP_ITEMS)}
        self.assertEqual(by_item['latte']['need'], 100)

    def test_negative_need_clamped(self):
        by_item = {s['item']: s for s in
                   P.read_slots(fake_config(need={'latte': -5}), 'autumn', SHOP_ITEMS)}
        self.assertEqual(by_item['latte']['need'], 0)

    def test_none_need_uses_default(self):
        by_item = {s['item']: s for s in
                   P.read_slots(fake_config(need={'latte': None}), 'autumn', SHOP_ITEMS)}
        self.assertEqual(by_item['latte']['need'], 100)


class TestDoneExcludesFromPlanning(unittest.TestCase):
    """已完成 = 不再生产、不再提醒，空闲产能转去做下一个。"""

    def setUp(self):
        self.config = fake_config(need={'iced_coffee': 0}, done=['salad'])
        self.slots = P.read_slots(self.config, 'autumn', SHOP_ITEMS)

    def test_done_and_zero_need_are_inactive(self):
        active = [s['item'] for s in P.active_slots(self.slots)]
        self.assertNotIn('salad', active)
        self.assertNotIn('iced_coffee', active)
        self.assertIn('latte', active)

    def test_done_item_not_in_progress_even_with_huge_stock(self):
        """蔬菜沙拉库存 2100：已完成不再出现在进度里，也就不会再发邮件或排产。"""
        progress = P.build_progress(self.slots, {'salad': 2100, 'latte': 82})
        self.assertNotIn('salad', progress)
        self.assertEqual(progress['latte'], [82, 100])

    def test_done_item_stays_excluded_when_stock_drops(self):
        self.assertNotIn('salad', P.build_progress(self.slots, {'salad': 3}))

    def test_unticking_done_resumes(self):
        slots = P.read_slots(fake_config(), 'autumn', SHOP_ITEMS)
        self.assertEqual(P.build_progress(slots, {'salad': 20})['salad'], [20, 100])

    def test_next_gap_becomes_active_after_done(self):
        """做完一个标记完成后，缺口自然落到下一个。"""
        from module.island.island_away_cook import pick_away_cook
        have = {'latte': 0, 'iced_coffee': 0}
        before = P.read_slots(fake_config(), 'autumn', SHOP_ITEMS)
        after = P.read_slots(fake_config(done=['iced_coffee']), 'autumn', SHOP_ITEMS)
        self.assertEqual(pick_away_cook('juu_coffee', 'autumn', have, slots=before), 'iced_coffee')
        self.assertEqual(pick_away_cook('juu_coffee', 'autumn', have, slots=after), 'latte')

    def test_all_done_in_shop_picks_none(self):
        from module.island.island_away_cook import pick_away_cook
        slots = P.read_slots(fake_config(done=['iced_coffee', 'latte']), 'autumn', SHOP_ITEMS)
        self.assertEqual(pick_away_cook('juu_coffee', 'autumn', {}, slots=slots), 'None')


class TestSeasonChange(unittest.TestCase):
    """换赛季只改代码里的赛季表，用户不选餐品。"""

    def test_new_season_dishes_come_from_table(self):
        from unittest import mock
        table = {'winter': [('冬任务', 'latte', 77), ('材料任务', 'wheat', 500)]}
        with mock.patch.dict(P.SEASON_PLAN_TASKS, table, clear=False):
            self.assertEqual(P.season_dishes('winter', SHOP_ITEMS), [('latte', 77)])
            slots = P.read_slots(fake_config(), 'winter', SHOP_ITEMS)
        self.assertEqual([(s['item'], s['need']) for s in slots], [('latte', 77)])

    def test_old_season_dish_not_in_config_is_ignored_safely(self):
        """配置里没有的餐品键读不到，按赛季表默认值、未完成处理，不会炸。"""
        from unittest import mock
        table = {'winter': [('冬任务', 'omelette', 40)]}
        with mock.patch.dict(P.SEASON_PLAN_TASKS, table, clear=False):
            slots = P.read_slots(fake_config(), 'winter', SHOP_ITEMS)
        self.assertEqual(slots, [{'item': 'omelette', 'need': 40, 'done': False}])

    def test_season_table_dishes_all_have_config_keys(self):
        """赛季表里每个店铺餐品都必须在配置里有 Need_/Done_ 键，否则用户改了也读不到。"""
        with open('module/config/argument/args.json', encoding='utf-8') as f:
            group = json.load(f)['IslandSeasonPlan']['IslandSeasonPlan']
        missing = []
        for season in SEASON_PLAN_TASKS:
            for item, _ in P.season_dishes(season, SHOP_ITEMS):
                for key in (f'Need_{item}', f'Done_{item}'):
                    if key not in group:
                        missing.append(key)
        self.assertEqual(missing, [], '赛季表加了餐品，要在 argument.yaml 里补 Need_/Done_ 并补翻译')


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
        self.path = os.path.join(tempfile.mkdtemp(), 'have.json')

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

    def test_done_dish_never_reaches_notify(self):
        """已完成的餐品不在进度里，邮件函数根本看不到它。"""
        config = fake_config(done=['salad'])
        slots = P.read_slots(config, 'autumn', SHOP_ITEMS)
        progress = P.build_progress(slots, {'salad': 2100, 'latte': 82})
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
    """配置定义、翻译与赛季表必须一致，否则界面上的开关会读不到。"""

    def _group(self):
        with open('module/config/argument/args.json', encoding='utf-8') as f:
            return json.load(f)['IslandSeasonPlan']['IslandSeasonPlan']

    def test_each_dish_has_need_and_done(self):
        group = self._group()
        self.assertEqual(group['NotifyEnable']['type'], 'checkbox')
        for item in AUTUMN_DISHES:
            self.assertEqual(group[f'Need_{item}']['type'], 'input')
            self.assertEqual(group[f'Done_{item}']['type'], 'checkbox')
            self.assertFalse(group[f'Done_{item}']['value'])

    def test_default_need_matches_season_table(self):
        group = self._group()
        for item, need in P.season_dishes('autumn', SHOP_ITEMS):
            self.assertEqual(group[f'Need_{item}']['value'], need, item)

    def test_no_item_picker_left(self):
        """餐品不再由用户选择：配置里不能再有 Item<n> 下拉。"""
        self.assertFalse([k for k in self._group() if k.startswith('Item')])

    def test_translations_in_all_languages(self):
        keys = ['NotifyEnable'] + [f'{p}_{i}' for i in AUTUMN_DISHES for p in ('Need', 'Done')]
        for lang in ('zh-CN', 'zh-TW', 'en-US', 'ja-JP'):
            with open(f'module/config/i18n/{lang}.json', encoding='utf-8') as f:
                group = json.load(f)['IslandSeasonPlan']
            with self.subTest(lang=lang):
                for key in keys:
                    self.assertNotEqual(group[key]['name'], f'IslandSeasonPlan.{key}.name')
                    self.assertNotEqual(group[key]['help'], f'IslandSeasonPlan.{key}.help')


if __name__ == '__main__':
    unittest.main()
