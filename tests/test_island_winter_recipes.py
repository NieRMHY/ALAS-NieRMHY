"""冬季餐品配方推导（island_winter_recipes）的真实数据对照。

四道冬季菜的 shop/time_min/materials 必须由游戏原表推出，不能手抄；同时用经济表里
46 道能对上菜单的菜品反证「时间 = workload / 600」「材料名映射」两套规则本身没错。
"""
import unittest
from unittest.mock import patch

from module.island import island_winter_meals
from module.island import island_winter_recipes as winter_recipes
from module.island.island_economy import BASE_MATERIALS, ECONOMY_PRODUCTS
from module.island.island_planner import SHOP_TASKS
from module.island.island_season import SEASONAL_ITEMS
from module.island_planner import settings_map
from module.island_planner.data import (
    DIC_ISLAND_RECIPE,
    DIC_ISLAND_RESTAURANT_MENU_TO_RECIPE,
)

# 与 DIC_ISLAND_RECIPE 9900027-9900030 一致：workload 24000/9000/12000/12000，
# commission_cost 见测试内断言；数值不来自 wiki，也不来自本表的重复抄写。
EXPECTED = {
    'shiitake_chicken_soup': {
        'shop': 'restaurant', 'time_min': 40.0,
        'materials': {'winter_shiitake': 2, 'chicken': 1},
    },
    'green_jujube_porridge': {
        'shop': 'restaurant', 'time_min': 15.0,
        'materials': {'green_jujube': 2, 'rice': 5},
    },
    'water_chestnut_cake': {
        'shop': 'juu_eatery', 'time_min': 20.0,
        'materials': {'water_chestnut': 2},
    },
    'sugar_tangerine_daifuku': {
        'shop': 'juu_eatery', 'time_min': 20.0,
        'materials': {'sugar_tangerine': 2, 'wheat_flour': 3},
    },
}


class FakeConfig:
    def __init__(self, values):
        self.values = values

    def cross_get(self, key, default=None):
        return self.values.get(key, default)


def business_config(shop, items):
    """商区配置：把 items 填进该店的 Product1..N（其余槽位与餐品槽保持缺省）。"""
    index = SHOP_TASKS[shop][1]
    values = {'IslandBusiness.IslandBusiness.ShopLevel': 'diamond',
              'IslandPlan.IslandPlan.Season': 'winter'}
    for slot, item in enumerate(items, start=1):
        values[f'IslandBusiness.IslandBusinessShop{index}.Product{slot}'] = item
    return FakeConfig(values)


def menu_dishes():
    """经济表与菜单表都对得上的菜品：[(菜品名, 配方 ID)]。"""
    dish_by_id = {item_id: name for name, item_id in settings_map.DISH_ITEM_IDS.items()}
    found = []
    for menu in DIC_ISLAND_RESTAURANT_MENU_TO_RECIPE.values():
        for item_id, recipe_id in menu.items():
            name = dish_by_id.get(item_id)
            if name in ECONOMY_PRODUCTS:
                found.append((name, recipe_id))
    return found


class WinterRecipeDataTests(unittest.TestCase):
    def test_recipes_match_game_data(self):
        """四道冬季菜的三个字段必须与游戏配方表推导结果完全一致。"""
        self.assertEqual(winter_recipes.WINTER_MEAL_UNKNOWN, {})
        self.assertEqual(winter_recipes.WINTER_MEAL_RECIPES, EXPECTED)
        self.assertEqual(DIC_ISLAND_RECIPE[9900027]['workload'], 24000)
        self.assertEqual(DIC_ISLAND_RECIPE[9900027]['commission_cost'], {4045: 2, 2602: 1})
        self.assertEqual(DIC_ISLAND_RECIPE[9900028]['commission_cost'], {4049: 2, 2002: 5})
        self.assertEqual(DIC_ISLAND_RECIPE[9900029]['commission_cost'], {4046: 2})
        self.assertEqual(DIC_ISLAND_RECIPE[9900030]['commission_cost'], {4047: 2, 3004: 3})

    def test_workload_per_minute_follows_daily_workload(self):
        """每分钟工作量由 DAILY_WORKLOAD 推出，不另写 600。"""
        self.assertEqual(settings_map.DAILY_WORKLOAD, 24 * 60 * 60 * 10)
        self.assertEqual(winter_recipes.WORKLOAD_PER_MINUTE,
                         settings_map.DAILY_WORKLOAD // (24 * 60))

    def test_derived_time_matches_economy_table(self):
        """已进经济表的菜品：workload / 每分钟工作量 = time_min（46 道全部相等）。"""
        dishes = menu_dishes()
        self.assertGreaterEqual(len(dishes), 40, '菜单与经济表对不上的菜品过多，规则验证失效')
        for name, recipe_id in dishes:
            with self.subTest(dish=name):
                self.assertAlmostEqual(
                    DIC_ISLAND_RECIPE[recipe_id]['workload'] / winter_recipes.WORKLOAD_PER_MINUTE,
                    ECONOMY_PRODUCTS[name]['time_min'],
                )

    def test_derived_materials_match_economy_table(self):
        """已进经济表的菜品：物品 ID 反查出的材料名与数量必须和经济表一模一样。"""
        for name, recipe_id in menu_dishes():
            with self.subTest(dish=name):
                derived = {winter_recipes.material_name(item_id): count
                           for item_id, count in DIC_ISLAND_RECIPE[recipe_id]['commission_cost'].items()}
                self.assertNotIn(None, derived, f'{name} 有无法命名的材料')
                self.assertEqual(derived, ECONOMY_PRODUCTS[name]['materials'])

    def test_shop_matches_kitchen_and_season_table(self):
        """店铺来自冬季季节表，且与该餐厅已入库菜品的 shop 一致。"""
        dish_by_id = {item_id: name for name, item_id in settings_map.DISH_ITEM_IDS.items()}
        for name, info in winter_recipes.WINTER_MEAL_RECIPES.items():
            with self.subTest(dish=name):
                item_id = settings_map.DISH_ITEM_IDS[name]
                kitchens = [rid for rid, menu in DIC_ISLAND_RESTAURANT_MENU_TO_RECIPE.items()
                            if item_id in menu]
                self.assertEqual(len(kitchens), 1)
                menu = DIC_ISLAND_RESTAURANT_MENU_TO_RECIPE[kitchens[0]]
                shops = {ECONOMY_PRODUCTS[dish_by_id[i]]['shop'] for i in menu
                         if dish_by_id.get(i) in ECONOMY_PRODUCTS}
                self.assertEqual(shops, {info['shop']})
                self.assertIn(name, SEASONAL_ITEMS['winter'][info['shop']])

    def test_materials_are_resolvable_after_base_materials_extended(self):
        """材料要么是商品，要么在 BASE_MATERIALS，要么由 required_base_materials() 补上。"""
        required = winter_recipes.required_base_materials()
        self.assertEqual(required,
                         {'winter_shiitake', 'water_chestnut', 'green_jujube', 'sugar_tangerine'})
        self.assertEqual(required & set(ECONOMY_PRODUCTS), set())
        resolvable = set(ECONOMY_PRODUCTS) | set(BASE_MATERIALS) | set(required)
        for info in winter_recipes.WINTER_MEAL_RECIPES.values():
            for material in info['materials']:
                self.assertIn(material, resolvable)


class WinterRecipeMergeTests(unittest.TestCase):
    def test_extension_carries_only_known_fields_and_copies(self):
        """只带 shop/time_min/materials，且改副本不会污染常量。"""
        extension = winter_recipes.economy_extension()
        self.assertEqual(set(extension), set(winter_recipes.WINTER_MEAL_RECIPES))
        for name, info in extension.items():
            self.assertEqual(set(info), {'shop', 'time_min', 'materials'})
            info['materials']['mutated'] = 1
            self.assertNotIn('mutated', winter_recipes.WINTER_MEAL_RECIPES[name]['materials'])

    def test_with_winter_meals_does_not_touch_input_or_overwrite(self):
        before = dict(ECONOMY_PRODUCTS)
        merged = winter_recipes.with_winter_meals(ECONOMY_PRODUCTS)
        self.assertIsNot(merged, ECONOMY_PRODUCTS)
        self.assertEqual(set(ECONOMY_PRODUCTS), set(before))
        for name in winter_recipes.WINTER_MEAL_RECIPES:
            self.assertIn(name, merged)
        sentinel = {'shop': 'restaurant', 'time_min': 1.0, 'materials': {}}
        kept = winter_recipes.with_winter_meals({'shiitake_chicken_soup': sentinel})
        self.assertIs(kept['shiitake_chicken_soup'], sentinel)

    def test_economy_values_stay_consistent_if_dish_is_added_later(self):
        """经济表将来补齐这四道菜时，本表不能和经济表打架。"""
        for name, info in winter_recipes.WINTER_MEAL_RECIPES.items():
            known = ECONOMY_PRODUCTS.get(name)
            if known is None:
                continue
            with self.subTest(dish=name):
                self.assertEqual(known['shop'], info['shop'])
                self.assertEqual(known['materials'], info['materials'])
                self.assertAlmostEqual(known['time_min'], info['time_min'])


class WinterRecipeBusinessRequirementTests(unittest.TestCase):
    def test_business_requirements_marks_winter_dishes_unknown_without_merge(self):
        """回归：MEAL_RECIPES 缺冬季配方时，business_requirements 把它们整店判成未知。"""
        if 'shiitake_chicken_soup' in ECONOMY_PRODUCTS:
            self.skipTest('经济表已补齐冬季菜品')
        with patch.object(island_winter_meals, 'MEAL_RECIPES', ECONOMY_PRODUCTS):
            totals, unknown = island_winter_meals.business_requirements(
                business_config('restaurant', ['shiitake_chicken_soup']))
        self.assertEqual(unknown, {'restaurant'})
        self.assertEqual(totals, {})

    def test_business_requirements_accepts_winter_dishes_with_merged_table(self):
        """MEAL_RECIPES 默认已并入冬季表：四道菜不再未知，且按每格 6 个计入目标。"""
        merged = winter_recipes.with_winter_meals(ECONOMY_PRODUCTS)
        self.assertEqual(island_winter_meals.MEAL_RECIPES, merged)
        with patch.object(island_winter_meals, 'MEAL_RECIPES', merged):
            totals, unknown = island_winter_meals.business_requirements(
                business_config('restaurant',
                                ['shiitake_chicken_soup', 'green_jujube_porridge']))
            self.assertEqual(unknown, set())
            self.assertEqual(totals.get('shiitake_chicken_soup'), 6)
            self.assertEqual(totals.get('green_jujube_porridge'), 6)
            totals, unknown = island_winter_meals.business_requirements(
                business_config('juu_eatery',
                                ['water_chestnut_cake', 'sugar_tangerine_daifuku']))
            self.assertEqual(unknown, set())
            self.assertEqual(totals.get('water_chestnut_cake'), 6)
            self.assertEqual(totals.get('sugar_tangerine_daifuku'), 6)


if __name__ == '__main__':
    unittest.main()
