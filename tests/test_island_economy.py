"""
岛屿经济库离线测试：商品经济数据与查询（不连游戏，纯逻辑验证）。

方案生成相关测试见 test_island_planner.py。
"""
import unittest

from module.island.island_economy import (
    EconomyDatabase,
    ECONOMY_PRODUCTS,
    ECONOMY_SHOPS,
    SHOP_LEVELS,
    SALES_BOOST_CHARACTERS,
    CAPACITY_BOOST_CHARACTERS,
)


class TestEconomyDatabase(unittest.TestCase):
    """经济数据完整性与查询 API"""

    def test_data_coverage(self):
        """五家餐饮店都有数据，且每条数据字段完整"""
        shops_with_data = {v['shop'] for v in ECONOMY_PRODUCTS.values()}
        for shop in ECONOMY_SHOPS:
            self.assertIn(shop, shops_with_data, f'{shop} 缺少经济数据')
        for name, info in ECONOMY_PRODUCTS.items():
            self.assertIn('cn_name', info)
            self.assertIn('materials', info)
            self.assertGreater(info['time_min'], 0, f'{name} 时间非法')
            self.assertGreater(info['price'], 0, f'{name} 售价非法')
            self.assertGreaterEqual(info['profit'], 0, f'{name} 利润为负')

    def test_shop_of_each_product_is_known(self):
        for name, info in ECONOMY_PRODUCTS.items():
            self.assertIn(info['shop'], ECONOMY_SHOPS, f'{name} 店铺未知')

    def test_profit_per_min_ranking(self):
        """莓果香橙甜点组与花香果韵应是全库利润/分钟前二（wiki 结论）"""
        db = EconomyDatabase()
        top = db.sort_by_profit(list(ECONOMY_PRODUCTS.keys()))[:2]
        self.assertIn('berry_orange', top)
        self.assertIn('floral_fruity', top)

    def test_recommend_products_excludes_off_season(self):
        """非当季限定品不进推荐"""
        db = EconomyDatabase(season='autumn')
        names = [p['name'] for p in db.recommend_products('restaurant', season='autumn', top=20)]
        self.assertNotIn('double_bamboo_shoots', names)  # 春季限定
        self.assertIn('tofu_combo', names)               # 常驻

    def test_recommend_products_includes_current_season(self):
        db = EconomyDatabase(season='autumn')
        names = [p['name'] for p in db.recommend_products('restaurant', season='autumn', top=20)]
        self.assertIn('matsutake_chicken_soup', names)   # 秋季限定

    def test_filter_products(self):
        db = EconomyDatabase(season='spring')
        kept = db.filter_products(
            ['double_bamboo_shoots', 'tofu_combo', 'matsutake_chicken_soup'], season='spring')
        self.assertEqual(kept, ['double_bamboo_shoots', 'tofu_combo'])

    def test_expand_materials_recursive(self):
        """套餐递归分解到基础食材（经典豆腐套餐×7 → 大豆/鲜肉/白菜）"""
        db = EconomyDatabase()
        mats = db.expand_materials('tofu_combo', 7)
        self.assertEqual(mats['soybean'], 315)
        self.assertEqual(mats['pork'], 7)
        self.assertEqual(mats['chinese_cabbage'], 42)

    def test_batch_materials(self):
        db = EconomyDatabase()
        mats = db.batch_materials({'tofu_combo': 1, 'hearty_meal': 1})
        # tofu_combo → (tofu_meat(tofu×2) + cabbage_tofu(tofu×1)) = soybean 30+15
        # hearty_meal → (omurice + tofu×1) = soybean 15；合计 60
        self.assertEqual(mats['soybean'], 60)
        self.assertEqual(mats['pork'], 1)
        self.assertEqual(mats['egg'], 4)

    def test_shop_capacity_levels(self):
        self.assertEqual(EconomyDatabase.shop_capacity('bronze'), (2, 5, 10))
        self.assertEqual(EconomyDatabase.shop_capacity('silver'), (2, 6, 12))
        self.assertEqual(EconomyDatabase.shop_capacity('gold'), (3, 6, 18))
        self.assertEqual(EconomyDatabase.shop_capacity('diamond'), (4, 6, 24))

    def test_shop_capacity_boost_char(self):
        """长风全店每格+1"""
        slots, per_slot, cap = EconomyDatabase.shop_capacity('diamond', ['ChangFeng'])
        self.assertEqual(per_slot, 7)
        self.assertEqual(cap, 28)

    def test_sales_boost(self):
        """有鱼+肇和 10%；白熊+柴郡 5%；简餐+海伦娜/欧根可叠加到 20%"""
        db = EconomyDatabase()
        self.assertEqual(db.sales_boost('restaurant', ['ChaoHo']), 10.0)
        self.assertEqual(db.sales_boost('teahouse', ['Cheshire']), 5.0)
        self.assertEqual(db.sales_boost('juu_eatery', ['Helena', 'Eugen']), 20.0)
        self.assertEqual(db.sales_boost('restaurant', ['WorkerJuu']), 0.0)

    def test_cn_name(self):
        db = EconomyDatabase()
        self.assertEqual(db.cn_name('tofu_combo'), '经典豆腐套餐')
        self.assertEqual(db.cn_name('unknown_thing'), 'unknown_thing')

