"""
经营端库存校验的离线测试：只测纯逻辑（不连游戏、不截图）。

对应缺口：配置商品仓库没货时，上架会静默失败（格子空着）。
"""
import unittest

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


if __name__ == '__main__':
    unittest.main()
