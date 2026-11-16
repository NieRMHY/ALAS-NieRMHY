"""
经营端库存校验的离线测试：只测纯逻辑（不连游戏、不截图）。

对应缺口：配置商品仓库没货时，上架会静默失败（格子空着）。
"""
import unittest
from unittest.mock import Mock, patch

from module.island.island_business_stock import BusinessStockCheckMixin


class FakeBusiness(BusinessStockCheckMixin):
    """最小宿主：只实现库存校验依赖的属性与查找方法。"""

    SHOP_SEASON_MAP = {'有鱼餐馆': 'restaurant'}

    def __init__(self, products, active):
        self.shop_products = {'有鱼餐馆': list(products)}
        self.active_products = {'有鱼餐馆': list(active)}

    def _find_product_by_name(self, shop_name, name):
        for item in self.shop_products.get(shop_name, []):
            if item['name'] == name:
                return item
        return None


def make_item(name):
    return {'name': name, 'button': None}


class TestReplaceMissingProducts(unittest.TestCase):

    def setUp(self):
        # 餐馆池按利润/分钟：经典豆腐套餐 159 > 绵玉定食 64 > 凉拌双笋 52
        #                   > 肉沫烧豆腐 41 > 佛跳墙 30
        self.pool = ['tofu_combo', 'hearty_meal', 'double_bamboo_shoots',
                     'tofu_meat', 'fo_tiao']
        # 上架清单：凉拌双笋留作替补（不在清单里）
        self.active = [make_item(n) for n in
                       ('tofu_combo', 'hearty_meal', 'tofu_meat', 'fo_tiao')]

    def test_all_in_stock_keeps_order(self):
        host = FakeBusiness([make_item(n) for n in self.pool], self.active)
        counts = {'tofu_combo': 6, 'hearty_meal': 4, 'tofu_meat': 2, 'fo_tiao': 1,
                  'double_bamboo_shoots': 4}
        new_products, replacements = host.replace_missing_products('有鱼餐馆', counts)
        self.assertEqual(replacements, [])
        self.assertEqual([p['name'] for p in new_products],
                         ['tofu_combo', 'hearty_meal', 'tofu_meat', 'fo_tiao'])

    # Add by MHY, 冬季新品未录入经济库也应保留有库存的手填上架与常驻餐品。
    def test_winter_manual_products_and_away_cook_are_preserved(self):
        winter = make_item('shiitake_chicken_soup')
        host = FakeBusiness([winter, make_item('tofu_combo')], [winter])
        host.config = Mock()
        host.config.cross_get.side_effect = lambda key, default=None: (
            'winter' if key == 'IslandPlan.IslandPlan.Season' else 'shiitake_chicken_soup')
        products, replacements = host.replace_missing_products(
            '有鱼餐馆', {'shiitake_chicken_soup': 7, 'tofu_combo': 12})
        self.assertEqual(products, [winter])
        self.assertEqual(replacements, [])
        with patch('module.island.island_business_stock.load_defaults', return_value={}), \
                patch('module.island.island_business_stock.save_defaults'), \
                patch('module.island.island_business_stock.record_readings'):
            host._rotate_away_cook('restaurant', {'shiitake_chicken_soup': 7})
        host.config.cross_set.assert_not_called()
        host.config.update.assert_not_called()

    # Add by MHY, 2026-11-10：过季赛季下一次库存校验会回收带来源标记的自动 AwayCook。
    def test_retired_season_restores_recorded_away_cook(self):
        host = FakeBusiness([], [])
        host.config = Mock()
        host.config.cross_get.return_value = 'apple_juice'
        with patch('module.island.island_business_stock.SeasonConfig') as season_cls, \
                patch('module.island.island_business_stock.read_slots', return_value=[]), \
                patch('module.island.island_business_stock.record_readings'), \
                patch('module.island.island_business_stock.load_defaults',
                      return_value={'juu_coffee': {'value': 'cheese',
                                                   'auto': 'apple_juice'}}), \
                patch('module.island.island_business_stock.save_defaults') as save:
            season_cls.return_value.season = 'autumn'
            host._rotate_away_cook('juu_coffee', {})
        host.config.cross_set.assert_called_once_with(
            'IslandJuuCoffee.IslandJuuCoffeeNextTask.AwayCook', 'cheese')
        host.config.update.assert_called_once()
        save.assert_called_once_with({})

    # Add by MHY, 2026-11-10：当前值不是自动写入值，说明用户手改过，不能覆盖。
    def test_retired_season_keeps_manual_away_cook(self):
        host = FakeBusiness([], [])
        host.config = Mock()
        host.config.cross_get.return_value = 'mocha'
        with patch('module.island.island_business_stock.SeasonConfig') as season_cls, \
                patch('module.island.island_business_stock.read_slots', return_value=[]), \
                patch('module.island.island_business_stock.record_readings'), \
                patch('module.island.island_business_stock.load_defaults',
                      return_value={'juu_coffee': {'value': 'cheese',
                                                   'auto': 'apple_juice'}}), \
                patch('module.island.island_business_stock.save_defaults') as save:
            season_cls.return_value.season = 'autumn'
            host._rotate_away_cook('juu_coffee', {})
        host.config.cross_set.assert_not_called()
        host.config.update.assert_not_called()
        save.assert_called_once_with({})

    def test_missing_replaced_by_high_profit_in_stock(self):
        host = FakeBusiness([make_item(n) for n in self.pool], self.active)
        counts = {'tofu_combo': 6, 'hearty_meal': 0, 'tofu_meat': 2,
                  'fo_tiao': 1, 'double_bamboo_shoots': 4}  # 绵玉定食没货
        new_products, replacements = host.replace_missing_products('有鱼餐馆', counts)
        self.assertEqual(len(replacements), 1)
        missing, candidate, stock = replacements[0]
        self.assertEqual(missing, 'hearty_meal')
        self.assertEqual(candidate, 'double_bamboo_shoots')  # 有货且利润最高
        self.assertEqual(stock, 4)
        self.assertIn('double_bamboo_shoots', [p['name'] for p in new_products])
        self.assertNotIn('hearty_meal', [p['name'] for p in new_products])

    def test_all_zero_keeps_original(self):
        host = FakeBusiness([make_item(n) for n in self.pool], self.active)
        counts = {n: 0 for n in self.pool}  # 全店都没货
        new_products, replacements = host.replace_missing_products('有鱼餐馆', counts)
        self.assertEqual(replacements, [])
        self.assertEqual([p['name'] for p in new_products],
                         ['tofu_combo', 'hearty_meal', 'tofu_meat', 'fo_tiao'])

    def test_candidate_not_reused_twice(self):
        """同一替补只能占一个位置，第二个缺货位保持原样"""
        host = FakeBusiness([make_item(n) for n in self.pool], self.active)
        counts = {'tofu_combo': 0, 'hearty_meal': 0, 'tofu_meat': 2,
                  'fo_tiao': 1, 'double_bamboo_shoots': 3}
        new_products, replacements = host.replace_missing_products('有鱼餐馆', counts)
        self.assertEqual(len(replacements), 1)
        self.assertEqual(replacements[0][0], 'tofu_combo')
        self.assertEqual(replacements[0][1], 'double_bamboo_shoots')
        names = [p['name'] for p in new_products]
        self.assertEqual(names.count('double_bamboo_shoots'), 1)
        self.assertIn('hearty_meal', names)

    def test_unknown_stock_keeps_original(self):
        """没有仓库模板（库存 -1）的商品保持原配置，不当作缺货处理"""
        host = FakeBusiness([make_item(n) for n in self.pool], self.active)
        counts = {'tofu_combo': 6, 'hearty_meal': -1, 'tofu_meat': 2,
                  'fo_tiao': 1, 'double_bamboo_shoots': 4}
        new_products, replacements = host.replace_missing_products('有鱼餐馆', counts)
        self.assertEqual(replacements, [])
        self.assertIn('hearty_meal', [p['name'] for p in new_products])

    def test_rank_uses_economy_data(self):
        host = FakeBusiness([make_item(n) for n in self.pool], self.active)
        ranked = host.rank_shop_products('有鱼餐馆')
        self.assertEqual(ranked[0], 'tofu_combo')
        self.assertLess(ranked.index('tofu_combo'), ranked.index('fo_tiao'))

    def test_empty_products(self):
        host = FakeBusiness([], [])
        new_products, replacements = host.replace_missing_products('有鱼餐馆', {})
        self.assertEqual(new_products, [])
        self.assertEqual(replacements, [])


# Add by MHY, 校验库存识别到经营决策的链路，不把未知数量当成空仓。
class TestStockCheckReadings(unittest.TestCase):
    def make_host(self):
        host = FakeBusiness([make_item('tofu_combo'), make_item('hearty_meal')],
                            [make_item('tofu_combo')])
        host.device = Mock()
        host.goto_warehouse_within_postmanage = Mock()
        host._stock_check_template = Mock(side_effect=lambda shop, name: name)
        host._rotate_away_cook = Mock()
        return host

    def check(self, host, readings):
        with patch('module.island.island_business_stock.WarehouseOCR') as warehouse, \
                patch('module.island.island_business_stock.logger') as log, \
                patch('PIL.Image.fromarray'):
            warehouse.return_value.ocr_item_quantity.side_effect = readings
            result = host.check_configured_products_stock('有鱼餐馆')
            for call in warehouse.return_value.ocr_item_quantity.call_args_list:
                self.assertTrue(call.kwargs['strict'])
        return result, log

    def test_zero_stock_reports_shortage_even_without_any_positive_reading(self):
        host = self.make_host()
        result, log = self.check(host, [0, 0])
        self.assertEqual(result, 0)
        self.assertTrue(any('仍缺货且无替补' in str(c) for c in log.warning.call_args_list))
        self.assertFalse(any('库存充足' in str(c) for c in log.info.call_args_list))

    def test_unknown_item_is_preserved_with_stocked_alternative(self):
        host = self.make_host()
        result, log = self.check(host, [None, 6])
        self.assertEqual(result, 0)
        self.assertEqual(host.active_products['有鱼餐馆'][0]['name'], 'tofu_combo')
        self.assertTrue(any('库存未知' in str(c) for c in log.warning.call_args_list))
        self.assertFalse(any('库存充足' in str(c) for c in log.info.call_args_list))

    def test_known_empty_item_uses_stocked_alternative(self):
        host = self.make_host()
        result, _ = self.check(host, [0, 6])
        self.assertEqual(result, 1)
        self.assertEqual(host.active_products['有鱼餐馆'][0]['name'], 'hearty_meal')

    def test_unreadable_page_still_checks_stale_auto_configuration(self):
        host = self.make_host()
        result, log = self.check(host, [None, None])
        self.assertEqual(result, 0)
        host._rotate_away_cook.assert_called_once_with(
            'restaurant', {'tofu_combo': -1, 'hearty_meal': -1})
        self.assertFalse(any('库存充足' in str(c) for c in log.info.call_args_list))

    def test_winter_restores_old_auto_value_without_rotating_finite_tasks(self):
        host = self.make_host()
        host.config = Mock()
        host.config.cross_get.return_value = 'salad'
        with patch('module.island.island_business_stock.SeasonConfig') as season, \
                patch('module.island.island_business_stock.read_slots') as slots, \
                patch('module.island.island_business_stock.load_defaults',
                      return_value={'restaurant': 'tofu'}), \
                patch('module.island.island_business_stock.save_defaults') as save, \
                patch('module.island.island_business_stock.record_readings'):
            season.return_value.season = 'winter'
            BusinessStockCheckMixin._rotate_away_cook(host, 'restaurant', {})
        slots.assert_not_called()
        host.config.cross_set.assert_called_once_with(
            'IslandRestaurant.IslandRestaurantNextTask.AwayCook', 'tofu')
        save.assert_called_once_with({})


if __name__ == '__main__':
    unittest.main()
