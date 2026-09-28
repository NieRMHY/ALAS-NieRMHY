"""常驻餐品轮换测试（纯离线，不需要设备）。"""
import sys
import unittest

sys.path.insert(0, '.')

from module.island.island_away_cook import (
    AWAY_COOK_KEYS,
    pick_away_cook,
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
