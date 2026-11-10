"""常驻餐品轮换测试（纯离线，不需要设备）。"""
import sys
import unittest

sys.path.insert(0, '.')

from module.island.island_away_cook import (
    AWAY_COOK_KEYS,
    pick_away_cook,
    resolve_away_cook,
    rotation_key,
    season_items_for_shop,
)
from module.island.island_season_plan_data import WINTER_ENABLED_KEY

# Add by MHY, 2026-11-10：选品测试直接注入 read_slots 的产物，隔离赛季表变化；
# season 只影响无 slots 时的兜底，不参与这里的选择计算。
COFFEE_SLOTS = [
    {'item': 'iced_coffee', 'need': 250, 'done': False},
    {'item': 'latte', 'need': 100, 'done': False},
]
GRILL_SLOTS = [
    {'item': 'roasted_skewer', 'need': 250, 'done': False},
    {'item': 'carrot_omelette', 'need': 100, 'done': False},
    {'item': 'stir_fried_chicken', 'need': 100, 'done': False},
    {'item': 'steak_bowl', 'need': 50, 'done': False},
]
RESTAURANT_SLOTS = [{'item': 'salad', 'need': 100, 'done': False}]


def fake_config(notify=True, winter=True, **values):
    """只有 cross_get 的配置替身：提醒总开关 + 冬季任务开关，其余键由 values 补。"""
    from unittest import mock

    store = {'IslandSeasonPlan.IslandSeasonPlan.NotifyEnable': notify,
             WINTER_ENABLED_KEY: winter}
    store.update(values)
    config = mock.Mock()
    config.config_name = 'ALAS'
    config.Error_OnePushConfig = 'provider: smtp'
    config.cross_get.side_effect = lambda key, default=None: store.get(key, default)
    return config


def run_notify(progress, notified=None, season='autumn', config=None, reserve=None,
               buffer=20, unknown=(), error=None, stub_reserve=True):
    """跑一遍 notify_ready_from_progress，返回 (提醒物品, 邮件, 通知状态, 落盘次数)。

    stub_reserve=False 时不桩 business_requirements/meal_buffer，用真实配置算营业储备。
    """
    from contextlib import nullcontext
    from unittest import mock
    from module.island import island_away_cook as away_cook

    sent = []
    notified = {} if notified is None else notified
    saved = []
    if stub_reserve:
        requirements = (mock.patch('module.island.island_winter_meals.business_requirements',
                                   side_effect=error) if error else
                        mock.patch('module.island.island_winter_meals.business_requirements',
                                   return_value=(dict(reserve or {}), set(unknown))))
        buffer_patch = mock.patch('module.island.island_winter_meals.meal_buffer',
                                  return_value=buffer)
    else:
        requirements = nullcontext()
        buffer_patch = nullcontext()
    with requirements, buffer_patch, \
            mock.patch.object(away_cook, 'load_notified', return_value=notified), \
            mock.patch.object(away_cook, 'save_notified', side_effect=saved.append), \
            mock.patch('module.notify.notify.handle_notify',
                       side_effect=lambda *a, **k: sent.append(k) or True):
        fired = away_cook.notify_ready_from_progress(config or fake_config(), season, progress)
    return fired, sent, notified, saved


class TestNotifyReadyFromProgress(unittest.TestCase):
    """进度（仓库读数）达标才发邮件；通知函数必须真的跑一遍：写过 notify_title 却忘了
    import 只有调用时才暴露。"""

    def _run(self, progress, notified=None, **kwargs):
        kwargs.setdefault('season', 'autumn')
        return run_notify(progress, notified=notified, **kwargs)

    def test_ready_sends_one_mail(self):
        fired, sent, _, _ = self._run({'apple_juice': [250, 250]})
        self.assertEqual(fired, ['apple_juice'])
        self.assertEqual(len(sent), 1)
        self.assertIn('[岛屿]', sent[0]['title'])
        self.assertIn('<ALAS>', sent[0]['title'])
        self.assertIn('甜蜜引擎', sent[0]['content'])

    def test_material_tasks_do_not_notify(self):
        """农田/牧场材料长期溢出，提醒它们只会刷屏（真机一次发了 8 封）"""
        fired, sent, _, _ = self._run({'corn': [500, 500], 'wheat': [500, 500]})
        self.assertEqual(fired, [])
        self.assertEqual(sent, [])

    def test_multiple_ready_send_one_mail(self):
        """多项达标合并成一封，避免刷爆收件箱"""
        fired, sent, _, _ = self._run({'apple_juice': [250, 250], 'salad': [120, 100],
                                       'latte': [82, 100]})
        self.assertEqual(sorted(fired), ['apple_juice', 'salad'])
        self.assertEqual(len(sent), 1)

    def test_only_notifies_once(self):
        notified = {}
        self._run({'salad': [100, 100]}, notified)
        fired, sent, _, _ = self._run({'salad': [100, 100]}, notified)
        self.assertEqual(fired, [])
        self.assertEqual(sent, [])

    def test_drop_below_target_resets_notified(self):
        """提交任务后仓库数量掉下去会复位，下次攒够才能再提醒。"""
        notified = {}
        self._run({'salad': [100, 100]}, notified)
        _, _, _, saved = self._run({'salad': [3, 100]}, notified)
        self.assertFalse(notified['autumn']['salad']['notified'])
        self.assertEqual(len(saved), 1)
        fired, sent, _, _ = self._run({'salad': [100, 100]}, notified)
        self.assertEqual(fired, ['salad'])
        self.assertEqual(len(sent), 1)

    def test_not_ready_sends_nothing(self):
        """拿铁 82/100 不能发达标邮件（赛季页曾把 82 误读成 282）。"""
        fired, sent, _, _ = self._run({'latte': [82, 100]})
        self.assertEqual(fired, [])
        self.assertEqual(sent, [])

    def test_zero_need_never_notifies(self):
        fired, sent, _, _ = self._run({'latte': [0, 0]})
        self.assertEqual(fired, [])

    def test_legacy_notified_format(self):
        """旧状态文件里 {物品: True} 的格式不炸。"""
        fired, _, _, _ = self._run({'salad': [100, 100]}, {'autumn': {'salad': True}})
        self.assertEqual(fired, [])


class TestWinterMealNotify(unittest.TestCase):
    """冬季餐品：任务需求 + 营业储备 + MealBuffer 都够了才提醒。"""

    def _run(self, progress, notified=None, **kwargs):
        kwargs.setdefault('season', 'winter')
        return run_notify(progress, notified=notified, **kwargs)

    def test_threshold_includes_reserve_and_buffer(self):
        """需求 100 + 营业储备 12 + 缓冲 20 = 132：差一件就不能提醒。"""
        reserve = {'chicken_potato': 12}
        fired, sent, _, _ = self._run({'chicken_potato': [131, 100]}, reserve=reserve)
        self.assertEqual((fired, sent), ([], []))
        fired, sent, _, _ = self._run({'chicken_potato': [132, 100]}, reserve=reserve)
        self.assertEqual(fired, ['chicken_potato'])
        self.assertEqual(len(sent), 1)

    def test_buffer_alone_is_not_enough(self):
        """只按需求 + 缓冲（120）攒够还不行，还要留出营业储备。"""
        reserve = {'chicken_potato': 12}
        fired, _, _, _ = self._run({'chicken_potato': [120, 100]}, reserve=reserve)
        self.assertEqual(fired, [])

    def test_reserve_for_other_items_does_not_change_threshold(self):
        reserve = {'rice_mango': 99}
        fired, _, _, _ = self._run({'chicken_potato': [120, 100]}, reserve=reserve)
        self.assertEqual(fired, ['chicken_potato'])

    def test_switch_off_sends_nothing(self):
        fired, sent, _, _ = self._run({'chicken_potato': [999, 100]},
                                      config=fake_config(winter=False))
        self.assertEqual((fired, sent), ([], []))

    def test_notify_switch_off_sends_nothing(self):
        fired, sent, _, _ = self._run({'chicken_potato': [999, 100]},
                                      config=fake_config(notify=False))
        self.assertEqual((fired, sent), ([], []))

    def test_reserve_failure_sends_nothing(self):
        """营业储备算不出来（配方循环等）时宁可不提醒，不能把销售占用当 0。"""
        fired, sent, _, _ = self._run({'chicken_potato': [999, 100]},
                                      error=ValueError('餐品配方存在循环依赖'))
        self.assertEqual((fired, sent), ([], []))

    def test_unknown_stock_never_notifies(self):
        fired, sent, _, _ = self._run({'chicken_potato': [None, 100]})
        self.assertEqual((fired, sent), ([], []))

    def test_drop_between_need_and_target_resets(self):
        """销售消耗掉一部分（还在需求之上、储备之下）就复位，攒回来再提醒。"""
        notified = {}
        reserve = {'chicken_potato': 12}
        self._run({'chicken_potato': [132, 100]}, notified, reserve=reserve)
        self._run({'chicken_potato': [110, 100]}, notified, reserve=reserve)
        self.assertFalse(notified['winter']['chicken_potato']['notified'])
        fired, sent, _, _ = self._run({'chicken_potato': [132, 100]}, notified,
                                      reserve=reserve)
        self.assertEqual(fired, ['chicken_potato'])
        self.assertEqual(len(sent), 1)

    def test_message_states_basis_and_caveats(self):
        fired, sent, _, _ = self._run({'chicken_potato': [140, 100]},
                                      reserve={'chicken_potato': 12})
        self.assertEqual(fired, ['chicken_potato'])
        content = sent[0]['content']
        self.assertIn('最近一次仓库读数', content)
        self.assertIn('提交前请在游戏内核对', content)
        self.assertIn('Done_', content)
        self.assertIn('自动提交', content)
        self.assertIn('销售', content)
        self.assertIn('营业储备', content)
        self.assertIn('餐品缓冲 20', content)
        self.assertNotIn('绝不影响销售', content)
        self.assertIn('可以提交', sent[0]['title'])

    def test_unknown_shops_pause_notification(self):
        fired, sent, _, _ = self._run({'chicken_potato': [140, 100]},
                                      reserve={'chicken_potato': 12},
                                      unknown={'juu_eatery'})
        self.assertEqual(fired, [])
        self.assertEqual(sent, [])

    def test_real_business_requirements_drive_threshold(self):
        """不桩 business_requirements：钻石店一格禽肉土豆拼盘 = 6 件营业储备。"""
        config = fake_config(**{
            'IslandBusiness.IslandBusiness.ShopLevel': 'diamond',
            'IslandBusiness.IslandBusinessShop4.Product1': 'chicken_potato',
        })
        fired, sent, _, _ = self._run({'chicken_potato': [125, 100]}, config=config,
                                      stub_reserve=False)
        self.assertEqual((fired, sent), ([], []))
        fired, sent, _, _ = self._run({'chicken_potato': [126, 100]}, config=config,
                                      stub_reserve=False)
        self.assertEqual(fired, ['chicken_potato'])
        self.assertEqual(len(sent), 1)

    def test_non_winter_keeps_plain_need(self):
        """非冬季不受营业储备影响：需求 100 攒够就提醒。"""
        fired, sent, _, _ = self._run({'chicken_potato': [100, 100]},
                                      season='autumn', reserve={'chicken_potato': 999})
        self.assertEqual(fired, ['chicken_potato'])
        self.assertEqual(len(sent), 1)


class TestSeasonItemsForShop(unittest.TestCase):
    def test_coffee_items(self):
        """咖啡店要交冰咖啡和拿铁"""
        items = {name: need for name, need, _ in
                 season_items_for_shop('juu_coffee', 'winter', slots=COFFEE_SLOTS)}
        self.assertEqual(items, {'iced_coffee': 250, 'latte': 100})

    def test_grill_items(self):
        """烤肉店要交 4 样"""
        items = {name: need for name, need, _ in
                 season_items_for_shop('grill', 'winter', slots=GRILL_SLOTS)}
        self.assertEqual(items, {'roasted_skewer': 250, 'carrot_omelette': 100,
                                  'stir_fried_chicken': 100, 'steak_bowl': 50})

    def test_retired_season_without_slots_returns_empty(self):
        """秋季已过季：没传 slots 时不能回退到过季表，否则配置缺键会重新选中旧物品。"""
        for shop in AWAY_COOK_KEYS:
            self.assertEqual(season_items_for_shop(shop, 'autumn'), [], shop)

    def test_winter_fallback_only_uses_active_table(self):
        """进行中赛季仍可按赛季表兜底（离线/旧调用），过季表不参与。"""
        items = {name: need for name, need, _ in season_items_for_shop('grill', 'winter')}
        self.assertEqual(items, {'chicken_potato': 100})

    def test_unknown_season(self):
        self.assertEqual(season_items_for_shop('grill', 'nonexistent'), [])


class TestPickAwayCook(unittest.TestCase):
    def test_pick_biggest_gap(self):
        """冰咖啡还差 50、拿铁还差 100 -> 先产拿铁"""
        counts = {'iced_coffee': 200, 'latte': 0}
        self.assertEqual(pick_away_cook('juu_coffee', 'winter', counts,
                                       slots=COFFEE_SLOTS), 'latte')

    def test_pick_switches_when_done(self):
        """拿铁攒够后切回冰咖啡"""
        counts = {'iced_coffee': 0, 'latte': 100}
        self.assertEqual(pick_away_cook('juu_coffee', 'winter', counts,
                                       slots=COFFEE_SLOTS), 'iced_coffee')

    def test_all_done_returns_none(self):
        counts = {'iced_coffee': 250, 'latte': 100}
        self.assertEqual(pick_away_cook('juu_coffee', 'winter', counts,
                                       slots=COFFEE_SLOTS), 'None')

    def test_missing_stock_counts_as_zero(self):
        """读不到库存的物品按 0 算（保守多产，不会误判成已攒够）"""
        self.assertEqual(pick_away_cook('grill', 'winter', {},
                                       slots=GRILL_SLOTS), 'roasted_skewer')

    def test_none_and_negative_counts_are_tolerated(self):
        """-1/None 是未知读数的写法：轮换不能让它们参与比较而报错。"""
        counts = {'roasted_skewer': None, 'carrot_omelette': -1,
                  'stir_fried_chicken': 0, 'steak_bowl': 0}
        self.assertEqual(pick_away_cook('grill', 'winter', counts,
                                       slots=GRILL_SLOTS), 'roasted_skewer')

    def test_producible_filter(self):
        """不在可生产集合里的物品跳过"""
        counts = {'roasted_skewer': 0, 'carrot_omelette': 0,
                  'stir_fried_chicken': 0, 'steak_bowl': 0}
        picked = pick_away_cook('grill', 'winter', counts,
                               producible={'steak_bowl'}, slots=GRILL_SLOTS)
        self.assertEqual(picked, 'steak_bowl')

    def test_exclude_filter(self):
        picked = pick_away_cook('juu_coffee', 'winter', {},
                               exclude={'iced_coffee'}, slots=COFFEE_SLOTS)
        self.assertEqual(picked, 'latte')

    def test_retired_season_without_slots_picks_none(self):
        """过季赛季没有活动槽位时不能再选中秋季物品。"""
        self.assertEqual(pick_away_cook('juu_coffee', 'autumn', {}), 'None')

    def test_shop_without_season_items(self):
        self.assertEqual(pick_away_cook('juu_coffee', 'winter', {}), 'None')


class TestResolveAwayCook(unittest.TestCase):
    def test_records_user_default_when_overriding(self):
        """有赛季缺口时覆盖，并记住用户原值与自动写入值（餐馆的豆腐）"""
        target, defaults = resolve_away_cook('restaurant', 'winter', {}, 'tofu', {},
                                             slots=RESTAURANT_SLOTS)
        self.assertEqual(target, 'salad')
        self.assertEqual(defaults, {'restaurant': {'value': 'tofu', 'auto': 'salad'}})

    def test_restores_user_default_when_done(self):
        """赛季物品攒够后还原用户原值，岗位不再空转"""
        counts = {'salad': 100}
        target, defaults = resolve_away_cook(
            'restaurant', 'winter', counts, 'salad',
            {'restaurant': {'value': 'tofu', 'auto': 'salad'}},
            slots=RESTAURANT_SLOTS)
        self.assertEqual(target, 'tofu')
        self.assertEqual(defaults, {})

    def test_keeps_current_when_no_gap_and_no_backup(self):
        """没有缺口也没有备份时保持原值（不动用户配置）"""
        target, defaults = resolve_away_cook('teahouse', 'autumn', {}, 'None', {}, slots=[])
        self.assertEqual(target, 'None')
        self.assertEqual(defaults, {})

    def test_switch_between_season_items(self):
        """同一店多个赛季物品之间切换时不覆盖备份"""
        counts = {'iced_coffee': 250, 'latte': 0}
        target, defaults = resolve_away_cook(
            'juu_coffee', 'winter', counts, 'iced_coffee',
            {'juu_coffee': {'value': 'cheese', 'auto': 'iced_coffee'}},
            slots=COFFEE_SLOTS)
        self.assertEqual(target, 'latte')
        self.assertEqual(defaults, {'juu_coffee': {'value': 'cheese', 'auto': 'latte'}})

    def test_retired_season_restores_auto_written_value(self):
        """过季且当前值仍是自动写入值：还原用户原值，回收历史自动 AwayCook。"""
        target, defaults = resolve_away_cook(
            'juu_coffee', 'autumn', {}, 'latte',
            {'juu_coffee': {'value': 'cheese', 'auto': 'latte'}}, slots=[])
        self.assertEqual(target, 'cheese')
        self.assertEqual(defaults, {})

    def test_retired_season_keeps_manual_edit(self):
        """当前值已不是自动写入值：用户手填优先，不能盲目覆盖。"""
        target, defaults = resolve_away_cook(
            'juu_coffee', 'autumn', {}, 'mocha',
            {'juu_coffee': {'value': 'cheese', 'auto': 'latte'}}, slots=[])
        self.assertEqual(target, 'mocha')
        self.assertEqual(defaults, {})

    def test_legacy_backup_restores_only_retired_item(self):
        """旧备份没有 auto 标记：仅当现值仍是过季任务物品时才认作历史自动残留。"""
        target, defaults = resolve_away_cook(
            'juu_coffee', 'autumn', {}, 'latte', {'juu_coffee': 'cheese'}, slots=[])
        self.assertEqual(target, 'cheese')
        self.assertEqual(defaults, {})
        target, defaults = resolve_away_cook(
            'juu_coffee', 'autumn', {}, 'mocha', {'juu_coffee': 'cheese'}, slots=[])
        self.assertEqual(target, 'mocha')
        self.assertEqual(defaults, {})

    def test_retired_without_backup_keeps_current(self):
        """没有用户原值记录的历史残留：保留现值，只告警，不替用户清空。"""
        target, defaults = resolve_away_cook('juu_coffee', 'autumn', {}, 'apple_juice',
                                             {}, slots=[])
        self.assertEqual(target, 'apple_juice')
        self.assertEqual(defaults, {})

    def test_manual_change_during_override_becomes_new_original(self):
        """自动接管期间用户手改：下一次覆盖时以手填值作为新的原值。"""
        target, defaults = resolve_away_cook(
            'juu_coffee', 'winter', {'iced_coffee': 0, 'latte': 0}, 'mocha',
            {'juu_coffee': {'value': 'cheese', 'auto': 'iced_coffee'}},
            slots=COFFEE_SLOTS)
        self.assertEqual(target, 'iced_coffee')
        self.assertEqual(defaults, {'juu_coffee': {'value': 'mocha', 'auto': 'iced_coffee'}})


class TestRotationKey(unittest.TestCase):
    def test_keys(self):
        self.assertEqual(rotation_key('restaurant'),
                         'IslandRestaurant.IslandRestaurantNextTask.AwayCook')
        self.assertEqual(rotation_key('juu_coffee'),
                         'IslandJuuCoffee.IslandJuuCoffeeNextTask.AwayCook')
        self.assertIsNone(rotation_key('unknown_shop'))

    def test_all_shops_covered(self):
        self.assertEqual(set(AWAY_COOK_KEYS),
                         {'restaurant', 'teahouse', 'juu_eatery', 'grill', 'juu_coffee'})


if __name__ == '__main__':
    unittest.main()
