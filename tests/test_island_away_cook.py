"""常驻餐品轮换测试（纯离线，不需要设备）。"""
import sys
import unittest

sys.path.insert(0, '.')

from module.island.island_away_cook import (
    AWAY_COOK_KEYS,
    collect_finished,
    pick_away_cook,
    resolve_away_cook,
    rotation_key,
    season_items_for_shop,
)


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


class TestFinishedNotification(unittest.TestCase):
    def test_notify_once_per_item(self):
        """攒够只通知一次，重复读取不再发"""
        notified = {}
        counts = {'salad': 132}
        first = collect_finished('restaurant', 'autumn', counts, notified)
        self.assertEqual(first, [('salad', 100, 132)])
        self.assertEqual(collect_finished('restaurant', 'autumn', counts, notified), [])

    def test_reset_after_submit(self):
        """用户提交后数量下降，下次攒够重新通知"""
        notified = {}
        collect_finished('restaurant', 'autumn', {'salad': 100}, notified)
        collect_finished('restaurant', 'autumn', {'salad': 0}, notified)
        self.assertEqual(len(collect_finished('restaurant', 'autumn', {'salad': 100}, notified)), 1)

    def test_not_enough_no_notify(self):
        notified = {}
        self.assertEqual(collect_finished('restaurant', 'autumn', {'salad': 99}, notified), [])

    def test_missing_template_counts_as_not_ready(self):
        """没有仓库模板读不到数量时按 0 处理，不能误报"""
        notified = {}
        self.assertEqual(collect_finished('restaurant', 'autumn', {}, notified), [])

    def test_task_name_lookup(self):
        from module.island.island_season_plan_data import task_of_item
        self.assertEqual(task_of_item('salad', 'autumn'), ('健康饮食', 100))
        self.assertEqual(task_of_item('nonexistent', 'autumn'), (None, 0))


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
