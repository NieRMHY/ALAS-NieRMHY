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

    def test_shelf_prefers_planned_products(self):
        """上架优先卖自己会补货的商品"""
        plan = plan_shop('grill', season='autumn', exclude={'crayfish_stir_fry'})
        meals = {n for n, _ in plan.meals}
        self.assertIn(plan.shelf[0], meals)
        self.assertGreaterEqual(len(set(plan.shelf) & meals), 4)

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
        self.assertEqual(len(plans['grill'].meals), 7)
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
