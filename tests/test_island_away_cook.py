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


class TestNotifyReadyFromProgress(unittest.TestCase):
    """进度（仓库读数）达标才发邮件；通知函数必须真的跑一遍：写过 notify_title 却忘了
    import 只有调用时才暴露。"""

    def _config(self):
        from unittest import mock
        config = mock.Mock()
        config.config_name = 'ALAS'
        config.Error_OnePushConfig = 'provider: smtp'
        return config

    def _run(self, progress, notified=None):
        from unittest import mock
        from module.island import island_away_cook as away_cook

        sent = []
        notified = {} if notified is None else notified
        saved = []
        with mock.patch.object(away_cook, 'load_notified', return_value=notified), \
                mock.patch.object(away_cook, 'save_notified', side_effect=saved.append), \
                mock.patch('module.notify.notify.handle_notify',
                           side_effect=lambda *a, **k: sent.append(k) or True):
            fired = away_cook.notify_ready_from_progress(self._config(), 'autumn', progress)
        return fired, sent, notified, saved

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


class TestSeasonItemsForShop(unittest.TestCase):
    def test_coffee_items(self):
        """咖啡店要交冰咖啡和拿铁"""
        items = {name: need for name, need, _ in season_items_for_shop('juu_coffee', 'autumn')}
        self.assertEqual(items, {'iced_coffee': 250, 'latte': 100})

    def test_grill_items(self):
        """烤肉店要交 4 样"""
        items = {name: need for name, need, _ in season_items_for_shop('grill', 'autumn')}
        self.assertEqual(items, {'roasted_skewer': 250, 'carrot_omelette': 100,
                                  'stir_fried_chicken': 100, 'steak_bowl': 50})

    def test_unknown_season(self):
        self.assertEqual(season_items_for_shop('grill', 'nonexistent'), [])


class TestPickAwayCook(unittest.TestCase):
    def test_pick_biggest_gap(self):
        """冰咖啡还差 50、拿铁还差 100 -> 先产拿铁"""
        counts = {'iced_coffee': 200, 'latte': 0}
        self.assertEqual(pick_away_cook('juu_coffee', 'autumn', counts), 'latte')

    def test_pick_switches_when_done(self):
        """拿铁攒够后切回冰咖啡"""
        counts = {'iced_coffee': 0, 'latte': 100}
        self.assertEqual(pick_away_cook('juu_coffee', 'autumn', counts), 'iced_coffee')

    def test_all_done_returns_none(self):
        counts = {'iced_coffee': 250, 'latte': 100}
        self.assertEqual(pick_away_cook('juu_coffee', 'autumn', counts), 'None')

    def test_missing_stock_counts_as_zero(self):
        """读不到库存的物品按 0 算（保守）"""
        self.assertEqual(pick_away_cook('grill', 'autumn', {}), 'roasted_skewer')

    def test_producible_filter(self):
        """不在可生产集合里的物品跳过"""
        counts = {'roasted_skewer': 0, 'carrot_omelette': 0,
                  'stir_fried_chicken': 0, 'steak_bowl': 0}
        picked = pick_away_cook('grill', 'autumn', counts,
                               producible={'steak_bowl'})
        self.assertEqual(picked, 'steak_bowl')

    def test_exclude_filter(self):
        picked = pick_away_cook('juu_coffee', 'autumn', {},
                               exclude={'iced_coffee'})
        self.assertEqual(picked, 'latte')

    def test_shop_without_season_items(self):
        self.assertEqual(pick_away_cook('juu_eatery', 'autumn', {}), 'None')


class TestResolveAwayCook(unittest.TestCase):
    def test_records_user_default_when_overriding(self):
        """有赛季缺口时覆盖，并记住用户原值（餐馆的豆腐）"""
        target, defaults = resolve_away_cook('restaurant', 'autumn', {}, 'tofu', {})
        self.assertEqual(target, 'salad')
        self.assertEqual(defaults, {'restaurant': 'tofu'})

    def test_restores_user_default_when_done(self):
        """赛季物品攒够后还原用户原值，岗位不再空转"""
        counts = {'salad': 100}
        target, defaults = resolve_away_cook('restaurant', 'autumn', counts, 'salad',
                                             {'restaurant': 'tofu'})
        self.assertEqual(target, 'tofu')
        self.assertEqual(defaults, {})

    def test_keeps_current_when_no_gap_and_no_backup(self):
        """没有缺口也没有备份时保持原值（不动用户配置）"""
        target, defaults = resolve_away_cook('teahouse', 'autumn', {'apple_juice': 250},
                                             'None', {})
        self.assertEqual(target, 'None')
        self.assertEqual(defaults, {})

    def test_switch_between_season_items(self):
        """同一店多个赛季物品之间切换时不覆盖备份"""
        counts = {'iced_coffee': 250, 'latte': 0}
        target, defaults = resolve_away_cook('juu_coffee', 'autumn', counts, 'iced_coffee',
                                             {'juu_coffee': 'cheese'})
        self.assertEqual(target, 'latte')
        self.assertEqual(defaults, {'juu_coffee': 'cheese'})


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
