"""
岛屿经济闭环离线测试：经济数据库 + AutoProfit 感知生产规划器。

不连游戏、不依赖设备，全部纯逻辑验证（仿照 test_island_shop_production 的离线模式）。
"""
import os
import unittest

from module.island.island_economy import (
    EconomyDatabase,
    ECONOMY_PRODUCTS,
    ECONOMY_SHOPS,
    SHOP_LEVELS,
    SALES_BOOST_CHARACTERS,
    CAPACITY_BOOST_CHARACTERS,
)
from module.island.island_autoprofit import (
    AutoProfitPlanner,
    IslandEconomyConfigError,
    merge_autoprofit_with_manual,
    get_autoprofit_planner,
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


class TestAutoProfitPlanner(unittest.TestCase):
    """感知生产规划器"""

    def test_unknown_shop_raises_config_error(self):
        with self.assertRaises(IslandEconomyConfigError):
            AutoProfitPlanner('manufacture')

    def test_factory_returns_none_for_manufacture(self):
        """制造工坊走 PT 体系，工厂函数返回 None 保持原行为"""
        self.assertIsNone(get_autoprofit_planner('manufacture'))

    def test_target_stock_follows_level(self):
        """店铺等级越高目标库存越大"""
        bronze = AutoProfitPlanner('restaurant', shop_level='bronze')
        diamond = AutoProfitPlanner('restaurant', shop_level='diamond')
        self.assertGreater(
            diamond.target_stock('tofu_combo'),
            bronze.target_stock('tofu_combo'))

    def test_build_plan_respects_stock(self):
        """已有充足库存的商品不再排产"""
        p = AutoProfitPlanner('restaurant', shop_level='diamond')
        target = p.target_stock('tofu_combo')
        plan = p.build_plan({'tofu_combo': target + 10}, season='autumn')
        names = [n for n, _ in plan]
        self.assertNotIn('tofu_combo', names)

    def test_build_plan_counts_in_production(self):
        """在制品计入当前库存，避免重复排产"""
        p = AutoProfitPlanner('restaurant', shop_level='diamond')
        target = p.target_stock('tofu_combo')
        plan_no_wip = p.build_plan({}, season='autumn')
        plan_with_wip = p.build_plan(
            {}, in_production={'tofu_combo': target}, season='autumn')
        qty_no = dict(plan_no_wip).get('tofu_combo', 0)
        qty_wip = dict(plan_with_wip).get('tofu_combo', 0)
        self.assertLess(qty_wip, qty_no)

    def test_build_plan_profit_order(self):
        """主计划（套餐部分）按利润/分钟降序；原料联动追加项在尾部不参与排序"""
        p = AutoProfitPlanner('juu_eatery', shop_level='gold')
        plan = p.build_plan({}, season='spring')
        self.assertTrue(len(plan) >= 2)
        db = EconomyDatabase()
        rates = [db.profit_per_min(n) for n, _ in plan]
        # 联动原料项（如套餐原料 corn_cup）可能追加在尾部，只校验首项为最大
        self.assertEqual(rates[0], max(rates))

    def test_merge_manual_slots_floor(self):
        """手动槽位保底：同名取最大值"""
        auto = [('tofu_combo', 5)]
        manual = {'tofu_combo': 7, 'tofu_meat': 3}
        merged = dict(merge_autoprofit_with_manual(auto, manual))
        self.assertEqual(merged['tofu_combo'], 7)
        self.assertEqual(merged['tofu_meat'], 3)

    def test_build_plan_filters_unproducible(self):
        """经济库中代码未实现的商品（无按钮资源）不参与排产，避免 KeyError"""
        p = AutoProfitPlanner('grill')
        available = {'roasted_skewer', 'chicken_potato', 'stir_fried_chicken',
                     'carrot_omelette', 'steak_bowl', 'crayfish_stir_fry',
                     'carnival', 'double_energy'}
        # 不传 available：lemon_shrimp（利润高）会被选中
        plan_all = [n for n, _ in p.build_plan({}, season='autumn')]
        self.assertIn('lemon_shrimp', plan_all)
        # 传 available（代码可生产列表）：被过滤掉
        plan_filtered = [n for n, _ in p.build_plan({}, season='autumn', available=available)]
        self.assertNotIn('lemon_shrimp', plan_filtered)
        self.assertTrue(set(plan_filtered) <= available)

    def test_min_deficit_threshold(self):
        """缺口小于阈值不排产"""
        p = AutoProfitPlanner('restaurant', shop_level='bronze')
        target = p.target_stock('tofu_combo')
        # 缺口 1（低于 AUTOPROFIT_MIN_DEFICIT=2）
        plan = p.build_plan({'tofu_combo': target - 1}, season='autumn')
        names = [n for n, _ in plan]
        self.assertNotIn('tofu_combo', names)


class TestSupportPlan(unittest.TestCase):
    """空岗填充的原料保障：填充商品缺上游原料时先造原料"""

    def test_coffee_missing_iced_coffee(self):
        """啾咖啡：醒神套餐缺冰咖啡 → 冰咖啡进保障计划"""
        p = AutoProfitPlanner('juu_coffee')
        plan = p.support_plan('wake_up_call', {'cheese': 21, 'iced_coffee': 0},
                              exclude=set())
        names = [n for n, _ in plan]
        self.assertIn('iced_coffee', names)
        self.assertNotIn('cheese', names)  # 芝士充足不需要补

    def test_eatery_missing_orange_pie(self):
        """啾啾简餐：莓果香橙甜点组缺香橙派 → 香橙派进保障计划"""
        p = AutoProfitPlanner('juu_eatery')
        plan = p.support_plan('berry_orange',
                              {'strawberry_charlotte': 23, 'orange_pie': 0})
        names = [n for n, _ in plan]
        self.assertIn('orange_pie', names)
        self.assertNotIn('strawberry_charlotte', names)

    def test_no_support_when_materials_enough(self):
        """原料充足时保障计划为空"""
        p = AutoProfitPlanner('juu_coffee')
        plan = p.support_plan('wake_up_call', {'cheese': 99, 'iced_coffee': 99})
        self.assertEqual(plan, [])

    def test_eatery_must_not_plan_cheese(self):
        """真机事故回归：芝士是咖啡店商品，简餐只能当材料用，不得排产"""
        p = AutoProfitPlanner('juu_eatery')
        # 简餐可生产列表（无 cheese）
        eatery_items = {'apple_pie', 'corn_cup', 'orange_pie', 'banana_crepe',
                        'orchard_duo', 'rice_mango', 'succulently_sweet',
                        'berry_orange', 'strawberry_charlotte', 'seafood_rice'}
        plan = p.support_plan('berry_orange', {}, available=eatery_items)
        names = [n for n, _ in plan]
        self.assertNotIn('cheese', names)
        self.assertTrue(set(names) <= eatery_items)

    def test_coffee_can_plan_cheese(self):
        """咖啡店可以生产芝士，保障计划允许包含"""
        p = AutoProfitPlanner('juu_coffee')
        coffee_items = {'omelette', 'iced_coffee', 'cheese', 'latte',
                        'citrus_coffee', 'strawberry_milkshake',
                        'morning_light', 'wake_up_call', 'fruity_fruitier'}
        plan = p.support_plan('wake_up_call', {}, available=coffee_items)
        names = [n for n, _ in plan]
        self.assertIn('cheese', names)  # 芝士在该店可生产

    def test_exclude_respected(self):
        """不可生产名单内的原料不进保障计划"""
        p = AutoProfitPlanner('juu_coffee')
        plan = p.support_plan('wake_up_call', {'cheese': 0, 'iced_coffee': 0},
                              exclude={'iced_coffee'})
        names = [n for n, _ in plan]
        self.assertNotIn('iced_coffee', names)


class TestUnproducibleList(unittest.TestCase):
    """不可生产名单的持久化与解除（账号解锁后恢复排产）"""

    def setUp(self):
        import tempfile
        import module.island.island_autoprofit as ap
        self.ap = ap
        self._orig = ap.UNPRODUCIBLE_FILE
        fd, path = tempfile.mkstemp(suffix='.json')
        os.close(fd)
        os.remove(path)
        ap.UNPRODUCIBLE_FILE = path

    def tearDown(self):
        import os as _os
        try:
            _os.remove(self.ap.UNPRODUCIBLE_FILE)
        except OSError:
            pass
        self.ap.UNPRODUCIBLE_FILE = self._orig

    def test_add_load_remove_cycle(self):
        """加入名单 → 读取到 → 解除 → 名单清空"""
        self.assertEqual(self.ap.load_unproducible('grill'), set())
        self.ap.add_unproducible('grill', 'crayfish_stir_fry')
        self.assertEqual(self.ap.load_unproducible('grill'), {'crayfish_stir_fry'})
        self.ap.remove_unproducible('grill', 'crayfish_stir_fry')
        self.assertEqual(self.ap.load_unproducible('grill'), set())

    def test_remove_keeps_other_shops(self):
        """解除一个店铺的商品不影响其他店铺名单"""
        self.ap.add_unproducible('grill', 'crayfish_stir_fry')
        self.ap.add_unproducible('teahouse', 'pineapple_juice')
        self.ap.remove_unproducible('grill', 'crayfish_stir_fry')
        self.assertEqual(self.ap.load_unproducible('grill'), set())
        self.assertEqual(self.ap.load_unproducible('teahouse'), {'pineapple_juice'})

    def test_blacklisted_excluded_from_plan(self):
        """名单内商品不参与排产，解除后重新参与"""
        p = AutoProfitPlanner('grill')
        blacklist = {'crayfish_stir_fry'}
        plan = [n for n, _ in p.build_plan({}, season='autumn', exclude=blacklist)]
        self.assertNotIn('crayfish_stir_fry', plan)
        plan2 = [n for n, _ in p.build_plan({}, season='autumn', exclude=set())]
        self.assertIn('crayfish_stir_fry', plan2)


class TestShopBaseHook(unittest.TestCase):
    """店铺基类挂点：不开启时零行为变化"""

    def test_hook_methods_exist(self):
        from module.island.island_shop_base import IslandShopBase
        self.assertTrue(hasattr(IslandShopBase, 'setup_autoprofit'))
        self.assertTrue(hasattr(IslandShopBase, 'refresh_autoprofit_targets'))

    def test_refresh_noop_when_disabled(self):
        """未启用时 refresh_autoprofit_targets 是空操作（不触碰 post_products）"""
        from module.island.island_shop_base import IslandShopBase

        class FakeShop:
            autoprofit_enabled = False
            autoprofit_planner = None
            post_products = [('tofu', 7)]

        shop = FakeShop()
        IslandShopBase.refresh_autoprofit_targets(shop)
        self.assertEqual(shop.post_products, [('tofu', 7)])


if __name__ == '__main__':
    unittest.main()
