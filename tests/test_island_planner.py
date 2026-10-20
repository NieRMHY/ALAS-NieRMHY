"""
岛屿方案生成器离线测试：解析、选品、上架、配置补丁（不连游戏）。

覆盖历史事故的回归点：
  - 只排本店代码实现了的商品（lemon_shrimp 这类 wiki 有、代码无的必须排除）
  - 芝士等"别家店铺的商品"不得出现在本店生产清单
  - 上架清单必须是配置项合法取值（否则 WebUI 校验报错）
"""
import json
import os
import tempfile
import unittest

import module.island.island_planner as planner
from module.island.island_economy import ECONOMY_PRODUCTS
from module.island.island_planner import (
    apply_patch,
    code_products,
    config_patch,
    load_unproducible,
    plan_all,
    plan_shop,
    save_unproducible,
    shelf_options,
    target_stock,
)


class TestCodeProducts(unittest.TestCase):
    """从商店源码解析本店可生产商品"""

    def test_grill_products(self):
        names = code_products('grill')
        self.assertIn('double_energy', names)
        self.assertIn('crayfish_stir_fry', names)  # 代码里有按钮，只是账号未解锁
        self.assertNotIn('lemon_shrimp', names)    # wiki 有、代码没有

    def test_all_shops_non_empty(self):
        for shop in ('restaurant', 'teahouse', 'juu_eatery', 'grill', 'juu_coffee'):
            with self.subTest(shop=shop):
                self.assertGreaterEqual(len(code_products(shop)), 5)


class TestShelfOptions(unittest.TestCase):
    """上架候选来自配置项定义，保证方案一定能被校验接受"""

    def test_options_match_shop(self):
        self.assertIn('tofu_combo', shelf_options('restaurant'))
        self.assertIn('double_energy', shelf_options('grill'))
        self.assertNotIn('None', shelf_options('restaurant'))


class TestPlanShop(unittest.TestCase):
    """方案内容"""

    def setUp(self):
        fd, path = tempfile.mkstemp(suffix='.json')
        os.close(fd)
        os.remove(path)
        self._orig = planner.UNPRODUCIBLE_FILE
        planner.UNPRODUCIBLE_FILE = path

    def tearDown(self):
        try:
            os.remove(planner.UNPRODUCIBLE_FILE)
        except OSError:
            pass
        planner.UNPRODUCIBLE_FILE = self._orig

    def test_meals_only_producible(self):
        """生产清单只含本店代码实现的商品"""
        for shop in ('restaurant', 'teahouse', 'juu_eatery', 'grill', 'juu_coffee'):
            plan = plan_shop(shop, season='autumn')
            names = {n for n, _ in plan.meals}
            with self.subTest(shop=shop):
                self.assertTrue(names)
                self.assertTrue(names <= code_products(shop))

    def test_no_foreign_shop_product(self):
        """芝士是咖啡店商品，简餐生产清单不得出现（历史 KeyError 事故）"""
        plan = plan_shop('juu_eatery', season='autumn')
        self.assertNotIn('cheese', {n for n, _ in plan.meals})

    def test_exclude_recorded(self):
        plan = plan_shop('grill', season='autumn', exclude={'crayfish_stir_fry'})
        names = {n for n, _ in plan.meals}
        self.assertNotIn('crayfish_stir_fry', names)
        self.assertNotIn('crayfish_stir_fry', plan.shelf)
        self.assertTrue(any('爆炒小龙虾' in note for note in plan.notes))

    def test_shelf_subset_of_shelf_options(self):
        """上架清单必须是 Product1-5 的合法取值"""
        for shop in ('restaurant', 'teahouse', 'juu_eatery', 'grill', 'juu_coffee'):
            plan = plan_shop(shop, season='autumn')
            with self.subTest(shop=shop):
                self.assertTrue(plan.shelf)
                self.assertTrue(set(plan.shelf) <= set(shelf_options(shop)))

    def test_shelf_consistent_with_production(self):
        """货架商品必须在生产清单里（否则那格迟早空掉）"""
        plan = plan_shop('grill', season='autumn', exclude={'crayfish_stir_fry'})
        meals = {n for n, _ in plan.meals}
        self.assertTrue(plan.shelf)
        self.assertTrue(set(plan.shelf) <= meals)

    def test_shelf_sorted_by_profit(self):
        """货架按单件利润排序：每格每天固定卖 per_slot 件，一格收益 = 6 x 单件利润"""
        for shop in ('restaurant', 'teahouse', 'juu_eatery', 'grill', 'juu_coffee'):
            plan = plan_shop(shop, season='autumn')
            profits = [ECONOMY_PRODUCTS[n]['profit'] for n in plan.shelf]
            with self.subTest(shop=shop):
                self.assertTrue(plan.shelf)
                self.assertEqual(profits, sorted(profits, reverse=True))

    def test_shelf_prefers_profit_over_price(self):
        """售价高但单件利润低的商品不该排在售价低但利润高的前面。

        货架每格每天固定卖 6 件，一格的价值是 6 x 单件利润；按售价排序会把
        「进货贵」当成「赚得多」。洋葱蒸鱼售价 420 < 白菜豆腐汤 425，但单件利润
        356.67 > 351.65（材料成本更低）。
        """
        cheap_price, high_price = 'onion_fish', 'cabbage_tofu'
        self.assertLess(ECONOMY_PRODUCTS[cheap_price]['price'],
                        ECONOMY_PRODUCTS[high_price]['price'])
        self.assertGreater(ECONOMY_PRODUCTS[cheap_price]['profit'],
                           ECONOMY_PRODUCTS[high_price]['profit'])
        plan = plan_shop('restaurant', season='autumn',
                         shelf_pool=[high_price, cheap_price],
                         producible={high_price, cheap_price}, shelf_slots=1)
        self.assertEqual(plan.shelf, [cheap_price])

    def test_extra_meals_off_by_default(self):
        """默认只排货架补货：不在货架上的商品卖不掉，排进清单只是白占槽位"""
        plan = plan_shop('restaurant', season='autumn')
        meals = {n for n, _ in plan.meals}
        self.assertTrue(plan.shelf)
        self.assertTrue(meals <= set(plan.shelf), f'多出非货架商品: {meals - set(plan.shelf)}')

    def test_extra_meals_on_adds_items(self):
        """打开开关才用剩余工时生产货架之外的额外商品"""
        off = plan_shop('restaurant', season='autumn')
        on = plan_shop('restaurant', season='autumn', extra_meals=True)
        extra = {n for n, _ in on.meals} - set(on.shelf)
        self.assertTrue(extra, '打开开关后应多出不在货架上的商品')
        self.assertLessEqual(len(on.meals), planner.MEAL_SLOTS)
        self.assertLess(len(off.meals), len(on.meals))

    def test_stockpile_reserves_a_meal_slot(self):
        """有囤积待排时留最后一格：货架 + 额外项本来会占满 8 格，囤积仍要排得进去。

        真机风险：额外餐品循环排在囤积之前，8 格填满后囤积那段直接 break，
        赛季任务永远排不进生产清单。
        """
        full = plan_shop('teahouse', season='autumn', extra_meals=True)
        self.assertEqual(len(full.meals), planner.MEAL_SLOTS,
                         '此用例依赖「额外项本身能填满 8 格」的前提')
        plan = plan_shop('teahouse', season='autumn', extra_meals=True,
                         stockpile={'apple_juice': 250}, stock_have={'apple_juice': 0})
        names = {n for n, _ in plan.meals}
        self.assertLessEqual(len(plan.meals), planner.MEAL_SLOTS)
        self.assertIn('apple_juice', names)
        self.assertEqual(plan.meals[-1], ('apple_juice', 250))
        self.assertEqual(plan.stockpile, [('apple_juice', 250)])

    def test_seasonal_filter(self):
        """秋季方案不含春夏限定品"""
        plan = plan_shop('restaurant', season='autumn')
        meals = {n for n, _ in plan.meals}
        self.assertNotIn('double_bamboo_shoots', meals)   # 春
        self.assertNotIn('amaranth_rice_ball', meals)     # 夏

    def test_warehouse_filter(self):
        """传入仓库库存后，没货的商品不上架"""
        plan = plan_shop('restaurant', season='autumn',
                         warehouse={'tofu_combo': 5, 'hearty_meal': 0})
        self.assertIn('tofu_combo', plan.shelf)
        self.assertNotIn('hearty_meal', plan.shelf)
        self.assertTrue(any('无库存' in note for note in plan.notes))

    def test_level_changes_stock(self):
        """等级越高单格容量越大，目标库存随之提高"""
        self.assertLess(target_stock('restaurant', 'tofu_combo', 'bronze'),
                        target_stock('restaurant', 'tofu_combo', 'diamond'))

    def test_quantity_positive(self):
        plan = plan_shop('juu_coffee', season='autumn')
        self.assertTrue(all(q >= 2 for _, q in plan.meals))


class TestPostNumberCapacity(unittest.TestCase):
    """产能按各店岗位数算，不再是「每店 2 岗」的固定口径。

    真机五家店的 PostNumber 都是 2，而代码默认值镜像 argument.yaml 是
    2/2/1/1/2；旧的固定口径把 1 岗的店高估一倍产能，方案排到货架上的东西
    根本做不出来。
    """

    def setUp(self):
        fd, path = tempfile.mkstemp(suffix='.json')
        os.close(fd)
        os.remove(path)
        self._orig = planner.UNPRODUCIBLE_FILE
        planner.UNPRODUCIBLE_FILE = path

    def tearDown(self):
        try:
            os.remove(planner.UNPRODUCIBLE_FILE)
        except OSError:
            pass
        planner.UNPRODUCIBLE_FILE = self._orig

    def test_capacity_follows_post_number(self):
        self.assertEqual(planner.capacity_hours('grill', 1), 24.0)
        self.assertEqual(planner.capacity_hours('grill', 2), 48.0)
        # 缺省取 argument.yaml 的默认岗位数（烤肉/简餐 1，餐馆/白熊/咖啡 2）
        self.assertEqual(planner.capacity_hours('grill'), 24.0)
        self.assertEqual(planner.capacity_hours('restaurant'), 48.0)

    def test_one_post_cuts_shelf_by_budget(self):
        one = plan_shop('restaurant', season='autumn', post_number=1)
        two = plan_shop('restaurant', season='autumn', post_number=2)
        self.assertEqual((one.post_number, one.capacity_hours), (1, 24.0))
        self.assertEqual((two.post_number, two.capacity_hours), (2, 48.0))
        # 1 岗预算 21.6 时：装不下的货架商品要被裁掉
        self.assertLess(len(one.shelf), len(two.shelf))
        self.assertTrue(any('预算 21.6 时' in note for note in one.notes))

    def test_plan_all_passes_post_numbers(self):
        plans = plan_all(shops=['restaurant', 'grill'], season='autumn',
                         post_numbers={'restaurant': 1, 'grill': 2})
        self.assertEqual(plans['restaurant'].post_number, 1)
        self.assertEqual(plans['grill'].post_number, 2)
        self.assertIn('1 岗位 x 24 时', ' '.join(plans['restaurant'].notes))
        self.assertIn('2 岗位 x 24 时', ' '.join(plans['grill'].notes))

    def test_stockpile_keeps_target_and_reports_days(self):
        """囤积目标数量照排，只用剩余日产能算「预计几天」。

        MealNumber 是库存目标：写小了运行端做到那个数就停，而缺口没消失时不会再有
        事件触发刷新，赛季任务会卡在半路。
        """
        one = plan_shop('grill', season='autumn', post_number=1,
                        exclude={'crayfish_stir_fry'},
                        stockpile={'stir_fried_chicken': 120},
                        stock_have={'stir_fried_chicken': 20})
        two = plan_shop('grill', season='autumn', post_number=2,
                        exclude={'crayfish_stir_fry'},
                        stockpile={'stir_fried_chicken': 120},
                        stock_have={'stir_fried_chicken': 20})
        for plan in (one, two):
            self.assertEqual(plan.meals[-1], ('stir_fried_chicken', 120),
                             '目标数量不该被产能截断')
            self.assertEqual(plan.stockpile[-1], ('stir_fried_chicken', 120))
        notes_one = ' '.join(one.notes)
        notes_two = ' '.join(two.notes)
        self.assertIn('预计', notes_one, '超一天的量要报预期天数')
        self.assertIn('天完成', notes_one)
        # 2 岗比 1 岗每天能做的多，预计天数更短
        self.assertLess(self._days(notes_two), self._days(notes_one))

    @staticmethod
    def _days(notes):
        """从说明里取「预计 X 天」的 X。"""
        import re
        match = re.search(r'预计 ([0-9.]+) 天完成', notes)
        return float(match.group(1)) if match else 0.0

    def test_stockpile_never_blocked_by_budget(self):
        """预算装不下整件也照样排：不做 = 赛季任务永远不推进。"""
        plan = plan_shop('restaurant', season='autumn', post_number=1,
                         stockpile={'persimmon_cake': 120})
        self.assertEqual(plan.meals[-1], ('persimmon_cake', 120))
        self.assertIn('预计', ' '.join(plan.notes))


class TestUnproducibleList(unittest.TestCase):
    """未解锁名单（方案侧的排除输入）"""

    def setUp(self):
        fd, path = tempfile.mkstemp(suffix='.json')
        os.close(fd)
        os.remove(path)
        self._orig = planner.UNPRODUCIBLE_FILE
        planner.UNPRODUCIBLE_FILE = path

    def tearDown(self):
        try:
            os.remove(planner.UNPRODUCIBLE_FILE)
        except OSError:
            pass
        planner.UNPRODUCIBLE_FILE = self._orig

    def test_save_load_roundtrip(self):
        self.assertEqual(load_unproducible('grill'), set())
        save_unproducible('grill', {'crayfish_stir_fry'})
        self.assertEqual(load_unproducible('grill'), {'crayfish_stir_fry'})
        save_unproducible('grill', set())
        self.assertEqual(load_unproducible('grill'), set())

    def test_plan_respects_file(self):
        save_unproducible('grill', {'carnival'})
        plan = plan_shop('grill', season='autumn')
        self.assertNotIn('carnival', {n for n, _ in plan.meals})


class TestConfigPatch(unittest.TestCase):
    """配置补丁结构"""

    def test_patch_shape(self):
        patch = config_patch(plan_all(season='autumn'))
        for task in ('IslandRestaurant', 'IslandTeahouse', 'IslandJuuEatery',
                     'IslandGrill', 'IslandJuuCoffee'):
            self.assertIn(task, patch)
            group = patch[task][task]
            self.assertEqual(len([k for k in group if k.startswith('Meal') and
                                  not k.startswith('MealNumber')]), 8)
        business = patch['IslandBusiness']
        for index in '12345':
            self.assertIn(f'IslandBusinessShop{index}', business)
            self.assertEqual(len([k for k in business[f'IslandBusinessShop{index}']
                                  if k.startswith('Product')]), 5)

    def test_empty_slots_cleared(self):
        """商品不足 8 个时，多余槽位必须清空而不是留旧值"""
        plans = plan_all(shops=['grill'], season='autumn',
                         extra_exclude={'grill': {'crayfish_stir_fry'}})
        self.assertLess(len(plans['grill'].meals), 8)
        group = config_patch(plans)['IslandGrill']['IslandGrill']
        self.assertEqual(group['Meal8'], 'None')
        self.assertEqual(group['MealNumber8'], 0)

    def test_apply_patch_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'ALAS.json')
            original = {'IslandGrill': {'IslandGrill': {'Meal1': 'old', 'PostNumber': 2}},
                        'IslandBusiness': {'IslandBusinessShop4': {'Product1': 'old'}},
                        'Other': {'Keep': 1}}
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(original, f)
            patch = config_patch(plan_all(shops=['grill'], season='autumn'))
            backup = apply_patch(path, patch)
            self.assertTrue(os.path.exists(backup))
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
            self.assertNotEqual(data['IslandGrill']['IslandGrill']['Meal1'], 'old')
            self.assertEqual(data['IslandGrill']['IslandGrill']['PostNumber'], 2)
            self.assertEqual(data['Other'], {'Keep': 1})
            self.assertIn('IslandBusinessShop4', data['IslandBusiness'])


if __name__ == '__main__':
    unittest.main()
