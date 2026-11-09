"""
岛屿规划离线测试：本地方案生成器（module/island/island_planner）与移植规划器（module/island_planner）。

前一部分覆盖本地方案生成器（Add by MHY，自研）：
  - 只排本店代码实现了的商品（lemon_shrimp 这类 wiki 有、代码无的必须排除）
  - 芝士等"别家店铺的商品"不得出现在本店生产清单
  - 上架清单必须是配置项合法取值（否则 WebUI 校验报错）
  - 单件利润排序、岗位数产能、额外餐品开关、赛季囤积

后一部分覆盖上游移植的岛屿生产规划器（Add by MHY, 合并 upstream 的
module/island_planner 后并入本文件，两套实现的回归都保留）：
  - 物品/菜品名映射、餐厅与服务员、作物目标、产线岗位数
  - 线性规划求解（含优先级二次求解）与写回配置
  - 科技扫描、季节任务扫描、货运缺口识别的纯逻辑部分
"""
import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
import yaml

import module.config.server as server
import module.island.island_planner as planner
from module.island.farm_targets import parse_crop_targets
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
from module.island_planner import settings_map as sm
from module.island_planner.calculator import ProductionPlanCalculator
from module.island_planner.data import (
    DIC_ISLAND_ITEM,
    DIC_ISLAND_RECIPE,
    DIC_ISLAND_SEASON,
    DIC_ISLAND_TECHNOLOGY,
)
from module.island_planner.utils import get_current_activity_list


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
# ==================== 岛屿生产规划器（module/island_planner，移植自 ALAS） ====================

ROOT = Path(__file__).resolve().parents[1]
ARGUMENT = yaml.safe_load((ROOT / 'module/config/argument/argument.yaml').read_text(encoding='utf-8'))
ARGS = json.loads((ROOT / 'module/config/argument/args.json').read_text(encoding='utf-8'))
NOW = datetime(2026, 10, 27, 12)


def options(group, key):
    return [name for name in ARGUMENT[group][key]['option'] if name != 'None']


MEAL_OPTIONS = {rid: options(k['task'], 'Meal1') for rid, k in sm.KITCHENS.items()}
PRODUCT_OPTIONS = {rid: options(k['business'], 'Product1') for rid, k in sm.KITCHENS.items()}


def solve(technology, grades='gold', chars=('WorkerJuu', 'WorkerJuu'), profit=50000, open_ids=None, slot_limit=None):
    calculator = ProductionPlanCalculator(
        technology,
        activity_list=get_current_activity_list(NOW),
        restaurant_settings=sm.restaurant_settings(
            {rid: grades for rid in sm.KITCHENS}, {rid: chars for rid in sm.KITCHENS}, open_ids),
        daily_profit_lower_limit=profit,
        slot_limit=slot_limit,
    )
    excluded = sm.restrict_calculator(calculator, MEAL_OPTIONS, PRODUCT_OPTIONS)
    calculator.solve_production_plan(current_time=NOW)
    return calculator, excluded


class NameMappingTest(unittest.TestCase):
    def setUp(self):
        self.previous_server = server.server
        server.server = 'en'

    def tearDown(self):
        server.server = self.previous_server

    def test_english_names_on_cn_server_keep_producible_identity(self):
        from module.island_planner.planner import parse_targets, resolve_item
        from module.island_planner.utils import normalize_item_id

        server.server = 'cn'
        matches = [item_id for item_id, item in DIC_ISLAND_ITEM.items()
                   if item['name']['en'] == 'Corn']
        expected = next((item_id for item_id in matches
                         if item_id in ProductionPlanCalculator.RECIPE_PRODUCT_IDS), matches[0])
        self.assertEqual(resolve_item('Corn'), expected)
        self.assertIn(normalize_item_id('Corn'), matches)
        self.assertEqual(parse_targets('Corn: 200', 'ExtraTargets'), {expected: [200]})

    def test_every_azurpilot_dish_option_has_an_item(self):
        # Modify by MHY, 第 5 季数据已并入（见 test_island_winter_logic），冬季菜品不再是
        # 「规划器不支持」的例外：配置里的每个菜品选项都必须有物品映射
        for rid, kitchen in sm.KITCHENS.items():
            for name in MEAL_OPTIONS[rid] + PRODUCT_OPTIONS[rid]:
                self.assertIn(name, sm.DISH_ITEM_IDS, f'{kitchen["task"]}: {name}')
        for item_id in sm.DISH_ITEM_IDS.values():
            self.assertIn(item_id, DIC_ISLAND_ITEM)

    def test_every_crop_is_produced_by_a_recipe(self):
        products = {next(iter(r['commission_product'])) for r in DIC_ISLAND_RECIPE.values()}
        for area, crops in sm.CROP_ITEM_IDS.items():
            for crop, item_id in crops.items():
                self.assertIn(item_id, products, f'{area}: {crop}')

    def test_waitress_slots(self):
        # 有鱼餐馆：肇和有加成，柴郡对本店无加成视为 any；None 由工作啾代班，也视为 any
        self.assertEqual(sm.waitress_slots(601, ('ChaoHo', 'Cheshire')), ('Chao_Ho', 'any'))
        self.assertEqual(sm.waitress_slots(602, ('Cheshire', 'None')), ('Cheshire', 'any'))
        self.assertEqual(sm.waitress_slots(603, ('Eugen', 'Eugen')), ('Prinz_Eugen', 'any'))
        with self.assertRaises(ValueError):
            sm.restaurant_settings({601: 'platinum'}, {})

    def test_open_restaurants(self):
        self.assertEqual(sm.open_restaurants(False, [], []), set(sm.KITCHENS))
        # 默认分批 [3, 1, 5] + [2, 4] 覆盖全部五家
        self.assertEqual(sm.open_restaurants(True, [3, 1, 5], [2, 4]), set(sm.KITCHENS))
        self.assertEqual(sm.open_restaurants(True, [1], ['5']), {601, 901})
        settings = sm.restaurant_settings({}, {}, open_ids={601})
        self.assertEqual(settings[602]['waitress_slots'], ('none', 'none'))
        self.assertEqual(settings[601]['waitress_slots'], ('any', 'any'))


class SeasonScannerRetryTest(unittest.TestCase):
    def test_retry_when_no_task_rows_found(self):
        from unittest.mock import Mock

        import numpy as np

        from module.island_planner.season_tasks import IslandSeasonTaskScanner

        scanner = IslandSeasonTaskScanner.__new__(IslandSeasonTaskScanner)
        scanner.loop = Mock(return_value=range(2))
        scanner._task_rows = Mock(side_effect=[np.empty((0, 2)), np.array([[0., 40.]])])
        self.assertEqual(len(scanner.season_task_grid.buttons), 3)
        self.assertEqual(scanner._task_rows.call_count, 2)


class FakeCalculatorTest(unittest.TestCase):
    """用假结果检查后厨/商区/作物的换算规则。"""

    def make(self):
        return SimpleNamespace(
            restaurant_capacity={rid: 6 for rid in sm.KITCHENS},
            # 豆腐 40/天（中间品），肉末烧豆腐卖 6、日缓冲 6，套餐卖 3
            production_plan={601001: 40 / 1, 601002: 6, 601101: 3, 101005: 1},
            recipe_group={601001: 'koi', 601002: 'koi', 601101: 'koi', 101005: 'field'},
            sell_plan={(601, 3012): 6, (601, 3101): 3},
            product_daily_buffer_items={3011: 12, 3012: 9, 3101: 3, 2002: 20},
            idle_accumulating_items_per_day={3011: 2.5, 2002: 4.2},
        )

    def test_kitchen_settings(self):
        values, notes = sm.kitchen_settings(self.make(), 601, MEAL_OPTIONS[601], PRODUCT_OPTIONS[601])
        self.assertEqual(notes, [])
        meals = [(values[f'IslandRestaurant.IslandRestaurant.Meal{i}'],
                  values[f'IslandRestaurant.IslandRestaurant.MealNumber{i}']) for i in range(1, 9)]
        # 出售菜品在前（容量 6 + 日缓冲），中间品在后，空槽为 None/0
        self.assertEqual(meals[:3], [('tofu_meat', 15), ('tofu_combo', 9), ('tofu', 12)])
        self.assertEqual(meals[3:], [('None', 0)] * 5)
        self.assertEqual(values['IslandRestaurant.IslandRestaurantNextTask.AwayCook'], 'tofu')
        self.assertEqual(
            [values[f'IslandBusiness.IslandBusinessShop1.Product{i}'] for i in range(1, 6)],
            ['tofu_meat', 'tofu_combo', 'None', 'None', 'None'])

    def test_crop_settings(self):
        values, notes = sm.crop_settings(self.make())
        farm = parse_crop_targets(values['IslandFarm.IslandFarm.CropTargets'])
        # 目标只含一天消耗，闲时累积量只作提示，避免攒 PT 的作物挤占真正需要的作物
        self.assertEqual(farm['rice'], 20)
        self.assertEqual(farm['wheat'], 0)
        self.assertEqual(set(farm), set(sm.CROP_ITEM_IDS['farm']))
        self.assertEqual(len(notes), 1)
        self.assertIn('rice 4/day', notes[0])


class ProductionLineTest(unittest.TestCase):
    """矿山/林场/渔场/牧场/制造业的换算。"""

    def make(self):
        tech = {tech_id: True for tech_id in DIC_ISLAND_TECHNOLOGY}
        calculator = ProductionPlanCalculator(tech)
        calculator.production_plan = {
            101013: 3,      # 鸡舍 3 批
            701010: 10,     # 铁钉 10 批，工作量 10 * workload
            401005: 2,      # 铁矿
        }
        calculator.product_daily_buffer_items = {2703: 12, 5107: 3}
        calculator.idle_accumulating_items_per_day = {2705: 40}
        return calculator

    def test_thresholds(self):
        values, notes = sm.threshold_settings(self.make())
        self.assertEqual(values['IslandMineForest.IslandMine.MinIron'], 12)
        self.assertEqual(values['IslandMineForest.IslandMine.MinSilver'], 0)
        self.assertEqual(values['IslandRancher.IslandFishery.MinYellowfinTuna'], 3)
        self.assertEqual(values['IslandMineForest.IslandForest.MinElegant'], 0)
        self.assertEqual(len(notes), 1)
        self.assertIn('Silver Ore 40/day', notes[0])

    def test_targets_become_stock_thresholds(self):
        # 目标按剩余量进库存下限；按期限摊薄会让「50 个 / 87 天」变成 1 个
        calculator = self.make()
        calculator.product_daily_buffer_items[2701] = 2
        calculator.idle_accumulating_items_per_day = {}
        floors = sm.target_floor({2701: [{'count': 50, 'period': 87.0}]})
        self.assertEqual(floors, {2701: 50})
        stock = sm.stock_targets(calculator, floors)
        self.assertEqual(stock[2701], 52)  # 50 + 日缓冲 2（两者用途不同，不重复扣减）
        values, _ = sm.threshold_settings(calculator, stock)
        self.assertEqual(values['IslandMineForest.IslandMine.MinCopper'], 52)
        # 没有目标的物品不受影响，仍只写日缓冲
        self.assertEqual(values['IslandMineForest.IslandMine.MinIron'], 12)

    def test_target_floor_counts_every_entry(self):
        # 同一物品多条目标（季节任务 + 额外目标）应累加，三种输入形状都要能读
        floors = sm.target_floor({
            2701: [{'count': 30, 'period': 87.0}, 20],
            2703: {'total_need_count': 15},
            2702: 0,
        })
        self.assertEqual(floors, {2701: 50, 2703: 15})

    def test_ranch(self):
        calculator = self.make()
        values = sm.ranch_settings(calculator)
        level = calculator.ranch_level[9031]
        # 禽肉为副产物：每批 4 * (1 + 等级)，每 3 批摊一次
        expected = 4 * (1 + level) / 3 * 3
        self.assertEqual(values['IslandRancher.IslandRancher.MinChicken'], max(int(-(-expected // 1)), 1))
        self.assertEqual(values['IslandRancher.IslandRancher.MinPork'], 0)
        self.assertFalse(values['IslandRancher.IslandRancher.Milk'])
        self.assertFalse(values['IslandRancher.IslandRancher.Wool'])

    def test_manufacture_positions(self):
        values = sm.manufacture_settings(self.make())
        workload = DIC_ISLAND_RECIPE[701010]['workload'] * 10
        self.assertEqual(values['IslandManufacture.Industrial.Positions'],
                         min(-(-workload // sm.DAILY_WORKLOAD), 2))
        self.assertEqual(values['IslandManufacture.WoodProcessing.Positions'], 0)
        # 生产顺序：计划生产的产品按工作量降序，没有计划的产线为空（沿用固定规则）
        self.assertEqual(values['IslandManufacture.Industrial.Products'], 'iron_nail')
        self.assertEqual(values['IslandManufacture.WoodProcessing.Products'], '')

    def test_manufacture_product_order_by_workload(self):
        calculator = self.make()
        recipes = {sm.recipe_product(r): r for r, g in calculator.recipe_group.items() if g == 'manufacturing_lumber'}
        calculator.production_plan = {recipes[3048]: 1, recipes[3049]: 3}   # 纸张 1 批，记事本 3 批
        values = sm.manufacture_settings(calculator)
        expected = sorted(['paper', 'notebook'], key=lambda name: -DIC_ISLAND_RECIPE[
            recipes[sm.MANUFACTURE_PRODUCTS['manufacturing_lumber']['products'][name]]]['workload']
            * (3 if name == 'notebook' else 1))
        self.assertEqual(values['IslandManufacture.WoodProcessing.Products'], ' > '.join(expected))
        # 每个产线的产品名都是 AzurPilot 识别的产品
        for data in sm.MANUFACTURE_PRODUCTS.values():
            products = values[f'{data["line"]}.Products']
            for name in filter(None, products.split(' > ')):
                self.assertIn(name, data['products'])

    def test_auto_position_settings(self):
        tech = {tech_id: True for tech_id in DIC_ISLAND_TECHNOLOGY}
        tech[310103] = tech[310104] = False     # 农田第 3、4 个岗位未解锁
        values = sm.auto_position_settings(ProductionPlanCalculator(tech))
        self.assertEqual(values['IslandFarm.IslandFarm.Positions'], 2)
        self.assertEqual(values['IslandRancher.IslandFishery.Positions'], 3)
        self.assertEqual(values['IslandRestaurant.IslandRestaurant.PostNumber'], 2)
        # 选项范围内：岗位数配置的最大值不超过选项
        for path, value in values.items():
            task, group, key = path.split('.')
            self.assertIn(value, ARGUMENT[group][key]['option'], path)
        # 一个岗位都没解锁的区域不写入
        none = sm.auto_position_settings(ProductionPlanCalculator({}))
        self.assertNotIn('IslandMineForest.IslandMine.Positions', none)


class SolveTest(unittest.TestCase):
    def setUp(self):
        self.previous_server = server.server
        server.server = 'en'

    def tearDown(self):
        server.server = self.previous_server

    def test_cargo_demand_becomes_stock_target(self):
        # 货运给 settings 的是需求量：库存目标 = 需求量 + 计划日消耗，而不是缺口 + 缓冲
        calculator, _ = solve({tech_id: True for tech_id in DIC_ISLAND_TECHNOLOGY})
        self.assertTrue(calculator.lp_success, calculator.lp_message)
        buffer = calculator.product_daily_buffer_items.get(2011, 0)  # 草莓
        values, _ = sm.build_settings(calculator, MEAL_OPTIONS, PRODUCT_OPTIONS,
                                      {2011: [{'count': 35, 'period': 1.0}]})
        nursery = parse_crop_targets(values['IslandFarm.IslandNursery.CropTargets'])
        self.assertEqual(nursery['strawberry'], 35 + buffer)

    def test_full_technology_plan_writes_valid_settings(self):
        calculator, excluded = solve({tech_id: True for tech_id in DIC_ISLAND_TECHNOLOGY})
        self.assertTrue(calculator.lp_success, calculator.lp_message)
        self.assertGreaterEqual(calculator.daily_profit, 50000 - 1e-6)
        # 烧烤店后厨没有柠檬虾选项，求解前排除
        self.assertIn('Lemon Shrimp', excluded)

        values, _ = sm.build_settings(calculator, MEAL_OPTIONS, PRODUCT_OPTIONS)
        for path, value in values.items():
            task, group, key = path.split('.')
            self.assertIn(key, ARGS[task][group], path)
            definition = ARGUMENT[group][key]
            if isinstance(definition, dict) and 'option' in definition:
                self.assertIn(value, definition['option'], path)
            elif key.startswith(('MealNumber', 'Min')):
                self.assertIsInstance(value, int, path)
                self.assertGreaterEqual(value, 0, path)
        for rid, kitchen in sm.KITCHENS.items():
            products = [values[f'IslandBusiness.{kitchen["business"]}.Product{i}'] for i in range(1, 6)]
            sold = [name for name in products if name != 'None']
            self.assertEqual(len(sold), len(set(sold)))
            # 只卖规划出售的菜品，且都在 AzurPilot 商区选项里
            for name in sold:
                self.assertIn(name, PRODUCT_OPTIONS[rid])

    def test_starting_island_still_solves(self):
        calculator, _ = solve({tech_id: False for tech_id in DIC_ISLAND_TECHNOLOGY}, grades='bronze', profit=0)
        self.assertTrue(calculator.lp_success, calculator.lp_message)
        values, _ = sm.build_settings(calculator, MEAL_OPTIONS, PRODUCT_OPTIONS)
        self.assertEqual(len([path for path in values if path.endswith('CropTargets')]), 3)

    def test_closed_restaurant_sells_nothing(self):
        calculator, _ = solve({tech_id: True for tech_id in DIC_ISLAND_TECHNOLOGY}, open_ids=set(), profit=-1e9)
        self.assertTrue(calculator.lp_success, calculator.lp_message)
        self.assertEqual(calculator.sell_plan, {})


class FakeConfig:
    """只实现规划器用到的配置接口：属性读取、cross_get、批量写入。"""

    def __init__(self, technology_status, **overrides):
        self.data = {}
        for task, groups in ARGS.items():
            for group, args in groups.items():
                for key, arg in args.items():
                    if isinstance(arg, dict) and 'value' in arg:
                        self.data.setdefault(task, {}).setdefault(group, {})[key] = arg['value']
                        setattr(self, f'{group}_{key}', arg['value'])
        self.data['IslandProductionPlanner']['Storage']['Storage'] = {'IslandTechnologyStatus': technology_status}
        for key, value in overrides.items():
            setattr(self, key, value)
        self.written = {}

    def cross_get(self, keys, default=None):
        node = self.data
        for key in keys.split('.'):
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node

    def cross_set(self, keys, value):
        self.written[keys] = value

    def cross_set_many(self, values):
        self.written.update(values)

    def multi_set(self):
        from contextlib import nullcontext
        return nullcontext()


class PlannerTaskTest(unittest.TestCase):
    # Add by MHY, 固定规划季节与「本季剩余天数」：上游按服务器时间取季节，赛季快结束时
    # 同样的目标摊到不足一天的产能里会不可行（2026-11-04 只剩 0.7 天时，
    # Apple Pie 84 需要 127/天 > 48h 产能），测试会随日期飘红
    SEASON_ID = 5
    SEASON_REMAINING_DAYS = 20

    def setUp(self):
        self.previous_server = server.server
        server.server = 'en'

    def tearDown(self):
        server.server = self.previous_server

    def run_planner(self, cargo_scan=None, config_data=None, season_id=None,
                    season_scan=None, real_season=False, now=None, **overrides):
        from unittest.mock import patch
        from module.island_planner.planner import IslandProductionPlanner
        technology = {str(tech_id): True for tech_id in DIC_ISLAND_TECHNOLOGY}
        with patch.object(IslandProductionPlanner, '__init__', lambda self: None):
            planner = IslandProductionPlanner()
        overrides.setdefault('IslandProductionPlanner_ScanSeasonTasks', False)
        overrides.setdefault('IslandProductionPlanner_ScanCargoOrders', False)
        planner.config = FakeConfig(technology, IslandProductionPlanner_RescanTechnology=False, **overrides)
        for path, value in (config_data or {}).items():
            task, group, key = path.split('.')
            planner.config.data[task][group][key] = value
        planner.get_technology_status = lambda: self.fail('saved technology must not trigger a scan')
        planner.scan_season_task_targets = season_scan or (lambda: {3009: 30})
        # 扫描返回 (缺口, 需求量)
        planner.scan_cargo_targets = cargo_scan or (lambda: ({2011: 33}, {2011: 35}))
        if real_season:
            # Add by MHY, 走真实的 resolve_season，只固定服务器时间：验证 auto 与显式旧季的选择
            with patch('module.island_planner.planner._get_server_time',
                       return_value=now or datetime(2026, 11, 8, 12)):
                return planner, planner.run()
        season_id = self.SEASON_ID if season_id is None else season_id
        with patch('module.island_planner.planner.resolve_season',
                   return_value=(season_id, DIC_ISLAND_SEASON[season_id]['activity'],
                                 self.SEASON_REMAINING_DAYS)):
            return planner, planner.run()

    def test_preview_does_not_write(self):
        planner, result = self.run_planner()
        self.assertTrue(result)
        self.assertEqual(planner.config.written, {})

    def test_apply_writes_settings(self):
        planner, result = self.run_planner(IslandProductionPlanner_ApplySettings=True,
                                           IslandProductionPlanner_RestaurantGrade='gold')
        self.assertTrue(result)
        written = planner.config.written
        self.assertIn('IslandFarm.IslandFarm.CropTargets', written)
        self.assertIn('IslandBusiness.IslandBusinessShop1.Product1', written)
        self.assertTrue(all(path.split('.')[2] in ARGS[path.split('.')[0]][path.split('.')[1]] for path in written))

    def test_infeasible_plan_keeps_settings(self):
        planner, result = self.run_planner(IslandProductionPlanner_ApplySettings=True,
                                           IslandProductionPlanner_DailyProfitLowerLimit=10 ** 9)
        self.assertFalse(result)
        self.assertEqual(planner.config.written, {})


    def test_targets_reach_kitchen_settings(self):
        # 苹果派不在默认方案里；加入目标后啾啾简餐后厨应为其开工
        planner, result = self.run_planner(IslandProductionPlanner_ApplySettings=True,
                                           IslandProductionPlanner_ExtraTargets='Apple Pie: 84')
        self.assertTrue(result)
        meals = [planner.config.written.get(f'IslandJuuEatery.IslandJuuEatery.Meal{i}') for i in range(1, 9)]
        self.assertIn('apple_pie', meals)

    def test_targets_become_stock_targets(self):
        # 目标数量要进后厨的库存目标；按每日速率摊薄会写成 1，永远做不完
        planner, result = self.run_planner(IslandProductionPlanner_ApplySettings=True,
                                           IslandProductionPlanner_ExtraTargets='Apple Pie: 84')
        self.assertTrue(result)
        numbers = {
            planner.config.written.get(f'IslandJuuEatery.IslandJuuEatery.Meal{i}'):
                planner.config.written.get(f'IslandJuuEatery.IslandJuuEatery.MealNumber{i}')
            for i in range(1, 9)
        }
        self.assertGreaterEqual(numbers.get('apple_pie', 0), 84)

    def test_scan_writes_season_targets(self):
        planner, result = self.run_planner(IslandProductionPlanner_ScanSeasonTasks=True)
        self.assertTrue(result)
        self.assertEqual(
            planner.config.written['IslandProductionPlanner.IslandProductionPlanner.SeasonTaskTargets'].strip(),
            'Apple Pie (3009): 30')


    def test_scan_writes_cargo_targets(self):
        planner, result = self.run_planner(IslandProductionPlanner_ScanCargoOrders=True)
        self.assertTrue(result)
        # CargoTargets 存需求量（缺口 + 扫描时的库存），库存目标才不会被重复扣减
        self.assertEqual(
            planner.config.written['IslandProductionPlanner.IslandProductionPlanner.CargoTargets'].strip(),
            'Strawberries (2011): 35')

    def test_cargo_targets_use_demand_not_shortfall(self):
        # 委托需求 35、库存 2 → 缺口 33；写入的库存目标必须是需求量 35，
        # 拿缺口当目标会让任务端「仓库 < 目标」把库存再扣一次，永远补不满
        planner, result = self.run_planner(
            IslandProductionPlanner_ApplySettings=True,
            IslandProductionPlanner_ScanCargoOrders=True,
            cargo_scan=lambda: ({2011: 33}, {2011: 35}))
        self.assertTrue(result)
        # 草莓属于苗圃
        nursery = parse_crop_targets(planner.config.written['IslandFarm.IslandNursery.CropTargets'])
        self.assertGreaterEqual(nursery['strawberry'], 35)

    def test_cargo_fully_in_stock_keeps_target(self):
        # 委托已被库存完全满足（缺口为空）时，CargoTargets 仍要记录需求量，不能被清空
        planner, result = self.run_planner(
            IslandProductionPlanner_ScanCargoOrders=True,
            cargo_scan=lambda: ({}, {2011: 35}))
        self.assertTrue(result)
        self.assertEqual(
            planner.config.written['IslandProductionPlanner.IslandProductionPlanner.CargoTargets'].strip(),
            'Strawberries (2011): 35')

    def scan_cargo(self, reads):
        from unittest.mock import Mock, patch
        from module.island_planner.planner import IslandProductionPlanner
        with patch.object(IslandProductionPlanner, '__init__', lambda self: None):
            planner = IslandProductionPlanner()
        planner.device = Mock()
        for name in ('ui_ensure', 'ui_goto', 'island_transport_enter', 'appear_then_click', 'ui_additional'):
            setattr(planner, name, Mock(return_value=False))
        planner.ui_page_appear = Mock(return_value=True)
        planner.loop = lambda **kwargs: iter(range(len(reads)))
        with patch('module.island_planner.planner.read_cargo_slots', Mock(side_effect=reads)):
            return planner.scan_cargo_targets()

    def test_cargo_scan_waits_for_stable_read(self):
        # 第一张截图已提交标记还没显示（completed 全为 0），不能据此清空目标
        loading = [{'completed': 0, 'items': [(2011, 2, 35)], 'unreadable': 0}]
        ready = [{'completed': 2, 'items': [(2011, 2, 35)], 'unreadable': 0}]
        # 返回值是 (缺口, 需求量)：库存 2、需求 35 → 缺口 33、目标 35
        self.assertEqual(self.scan_cargo([loading, ready, ready]), ({2011: 33}, {2011: 35}))
        self.assertEqual(self.scan_cargo([loading, ready]), (None, None))

    def test_incomplete_cargo_scan_keeps_saved_targets(self):
        planner, result = self.run_planner(cargo_scan=lambda: (None, None), IslandProductionPlanner_ScanCargoOrders=True)
        self.assertTrue(result)
        self.assertNotIn('IslandProductionPlanner.IslandProductionPlanner.CargoTargets', planner.config.written)

    def test_cargo_fallback_warns_to_lp_overplan(self):
        # 扫描失败时沿用保存的需求量：库存目标照写，但要提示 LP 按整单需求规划可能偏大
        from unittest.mock import patch
        with patch('module.island_planner.planner.logger') as logger:
            self.run_planner(cargo_scan=lambda: (None, None),
                             IslandProductionPlanner_ScanCargoOrders=True,
                             IslandProductionPlanner_CargoTargets='Strawberries (2011): 35')
        messages = [str(call.args[0]) for call in logger.warning.call_args_list if call.args]
        self.assertTrue(any('沿用上次保存的需求量' in text for text in messages), messages)

    def test_apply_writes_default_products(self):
        # 矿山配置 4 个岗位，计划用剩的岗位写入默认产品（银矿）
        planner, result = self.run_planner(IslandProductionPlanner_ApplySettings=True,
                                           config_data={'IslandMineForest.IslandMine.Positions': 4})
        self.assertTrue(result)
        written = planner.config.written
        self.assertIn('IslandMineForest.IslandMine.MineSilver', written)
        self.assertIn(written.get('IslandFarm.IslandFarm.DefaultCrop', 'wheat'), sm.CROP_ITEM_IDS['farm'])

    def test_winter_season_plans_with_winter_chain(self):
        # Modify by MHY, 第 5 季数据已完整（活动 990027-990030、槽位 activity_formula
        # 9900027-9900030、采集原料 4043-4046、实际 pt_num），冬季不再阻断规划：
        # 冬季菜品目标要经冬季配方（9900027）进后厨
        planner, result = self.run_planner(
            IslandProductionPlanner_ApplySettings=True,
            IslandProductionPlanner_ExtraTargets='Shiitake Mushroom Chicken Stew: 20')
        self.assertTrue(result)
        meals = [planner.config.written.get(f'IslandRestaurant.IslandRestaurant.Meal{i}')
                 for i in range(1, 9)]
        self.assertIn('shiitake_chicken_soup', meals)

    def test_season_data_gaps_follow_data(self):
        # Add by MHY, 缺口判断只看 data.py：第 4 季的 8 个配方没有槽位、菜品没有菜单，
        # 第 5 季槽位与菜单齐全，没有季节时不做限制
        from module.island_planner.planner import season_data_gaps
        missing_slots, missing_menu = season_data_gaps(DIC_ISLAND_SEASON[4]['activity'])
        self.assertEqual(len(missing_slots), 8)
        self.assertTrue(missing_menu)
        self.assertEqual(season_data_gaps(DIC_ISLAND_SEASON[5]['activity']), ([], []))
        self.assertEqual(season_data_gaps(None), ([], []))

    def test_explicit_old_season_skips_before_scan_and_write(self):
        # Add by MHY, 指定第 4 季（旧季）时不能照常求解：旧季只有配方、没有槽位与菜单，
        # 必须在扫描科技/目标与写配置之前退出，手填的赛季配置保持原样
        planner, result = self.run_planner(
            real_season=True, now=datetime(2026, 11, 8, 12),
            IslandProductionPlanner_Season='season_4',
            IslandProductionPlanner_ApplySettings=True,
            IslandProductionPlanner_ScanSeasonTasks=True,
            IslandProductionPlanner_ScanCargoOrders=True,
            season_scan=lambda: self.fail('旧季数据缺口时不应扫描季节任务'),
            cargo_scan=lambda: self.fail('旧季数据缺口时不应扫描货运'))
        self.assertFalse(result)
        self.assertEqual(planner.config.written, {})

    def test_old_season_skip_logs_reason(self):
        # Add by MHY, 跳过时必须有明确中文日志，说明不扫描、不写配置，不能静默跳过
        from unittest.mock import patch
        with patch('module.island_planner.planner.logger') as logger:
            planner, result = self.run_planner(
                real_season=True, now=datetime(2026, 11, 8, 12),
                IslandProductionPlanner_Season='season_4')
        messages = [str(call.args[0]) for call in logger.warning.call_args_list if call.args]
        self.assertFalse(result)
        self.assertTrue(any('不扫描' in text and '不写入' in text for text in messages), messages)

    def test_tw_auto_old_season_skips_before_scan_and_write(self):
        # Add by MHY, 台服第 5 季日期为空，auto 在 2026-11-08 仍选中第 4 季；
        # 该季没有季节槽位/菜单数据，同样要在扫描与写入之前跳过
        server.server = 'tw'
        planner, result = self.run_planner(
            real_season=True, now=datetime(2026, 11, 8, 12),
            IslandProductionPlanner_ApplySettings=True,
            IslandProductionPlanner_ScanSeasonTasks=True,
            IslandProductionPlanner_ScanCargoOrders=True,
            season_scan=lambda: self.fail('台服旧季数据缺口时不应扫描季节任务'),
            cargo_scan=lambda: self.fail('台服旧季数据缺口时不应扫描货运'))
        self.assertFalse(result)
        self.assertEqual(planner.config.written, {})

    def test_no_active_season_still_plans(self):
        # Add by MHY, 台服 2026-11-19 后没有进行中的季节（第 5 季 tw 日期为空）：
        # 没有季节配方可查，规划器照常求解，不受旧季数据缺口保护影响
        server.server = 'tw'
        planner, result = self.run_planner(
            real_season=True, now=datetime(2026, 12, 1, 12),
            IslandProductionPlanner_ApplySettings=True)
        self.assertTrue(result)
        self.assertIn('IslandFarm.IslandFarm.CropTargets', planner.config.written)


class PriorityTest(unittest.TestCase):
    """目标 → 季节 PT → 岛币：第二次求解不降低 PT，岛币不少于第一次。"""

    def setUp(self):
        self.previous_server = server.server
        server.server = 'en'

    def tearDown(self):
        server.server = self.previous_server

    def test_coins_after_pt(self):
        from module.island_planner.priorities import solve_with_priorities
        tech = {tech_id: True for tech_id in DIC_ISLAND_TECHNOLOGY}
        first, _ = solve(tech, profit=0)
        calculator = ProductionPlanCalculator(
            tech, activity_list=get_current_activity_list(NOW),
            restaurant_settings=sm.restaurant_settings({rid: 'gold' for rid in sm.KITCHENS}, {}),
            daily_profit_lower_limit=0)
        sm.restrict_calculator(calculator, MEAL_OPTIONS, PRODUCT_OPTIONS)
        self.assertTrue(solve_with_priorities(calculator, current_time=NOW))
        self.assertGreaterEqual(calculator.total_pt, first.total_pt * (1 - 1e-4))
        self.assertGreaterEqual(calculator.daily_profit, first.daily_profit - 1e-6)

    def test_default_products(self):
        calculator, _ = solve({tech_id: True for tech_id in DIC_ISLAND_TECHNOLOGY})
        values, _ = sm.default_product_settings(calculator)
        for path, value in values.items():
            task, group, key = path.split('.')
            self.assertIn(value, ARGUMENT[group][key]['option'], path)
        # 有闲时作物时写入默认作物，岗位数不超过已解锁岗位
        farm = values['IslandFarm.IslandFarm.PlantPotatoes']
        unlocked = sum(calculator.slot_available.get(slot, False) for slot in calculator.GROUP_TO_SLOTS['field'])
        self.assertLessEqual(farm, unlocked)

    def test_position_config_limits_posts(self):
        # 农田只配置 1 个岗位时，规划容量与默认作物岗位数都不超过 1
        calculator, _ = solve({tech_id: True for tech_id in DIC_ISLAND_TECHNOLOGY}, slot_limit={'field': 1})
        unlocked = sum(calculator.slot_available.get(slot, False) for slot in calculator.GROUP_TO_SLOTS['field'])
        self.assertEqual(unlocked, 1)
        values, _ = sm.default_product_settings(calculator)
        self.assertLessEqual(values['IslandFarm.IslandFarm.PlantPotatoes'], 1)

    def test_position_limits_read_config(self):
        config = {'IslandFarm.IslandFarm.Positions': 3, 'IslandMineForest.IslandMine.Positions': 'bad'}
        self.assertEqual(sm.position_limits(config.get), {'field': 3})

    def test_idle_posts_counts_workload(self):
        calculator, _ = solve({tech_id: True for tech_id in DIC_ISLAND_TECHNOLOGY})
        calculator.idle_accumulating_items_per_day = {2705: 4 * 10}
        calculator.place_efficiency_bonus[401] = 0
        recipe = next(r for r, g in calculator.recipe_group.items()
                      if g == 'mine' and 2705 in sm.DIC_ISLAND_RECIPE[r]['commission_product'])
        per_batch = sm.DIC_ISLAND_RECIPE[recipe]['commission_product'][2705]
        expected = -(-(40 / per_batch * sm.DIC_ISLAND_RECIPE[recipe]['workload']) // sm.DAILY_WORKLOAD)
        self.assertEqual(sm.idle_posts(calculator, 'mine', 2705), expected)


class PlannerOptionTest(unittest.TestCase):
    """季节选择、优先级、已解锁的鱼与填满空余岗位。"""

    def setUp(self):
        self.previous_server = server.server
        server.server = 'en'

    def tearDown(self):
        server.server = self.previous_server

    def test_resolve_season(self):
        from module.island_planner.data import DIC_ISLAND_SEASON
        from module.island_planner.planner import resolve_season
        winter_day = datetime(2026, 11, 6, 12)
        season_id, activity, remaining = resolve_season('auto', winter_day)
        self.assertEqual(season_id, 5)
        self.assertEqual(activity, DIC_ISLAND_SEASON[5]['activity'])
        self.assertAlmostEqual(remaining, (datetime(2027, 2, 1, 23, 59, 59) - winter_day).total_seconds() / 86400)
        # 指定不在进行中的季节：用该季活动，期限为整季天数
        season_id, activity, remaining = resolve_season('season_4', winter_day)
        self.assertEqual((season_id, activity), (4, DIC_ISLAND_SEASON[4]['activity']))
        self.assertAlmostEqual(
            remaining,
            (datetime(2026, 11, 4, 23, 59, 59) - datetime(2026, 8, 6)).total_seconds() / 86400)
        # 未知季节按当前时间选择；台服第 5 季还没有日期，11 月 6 日仍在第 4 季
        self.assertEqual(resolve_season('season_99', winter_day)[0], 5)
        server.server = 'tw'
        self.assertEqual(resolve_season('auto', winter_day)[0], 4)
        self.assertEqual(resolve_season('season_5', winter_day), (5, DIC_ISLAND_SEASON[5]['activity'], None))

    def winter_calculator(self, tech=None, unlocked_fish=None, profit=0):
        from module.island_planner.data import DIC_ISLAND_SEASON
        calculator = ProductionPlanCalculator(
            tech or {tech_id: True for tech_id in DIC_ISLAND_TECHNOLOGY},
            activity_list=DIC_ISLAND_SEASON[5]['activity'],
            restaurant_settings=sm.restaurant_settings({rid: 'gold' for rid in sm.KITCHENS}, {}),
            daily_profit_lower_limit=profit)
        sm.restrict_calculator(calculator, MEAL_OPTIONS, PRODUCT_OPTIONS, unlocked_fish=unlocked_fish)
        return calculator

    def test_unlocked_fish_limits_fishery(self):
        calculator = self.winter_calculator(unlocked_fish=['shell', 'shrimp'])
        fishery = sm.producible_items(calculator, 'fishery')
        self.assertEqual(set(fishery), {5001, 5005})
        # 未勾选全部时不限制（None），黄鳍金枪鱼可用
        self.assertIn(5107, sm.producible_items(self.winter_calculator(), 'fishery'))

    def test_fill_spare_posts_uses_unlocked_products(self):
        from module.island_planner.priorities import solve_with_priorities
        calculator = self.winter_calculator(unlocked_fish=['shell', 'shrimp', 'crayfish'])
        self.assertTrue(solve_with_priorities(calculator, current_time=datetime(2026, 11, 6, 12)))
        values, _ = sm.default_product_settings(calculator, fill_spare_posts=True)
        for group, data in sm.DEFAULT_PRODUCTS.items():
            count_path, limit = data['count']
            unlocked = sum(calculator.slot_available.get(slot, False) for slot in calculator.GROUP_TO_SLOTS[group])
            # 全科技解锁时每个区域都有可生产产品：写满已解锁岗位，默认产品可生产且是合法选项
            self.assertEqual(values[count_path], min(limit, unlocked), count_path)
            product = values[data['product_path']]
            self.assertIn(data['products'][product], sm.producible_items(calculator, group), data['product_path'])
            task, group_name, key = data['product_path'].split('.')
            self.assertIn(product, ARGUMENT[group_name][key]['option'])
        self.assertIn(values['IslandRancher.IslandFishery.DefaultFish'], ('shell', 'shrimp', 'crayfish'))

    def test_fallback_product_skips_locked_items(self):
        calculator = self.winter_calculator()
        calculator.idle_accumulating_items_per_day = {}
        candidates = sm.DEFAULT_PRODUCTS['mine']['products']
        self.assertEqual(sm.fallback_product(calculator, 'mine', candidates), 'Silver')
        for recipe_id, group in calculator.recipe_group.items():
            if group == 'mine' and 2705 in DIC_ISLAND_RECIPE[recipe_id]['commission_product']:
                calculator.recipe_available[recipe_id] = False
        self.assertNotEqual(sm.fallback_product(calculator, 'mine', candidates), 'Silver')
        # 不填满时没有闲时产品就不写默认产品，岗位数为 0
        values, _ = sm.default_product_settings(calculator, fill_spare_posts=False)
        self.assertEqual(values['IslandMineForest.IslandMine.MineSilver'], 0)
        self.assertNotIn('IslandMineForest.IslandMine.DefaultOre', values)

    def test_coins_priority_earns_at_least_pt_priority(self):
        from module.island_planner.priorities import solve_with_priorities
        now = datetime(2026, 11, 6, 12)
        by_pt = self.winter_calculator()
        self.assertTrue(solve_with_priorities(by_pt, current_time=now, priority='pt'))
        by_coins = self.winter_calculator()
        self.assertTrue(solve_with_priorities(by_coins, current_time=now, priority='coins'))
        self.assertGreaterEqual(by_coins.daily_profit, by_pt.daily_profit - 1e-6)
        self.assertGreaterEqual(by_pt.total_pt, by_coins.total_pt - 1e-6)


class CargoReaderTest(unittest.TestCase):
    """EN 货运页截图：栏位 1 淡水鱼肉 6/16（另 2 格已提交），栏位 2 淡水鱼肉 6/26（未提交），
    栏位 3 草莓 2/35（另 2 格已提交）。"""

    def setUp(self):
        self.previous_server = server.server
        server.server = 'en'

    def tearDown(self):
        server.server = self.previous_server

    def test_partial_orders(self):
        from module.base.utils import load_image
        from module.island_planner.cargo import partial_order_demands, partial_order_targets, read_cargo_slots
        slots = read_cargo_slots(load_image(str(ROOT / 'tests/fixtures/island_planner/en_cargo_partial.png')))
        self.assertEqual([slot['completed'] for slot in slots], [2, 0, 2])
        self.assertEqual([slot['items'] for slot in slots],
                         [[(2521, 6, 16)], [(2521, 6, 26)], [(2011, 2, 35)]])
        # 未提交过货物的栏位 2 可以更换，不计入
        # 缺口 = 需求 - 库存（喂 LP）；需求量 = 需求总量（写入 CargoTargets 当库存目标）
        self.assertEqual(partial_order_demands(slots), {2011: 33, 2521: 10})
        self.assertEqual(partial_order_targets(slots), {2011: 35, 2521: 16})

    def test_shared_stock_counts_once(self):
        from module.island_planner.cargo import partial_order_demands, partial_order_targets
        slots = [{'completed': 1, 'items': [(2011, 5, 10)]}, {'completed': 2, 'items': [(2011, 5, 20)]}]
        # 同一物品多个委托：需求相加，库存只扣一次
        self.assertEqual(partial_order_demands(slots), {2011: 25})
        self.assertEqual(partial_order_targets(slots), {2011: 30})

    def test_item_without_number_is_unreadable(self):
        # 数字还没渲染出来的货物格（有图标、无数字）不能被当作空格跳过
        from module.base.utils import load_image
        from module.island_planner.cargo import (
            card_completed, counter_area, partial_orders_fully_read, read_cargo_slots)
        image = load_image(str(ROOT / 'tests/fixtures/island_planner/en_cargo_partial.png')).copy()
        card = next(card for card in range(3) if not card_completed(image, card, 0))
        x1, y1, x2, y2 = counter_area(card, 0)
        image[y1:y2, x1:x2] = image[y1, x1]
        slots = read_cargo_slots(image)
        self.assertEqual(slots[0]['items'], [])
        self.assertEqual(slots[0]['unreadable'], 1)
        self.assertFalse(partial_orders_fully_read(slots))

    def test_unreadable_partial_order_is_incomplete(self):
        from module.island_planner.cargo import partial_orders_fully_read
        self.assertTrue(partial_orders_fully_read([{'completed': 1, 'items': [(2011, 5, 10)], 'unreadable': 0},
                                                   {'completed': 0, 'items': [], 'unreadable': 2}]))
        self.assertFalse(partial_orders_fully_read([{'completed': 1, 'items': [], 'unreadable': 1}]))

    def test_with_period(self):
        from module.island_planner.planner import with_period
        self.assertEqual(with_period({2011: [33, {'count': 5, 'period': 3}]}, 2),
                         {2011: [{'count': 33, 'period': 2.0}, {'count': 5, 'period': 3}]})
        self.assertEqual(with_period({2011: [1]}, 'bad'), {2011: [{'count': 1, 'period': 1.0}]})


class TargetParsingTest(unittest.TestCase):
    def setUp(self):
        self.previous_server = server.server
        server.server = 'en'

    def tearDown(self):
        server.server = self.previous_server

    def test_parse_and_merge(self):
        from module.island_planner.planner import merge_targets, parse_targets
        season = parse_targets('Apple Pie: 30\nCorn: 100', 'SeasonTaskTargets')
        extra = parse_targets('Apple Pie: {count: 10, period: 2}\nNot An Item: 5\n3011: 4', 'ExtraTargets')
        self.assertEqual(season, {3009: [30], 2001: [100]})
        self.assertEqual(extra, {3009: [{'count': 10, 'period': 2}], 3011: [4]})
        merged = merge_targets(season, extra)
        from module.island_planner.utils import normalize_item_needs
        needs = normalize_item_needs(merged, default_period=8)
        # 30 个 8 天 + 10 个 2 天：前 2 天至少 10 个，8 天共 40 个
        self.assertEqual(needs[3009]['total_need_count'], 40)
        self.assertAlmostEqual(needs[3009]['rate_per_day'], 5.0)
        self.assertEqual(parse_targets('[1, 2', 'ExtraTargets'), {})

    def test_season_task_matching(self):
        from module.island_planner.data import DIC_ISLAND_TASK
        from module.island_planner.season_tasks import match_task_name, task_item_targets
        item_tasks = [tid for tid, task in DIC_ISLAND_TASK.items()
                      if task['target'] and next(iter(task['target'])) in DIC_ISLAND_ITEM]
        self.assertTrue(item_tasks)
        task_id = item_tasks[0]
        name = DIC_ISLAND_TASK[task_id]['name']['en']
        # OCR 少一个字母也能纠正到同一任务
        self.assertEqual(match_task_name(name[:-1], item_tasks[:20]), task_id)
        self.assertIsNone(match_task_name('', item_tasks))
        targets = task_item_targets([task_id, task_id, 10001000])
        item_id, count = next(iter(DIC_ISLAND_TASK[task_id]['target'].items()))
        self.assertEqual(targets, {item_id: count * 2})


class EfficiencyTest(unittest.TestCase):
    def test_efficiency_rate(self):
        from module.island_planner.planner import efficiency_rate
        # 配置为整数百分比；兼容早期的小数值与 WebUI 拆坏的字符串
        self.assertEqual(efficiency_rate(0), 0)
        self.assertAlmostEqual(efficiency_rate(4), 0.04)
        self.assertAlmostEqual(efficiency_rate(12), 0.12)
        self.assertAlmostEqual(efficiency_rate(0.04), 0.04)
        self.assertAlmostEqual(efficiency_rate('04'), 0.04)
        self.assertEqual(efficiency_rate('bad'), 0)


class SeasonScanGuardTest(unittest.TestCase):
    """季节任务扫描：读错的任务名不硬配，识别不到任务卡片时保留原目标。"""

    def setUp(self):
        self.previous_server = server.server
        server.server = 'en'

    def tearDown(self):
        server.server = self.previous_server

    def test_rejects_far_names(self):
        from module.island_planner.data import DIC_ISLAND_TASK
        from module.island_planner.season_tasks import match_task_name
        ids = [tid for tid, task in DIC_ISLAND_TASK.items() if task['name']['en'] == 'More Rice!']
        self.assertTrue(ids)
        # 11-02 日志：只读到「F」却被纠正为「More Rice!」
        self.assertIsNone(match_task_name('F', ids))
        self.assertIn(match_task_name('MoreRice!', ids), ids)

    def test_no_cards_keeps_targets(self):
        from unittest.mock import Mock
        from module.island_planner.season_tasks import IslandSeasonTaskScanner
        scanner = IslandSeasonTaskScanner.__new__(IslandSeasonTaskScanner)
        scanner.loop = Mock(side_effect=lambda **kwargs: iter(range(2)))
        scanner._task_rows = Mock(return_value=np.empty((0, 2)))
        with patch('module.island_planner.season_tasks.ISLAND_SEASON_TASK_SCROLL') as scroll:
            self.assertIsNone(scanner.scan_unfinished())
            scroll.next_page.assert_not_called()

    def test_planner_keeps_saved_targets_when_scan_fails(self):
        from module.island_planner.planner import IslandProductionPlanner
        with patch.object(IslandProductionPlanner, '__init__', lambda self: None):
            planner = IslandProductionPlanner()
        planner.config = FakeConfig({}, IslandProductionPlanner_ScanSeasonTasks=True,
                                    IslandProductionPlanner_ScanCargoOrders=False,
                                    IslandProductionPlanner_SeasonTaskTargets='Apple Pie: 30')
        planner.scan_season_task_targets = lambda: None
        demands, targets = planner.load_targets()
        self.assertEqual(demands, {3009: [30]})
        self.assertEqual(targets, {3009: [30]})
        self.assertNotIn('IslandProductionPlanner.IslandProductionPlanner.SeasonTaskTargets', planner.config.written)


class ScannerGeometryTest(unittest.TestCase):
    def test_node_positions_cover_scanned_tabs(self):
        from module.island_planner.scanner import SCANNED_TABS, get_technology_tab_and_position, node_in_view
        tabs = {get_technology_tab_and_position(tech_id)[0] for tech_id in DIC_ISLAND_TECHNOLOGY}
        self.assertTrue(set(SCANNED_TABS) <= tabs)
        # 视野左端时，第一列节点可见，很远的节点不可见
        self.assertTrue(node_in_view((ORIGIN_FIRST_COLUMN_X, 106), 0))
        self.assertFalse(node_in_view((5000, 106), 0))


ORIGIN_FIRST_COLUMN_X = 136 + 2 / 3 * 1 - 5 / 3 + 136


if __name__ == '__main__':
    unittest.main()
