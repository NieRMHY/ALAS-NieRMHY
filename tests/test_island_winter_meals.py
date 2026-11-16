"""冬季餐品营业储备、备用产能与独立账本（island_winter_meals）的纯逻辑测试。

这里只测 helper 的业务口径，不驱动店铺 UI：营业储备按货架直售 + 套餐整条配方算，
备用产能只扣一轮货架补货，任务目标由 Need/Done/MealBuffer 决定，账本按天保存
库存与已派工时。运行时串联见 test_island_winter_shop_runtime.py。
"""
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from module.island import island_winter_meals as W
from module.island.island_economy import ECONOMY_PRODUCTS
from module.island.island_planner import SHOP_TASKS
from module.island.island_winter_recipes import WINTER_MEAL_RECIPES

SEASON_GROUP = 'IslandSeasonPlan.IslandSeasonPlan'
NOW = datetime(2026, 11, 9, 12, 0, 0)
WINTER_DISHES = (
    'shiitake_chicken_soup',
    'green_jujube_porridge',
    'water_chestnut_cake',
    'sugar_tangerine_daifuku',
)


class FakeConfig:
    """只实现 cross_get 与 config_name 的配置替身。"""

    def __init__(self, values=None, config_name='ALAS'):
        self.values = values or {}
        self.config_name = config_name

    def cross_get(self, key, default=None):
        return self.values.get(key, default)


def shop_spec(products=(), chars=(), meals=()):
    """一家店的配置：Product1..N、Char1..2、本任务 Meal1..N（物品, 数量）。"""
    return {'products': products, 'chars': chars, 'meals': meals}


def make_config(season='winter', shops=None, **overrides):
    """构造冬季配置；短键自动补 IslandSeasonPlan 前缀，完整键原样写入。"""
    values = {
        'IslandPlan.IslandPlan.Season': season,
        'IslandBusiness.IslandBusiness.ShopLevel': 'diamond',
    }
    for shop, spec in (shops or {}).items():
        index = SHOP_TASKS[shop][1]
        task = SHOP_TASKS[shop][0]
        for slot, item in enumerate(spec.get('products', ()), 1):
            values[f'IslandBusiness.IslandBusinessShop{index}.Product{slot}'] = item
        for slot, char in enumerate(spec.get('chars', ()), 1):
            values[f'IslandBusiness.IslandBusinessShop{index}.Char{slot}'] = char
        for slot, (item, qty) in enumerate(spec.get('meals', ()), 1):
            values[f'{task}.{task}.Meal{slot}'] = item
            values[f'{task}.{task}.MealNumber{slot}'] = qty
    for key, value in overrides.items():
        values[key if key.startswith('Island') else f'{SEASON_GROUP}.{key}'] = value
    return FakeConfig(values)


class MealRecipeTableTests(unittest.TestCase):
    def test_meal_table_merges_four_winter_recipes_without_mutating_economy(self):
        """MEAL_RECIPES 默认包含四道冬季菜，且不写回经济表。"""
        self.assertIsNot(W.MEAL_RECIPES, ECONOMY_PRODUCTS)
        for name in WINTER_DISHES:
            with self.subTest(dish=name):
                self.assertIn(name, W.MEAL_RECIPES)
                self.assertEqual(W.MEAL_RECIPES[name], WINTER_MEAL_RECIPES[name])
        # 已有菜品仍是经济表的同一对象：只做浅拷贝，不复制也不改原表。
        self.assertIs(W.MEAL_RECIPES['tofu'], ECONOMY_PRODUCTS['tofu'])
        self.assertEqual(set(W.TASK_MEALS),
                         {'chicken_potato', 'rice_mango', 'strawberry_charlotte'})
        self.assertEqual(W.FINITE_MEALS, frozenset((*W.TASK_MEALS, 'cheese')))


class BusinessRequirementTests(unittest.TestCase):
    def test_direct_sale_and_multi_parent_ingredients_add_up(self):
        """货架直售与套餐耗用相加；芝士同时被夏洛特和醒神套餐消耗。"""
        config = make_config(shops={
            'juu_coffee': shop_spec(products=['cheese']),
            'juu_eatery': shop_spec(meals=[
                ('strawberry_charlotte', 10),
                ('wake_up_call', 5),
            ]),
        })
        totals, unknown = W.business_requirements(config)
        self.assertEqual(unknown, set())
        # 芝士：直售 6 + 夏洛特 10x2 + 醒神 5x1 = 31
        # 冰咖啡：醒神套餐 5x1 = 5，说明配方链会继续向下展开。
        self.assertEqual(totals, {
            'cheese': 31,
            'strawberry_charlotte': 10,
            'wake_up_call': 5,
            'iced_coffee': 5,
        })

    def test_explicit_meal_targets_use_max_not_sum(self):
        """同一菜品出现在多个套餐槽位时，库存下限取最大值，不累加。"""
        config = make_config(shops={
            'grill': shop_spec(products=['chicken_potato'], meals=[
                ('chicken_potato', 10),
                ('chicken_potato', 20),
            ]),
        })
        totals, unknown = W.business_requirements(config)
        self.assertEqual(unknown, set())
        self.assertEqual(totals, {'chicken_potato': 20})

    def test_four_winter_dishes_are_counted_per_shelf_slot(self):
        """冬季四道菜已能作为货架商品计入营业储备，不再整店判未知。"""
        config = make_config(shops={
            'restaurant': shop_spec(products=[
                'shiitake_chicken_soup', 'green_jujube_porridge']),
            'juu_eatery': shop_spec(products=[
                'water_chestnut_cake', 'sugar_tangerine_daifuku']),
        })
        totals, unknown = W.business_requirements(config)
        self.assertEqual(unknown, set())
        self.assertEqual(totals, {name: 6 for name in WINTER_DISHES})

    def test_other_season_items_are_filtered_on_both_sides(self):
        """冬季只认冬季菜；换成秋季后冬季菜被过滤，而不是记成未知。"""
        shops = {'restaurant': shop_spec(
            products=['matsutake_chicken_soup', 'shiitake_chicken_soup'],
            meals=[('matsutake_chicken_soup', 9), ('shiitake_chicken_soup', 7)],
        )}
        totals, unknown = W.business_requirements(make_config(shops=shops))
        self.assertEqual(unknown, set())
        self.assertEqual(totals, {'shiitake_chicken_soup': 7})

        totals, unknown = W.business_requirements(
            make_config(season='autumn', shops=shops))
        self.assertEqual(unknown, set())
        self.assertEqual(totals, {'matsutake_chicken_soup': 9})

    def test_shop_level_limits_products_independently_of_plan_settings(self):
        """冬季保留现有货架；方案生成格数不应削减实际营业储备。"""
        products = ['tofu', 'omurice', 'salad', 'fo_tiao']
        totals, unknown = W.business_requirements(make_config(shops={
            'restaurant': shop_spec(products=products)}))
        self.assertEqual(unknown, set())
        self.assertEqual(totals, {name: 6 for name in products})

        totals, unknown = W.business_requirements(make_config(
            shops={'restaurant': shop_spec(products=products)},
            **{'IslandBusiness.IslandBusiness.ShopLevel': 'bronze'}))
        self.assertEqual(unknown, set())
        self.assertEqual(totals, {'tofu': 5, 'omurice': 5})

        for slots in (1, 2, 99, 'invalid'):
            expected = {name: 6 for name in products}
            with self.subTest(slots=slots):
                totals, unknown = W.business_requirements(make_config(
                    shops={'restaurant': shop_spec(products=products)},
                    **{'IslandPlan.IslandPlan.PlanShelfSlots': slots}))
                self.assertEqual(unknown, set())
                self.assertEqual(totals, expected)

    def test_capacity_boost_character_adds_one_per_slot_once(self):
        """容量角色每格 +1；两名加成角色不叠加，非本店角色不生效。"""
        cases = (
            ((), 6),
            (('ChangFeng',), 7),
            (('ChaoHo',), 7),
            (('ChaoHo', 'ChangFeng'), 7),
            (('Cheshire',), 6),
        )
        for chars, expected in cases:
            with self.subTest(chars=chars):
                totals, unknown = W.business_requirements(make_config(shops={
                    'restaurant': shop_spec(products=['tofu', 'omurice'], chars=chars)}))
                self.assertEqual(unknown, set())
                self.assertEqual(totals, {'tofu': expected, 'omurice': expected})

    def test_unknown_products_mark_shop_but_known_slots_still_count(self):
        config = make_config(shops={
            'restaurant': shop_spec(products=['mystery_dish', 'tofu', 'tofu'])})
        totals, unknown = W.business_requirements(config)
        self.assertEqual(unknown, {'restaurant'})
        self.assertEqual(totals, {'tofu': 12})

    def test_zero_quantity_unknown_meal_is_ignored(self):
        """未知菜品数量为 0 时还没进入排产，不能把整店判成未知。"""
        config = make_config(shops={
            'restaurant': shop_spec(meals=[('mystery_dish', 0), ('tofu', 1)])})
        totals, unknown = W.business_requirements(config)
        self.assertEqual(unknown, set())
        self.assertEqual(totals, {'tofu': 1})

        config = make_config(shops={
            'restaurant': shop_spec(meals=[('mystery_dish', 1)])})
        totals, unknown = W.business_requirements(config)
        self.assertEqual(unknown, {'restaurant'})
        self.assertEqual(totals, {})


class TaskTargetTests(unittest.TestCase):
    def test_default_need_and_buffer_are_added_to_baseline(self):
        config = make_config()
        baseline = {'chicken_potato': 6, 'rice_mango': 6,
                    'strawberry_charlotte': 6, 'cheese': 6}
        targets = W.task_targets(config, baseline, {'strawberry_charlotte': 51})
        self.assertEqual(targets, {
            'chicken_potato': 126,
            'rice_mango': 76,
            'strawberry_charlotte': 51,
            'cheese': 6,
        })

    def test_configured_need_buffer_and_zero_need(self):
        config = make_config(Need_chicken_potato=10, Need_rice_mango=0,
                             Need_strawberry_charlotte=5, MealBuffer=3)
        baseline = {'chicken_potato': 6, 'rice_mango': 6,
                    'strawberry_charlotte': 6, 'cheese': 6}
        targets = W.task_targets(config, baseline, {'strawberry_charlotte': 12})
        self.assertEqual(targets, {
            'chicken_potato': 19,
            'strawberry_charlotte': 14,
            'cheese': 10,
        })
        self.assertNotIn('rice_mango', targets)

    def test_done_removes_slot_and_cheese_reserve(self):
        config = make_config(Done_strawberry_charlotte=True, Need_rice_mango=0)
        targets = W.task_targets(config, {'cheese': 6}, {'strawberry_charlotte': 0})
        self.assertNotIn('strawberry_charlotte', targets)
        self.assertNotIn('rice_mango', targets)
        self.assertNotIn('cheese', targets)

    def test_disabled_or_other_season_has_no_targets(self):
        self.assertTrue(W.enabled(make_config()))
        cases = (
            ('winter-off', make_config(WinterTaskEnabled=False)),
            ('autumn', make_config(season='autumn')),
        )
        for label, config in cases:
            with self.subTest(case=label):
                self.assertFalse(W.enabled(config))
                self.assertEqual(W.task_targets(config, {}, {'strawberry_charlotte': 0}), {})

    def test_charlotte_wip_discounts_cheese_and_unknown_skips_it(self):
        """夏洛特在产数量抵扣缺口；库存未知时不凭猜测补芝士。"""
        config = make_config(Need_strawberry_charlotte=25, MealBuffer=0)
        for have, expected_cheese in ((0, 56), (10, 36), (25, 6), (40, 6)):
            with self.subTest(have=have):
                targets = W.task_targets(
                    config, {'cheese': 6}, {'strawberry_charlotte': have})
                self.assertEqual(targets['strawberry_charlotte'], 25)
                self.assertEqual(targets['cheese'], expected_cheese)

        targets = W.task_targets(
            config, {'cheese': 6}, {'strawberry_charlotte': None})
        self.assertEqual(targets['strawberry_charlotte'], 25)
        self.assertNotIn('cheese', targets)


class SpareMinuteTests(unittest.TestCase):
    def test_spare_is_ninety_percent_of_post_minutes_minus_one_shelf_round(self):
        """备用产能 = 岗位数 x 24h x 90% - 本店一轮货架补货工时。"""
        config = make_config(shops={
            'grill': shop_spec(products=['chicken_potato'])})
        self.assertAlmostEqual(W.spare_minutes(config, {}, set(), 'grill'), 1116.0)

        config = make_config(shops={
            'restaurant': shop_spec(products=['tofu', 'omurice'])})
        self.assertAlmostEqual(W.spare_minutes(config, {}, set(), 'restaurant'), 2232.0)

        config = make_config(shops={
            'restaurant': shop_spec(products=['tofu', 'omurice'])},
            **{'IslandRestaurant.IslandRestaurant.PostNumber': 3})
        self.assertAlmostEqual(W.spare_minutes(config, {}, set(), 'restaurant'), 3528.0)

    def test_large_meal_targets_do_not_consume_daily_budget(self):
        """Meal 是库存目标，不是每日销量；大套餐不能把备用产能吃成 0。"""
        config = make_config(shops={
            'grill': shop_spec(products=['chicken_potato'], meals=[
                ('chicken_potato', 5000)])})
        totals, unknown = W.business_requirements(config)
        self.assertEqual(unknown, set())
        self.assertEqual(totals, {'chicken_potato': 5000})
        shelf, shelf_unknown = W.business_requirements(config, include_targets=False)
        self.assertEqual(shelf_unknown, set())
        self.assertEqual(shelf, {'chicken_potato': 6})
        self.assertAlmostEqual(W.spare_minutes(config, {}, set(), 'grill'), 1116.0)

    def test_unknown_recipe_or_shelf_item_blocks_spare(self):
        config = make_config(shops={
            'grill': shop_spec(products=['chicken_potato'])})
        self.assertEqual(W.spare_minutes(config, {}, {'grill'}, 'grill'), 0)

        config = make_config(shops={
            'grill': shop_spec(products=['mystery_dish'])})
        self.assertEqual(W.spare_minutes(config, {}, set(), 'grill'), 0)

    def test_other_shop_shelf_does_not_consume_budget(self):
        config = make_config(shops={
            'restaurant': shop_spec(products=['tofu'])})
        self.assertAlmostEqual(W.spare_minutes(config, {}, set(), 'grill'), 1296.0)
        self.assertAlmostEqual(W.spare_minutes(config, {}, set(), 'restaurant'), 2352.0)


class PlanBatchTests(unittest.TestCase):
    def test_active_tasks_share_one_budget(self):
        """同店多个任务按顺序共用剩余产能，后面的菜只能拿剩下的工时。"""
        config = make_config(MealBuffer=0, Need_rice_mango=2,
                             Need_strawberry_charlotte=10)
        spare = W.spare_minutes(config, {}, set(), 'juu_eatery')
        self.assertAlmostEqual(spare, 1296.0)
        batches = W.plan_batches(
            config, 'juu_eatery', {}, set(),
            {'rice_mango': 0, 'strawberry_charlotte': 0},
            {'cheese': 100}, spent=spare - 100)
        # 100 分钟：芒果糯米饭 2 个用 40 分钟，夏洛特 1 个用 35 分钟，剩 25。
        self.assertEqual(batches, {'rice_mango': 2, 'strawberry_charlotte': 1})

    def test_budget_floors_partial_item_and_spent_blocks_all(self):
        config = make_config(MealBuffer=0, Need_rice_mango=10)
        spare = W.spare_minutes(config, {}, set(), 'juu_eatery')
        batches = W.plan_batches(
            config, 'juu_eatery', {}, set(), {'rice_mango': 0},
            {'cheese': 0}, spent=spare - 39)
        self.assertEqual(batches, {'rice_mango': 1})

        for spent in (spare, spare + 1):
            with self.subTest(spent=spent):
                self.assertEqual(W.plan_batches(
                    config, 'juu_eatery', {}, set(), {'rice_mango': 0},
                    {'cheese': 0}, spent=spent), {})

    def test_unknown_inventory_or_recipe_skips_only_that_item(self):
        config = make_config(MealBuffer=0, Need_rice_mango=2,
                             Need_strawberry_charlotte=10)
        batches = W.plan_batches(
            config, 'juu_eatery', {}, set(),
            {'rice_mango': None, 'strawberry_charlotte': 0},
            {'cheese': 100})
        self.assertEqual(batches, {'strawberry_charlotte': 10})

        self.assertEqual(W.plan_batches(
            config, 'juu_eatery', {}, {'juu_eatery'},
            {'rice_mango': 0, 'strawberry_charlotte': 0},
            {'cheese': 100}), {})

    def test_charlotte_uses_only_cheese_above_direct_sale_reserve(self):
        """夏洛特只能吃直售保留线以上的芝士；库存未知时不排产。"""
        config = make_config(MealBuffer=0, Need_strawberry_charlotte=10)
        baseline = {'cheese': 6}
        totals = {'strawberry_charlotte': 4}
        cases = (
            (10, {'strawberry_charlotte': 2}),
            (12, {'strawberry_charlotte': 3}),
            (6, {}),
            (5, {}),
            (None, {}),
            (-1, {}),
        )
        for cheese, expected in cases:
            with self.subTest(cheese=cheese):
                self.assertEqual(W.plan_batches(
                    config, 'juu_eatery', baseline, set(), totals,
                    {'cheese': cheese}), expected)

    def test_charlotte_wip_reduces_batch(self):
        config = make_config(MealBuffer=0, Need_strawberry_charlotte=10)
        self.assertEqual(W.plan_batches(
            config, 'juu_eatery', {}, set(),
            {'strawberry_charlotte': 9}, {'cheese': 100}),
            {'strawberry_charlotte': 1})
        self.assertEqual(W.plan_batches(
            config, 'juu_eatery', {}, set(),
            {'strawberry_charlotte': 10}, {'cheese': 100}), {})

    def test_only_own_shop_items_are_batched(self):
        config = make_config(MealBuffer=0, Need_chicken_potato=1,
                             Need_rice_mango=0, Need_strawberry_charlotte=0)
        self.assertEqual(W.plan_batches(
            config, 'juu_eatery', {}, set(), {'chicken_potato': 0},
            {'cheese': 100}), {})


class ProtectedAwayTests(unittest.TestCase):
    def test_active_task_ingredients_and_parents_are_protected(self):
        """活跃任务本身、它的原料、以及会消耗这些原料的套餐都要避开。"""
        config = make_config()
        for item in ('chicken_potato', 'rice_mango', 'strawberry_charlotte',
                     'carnival', 'succulently_sweet', 'berry_orange',
                     'cheese', 'wake_up_call'):
            with self.subTest(item=item):
                self.assertTrue(W.protected_away(config, item))
        for item in ('tofu_combo', 'seafood_rice', 'iced_coffee', 'milk', None):
            with self.subTest(item=item):
                self.assertFalse(W.protected_away(config, item))

    def test_done_or_zero_need_releases_away_products(self):
        cases = (
            make_config(Done_strawberry_charlotte=True),
            make_config(Need_strawberry_charlotte=0),
        )
        for config in cases:
            with self.subTest(config=config.values):
                self.assertFalse(W.protected_away(config, 'strawberry_charlotte'))
                self.assertFalse(W.protected_away(config, 'cheese'))
                self.assertFalse(W.protected_away(config, 'wake_up_call'))
                # 其他未完成任务仍然受保护。
                self.assertTrue(W.protected_away(config, 'rice_mango'))
                self.assertTrue(W.protected_away(config, 'succulently_sweet'))

    def test_winter_disabled_releases_everything(self):
        config = make_config(WinterTaskEnabled=False)
        for item in ('chicken_potato', 'rice_mango', 'strawberry_charlotte',
                     'cheese', 'carnival', 'wake_up_call'):
            with self.subTest(item=item):
                self.assertFalse(W.protected_away(config, item))

    def test_recursion_follows_materials_not_parents(self):
        """只沿配方材料向下查：醒神套餐因含芝士被保护，冰咖啡本身不保护。"""
        config = make_config(Need_chicken_potato=0, Need_rice_mango=0,
                             Need_strawberry_charlotte=25)
        self.assertTrue(W.protected_away(config, 'cheese'))
        self.assertTrue(W.protected_away(config, 'wake_up_call'))
        self.assertTrue(W.protected_away(config, 'berry_orange'))
        self.assertFalse(W.protected_away(config, 'iced_coffee'))
        self.assertFalse(W.protected_away(config, 'milk'))


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = patch.object(W, 'STATE_DIR', self.temp.name)
        self.state.start()
        self.addCleanup(self.state.stop)
        self.clock = patch.object(W, 'now', return_value=NOW)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.config = FakeConfig(config_name='ALAS')

    def path(self):
        return W.ledger_path(self.config)

    def write(self, data):
        self.path().write_text(json.dumps(data), encoding='utf-8')

    def test_ledger_path_is_per_instance_and_stays_in_state_dir(self):
        self.assertEqual(self.path(),
                         Path(self.temp.name) / 'winter_meals_ALAS.json')
        # 实例名只取 basename，不能借配置名跳出账本目录。
        nested = FakeConfig(config_name='../instance/EN')
        self.assertEqual(W.ledger_path(nested),
                         Path(self.temp.name) / 'winter_meals_EN.json')

    def test_missing_file_starts_today_with_empty_sections(self):
        self.assertEqual(W.load_ledger(self.config), {
            'date': NOW.date().isoformat(), 'totals': {}, 'spent': {}})

    def test_same_day_preserves_spent_and_totals(self):
        data = {
            'date': NOW.date().isoformat(),
            'totals': {'chicken_potato': 0, 'cheese': None},
            'spent': {'grill': 120.5},
        }
        W.save_ledger(self.config, data)
        self.assertEqual(W.load_ledger(self.config), data)
        # 缺失的 spent 段补空，不因缺字段失败。
        partial = {'date': NOW.date().isoformat(), 'totals': {'rice_mango': 3}}
        self.write(partial)
        self.assertEqual(W.load_ledger(self.config),
                         {'date': NOW.date().isoformat(),
                          'totals': {'rice_mango': 3}, 'spent': {}})

    def test_cross_day_clears_spent_and_totals(self):
        self.write({
            'date': '2026-11-08',
            'totals': {'chicken_potato': None, 'rice_mango': 8},
            'spent': {'grill': 90},
        })
        self.assertEqual(W.load_ledger(self.config), {
            'date': NOW.date().isoformat(), 'totals': {}, 'spent': {}})

    def test_corrupt_shapes_and_values_raise(self):
        cases = {
            'top-list': [],
            'top-string': 'bad',
            'totals-list': {'totals': []},
            'spent-string': {'spent': 'bad'},
            'spent-none': {'spent': None},
            'totals-text': {'totals': {'x': '1'}},
            'totals-bool': {'totals': {'x': True}},
            'totals-negative': {'totals': {'x': -1}},
            'totals-nan': {'totals': {'x': float('nan')}},
            'totals-inf': {'totals': {'x': float('inf')}},
            'spent-none-value': {'spent': {'x': None}},
            'spent-bool': {'spent': {'x': False}},
            'spent-negative': {'spent': {'x': -0.5}},
            'spent-nan': {'spent': {'x': float('nan')}},
            'spent-text': {'spent': {'x': '2'}},
        }
        for label, data in cases.items():
            with self.subTest(case=label):
                self.write(data)
                with self.assertRaises(ValueError):
                    W.load_ledger(self.config)

        # 损坏的旧账本先报错，不能借跨天重置把异常数据洗掉。
        self.write({'date': '2026-11-08', 'spent': {'grill': 'bad'}})
        with self.assertRaises(ValueError):
            W.load_ledger(self.config)

    def test_save_creates_directory_and_replaces_atomically(self):
        nested = Path(self.temp.name) / 'nested'
        with patch.object(W, 'STATE_DIR', str(nested)):
            W.save_ledger(self.config, {
                'date': NOW.date().isoformat(), 'totals': {'x': 1}, 'spent': {}})
            W.save_ledger(self.config, {
                'date': NOW.date().isoformat(), 'totals': {'x': 2}, 'spent': {}})
            path = W.ledger_path(self.config)
            self.assertTrue(path.exists())
            self.assertFalse(path.with_suffix('.tmp').exists())
            self.assertEqual(W.load_ledger(self.config)['totals'], {'x': 2})


if __name__ == '__main__':
    unittest.main()
