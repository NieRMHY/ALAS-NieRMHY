"""用假 UI 验证店铺共用排产流程，不连接配置文件或游戏。"""

import unittest
from collections import Counter
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.exception import GameBugError
from module.island.island import Island
from module.island.island_grill import IslandGrill
from module.island.island_juu_coffee import IslandJuuCoffee
from module.island.island_juu_eatery import IslandJuuEatery
from module.island.island_restaurant import IslandRestaurant
from module.island.island_season import SeasonConfig
from module.island.island_teahouse import (
    FIXED_SELECT_CHRYSANTHEMUM_TEA,
    FIXED_SELECT_SPRING_FLOWER_TEA,
    SELECT_CHRYSANTHEMUM_TEA,
    IslandTeahouse,
)


NOW = datetime(2026, 9, 19, 12)


class ShopUI:
    """保留真实配方和排产，只模拟岗位状态、库存读取及下单结果。"""

    def __init__(self, shop_class, products=(), stock=None, *, seasonal=False,
                 season='spring', away=None, working=None):
        config = SimpleNamespace(
            IslandRestaurant_ChefFilter='WorkerJuu',
            IslandTeahouse_ChefFilter='WorkerJuu',
            IslandGrill_ChefFilter='WorkerJuu',
            IslandJuuCoffee_ChefFilter='WorkerJuu',
            IslandJuuCoffee_Friedrich=False,
            IslandJuuEatery_ChefFilter='WorkerJuu',
            IslandRestaurant_DoubleBambooShoots=seasonal,
            IslandTeahouse_Seasonal=seasonal,
            cross_get=Mock(return_value=season),
            task_delay=Mock(),
        )

        def init_island(shop, config, device=None, task=None):
            shop.config = config
            shop.device = device
            shop.unavailable_characters = set()

        with patch.object(Island, '__init__', init_island), patch(
            'module.island.island_shop_base.get_global_season_config',
            side_effect=SeasonConfig,
        ):
            self.shop = shop_class(config)
        shop = self.shop
        shop.post_products = list(products)
        setattr(config, shop.config_away_cook, away)
        self.stock = dict(stock or {})
        self.working = dict(working or {})
        self.orders = []
        self.rejected = set()
        self.actual_limit = shop.POST_PRODUCE_LIMIT
        for name in ('goto_postmanage', 'post_manage_mode', 'post_close', 'post_manage_swipe'):
            setattr(shop, name, Mock())
        shop.get_warehouse_counts = self.read_stock
        shop.post_check = self.check_post
        shop.post_produce = self.produce

    def read_stock(self):
        self.shop.warehouse_counts = dict(self.stock)
        if isinstance(self.shop, IslandTeahouse):
            self.shop.fresh_honey = self.stock.get('fresh_honey', 0)
        return self.shop.warehouse_counts

    def check_post(self, post_id, time_var_name):
        shop = self.shop
        if post_id in self.working:
            product, number = self.working[post_id]
            shop.posts[post_id]['status'] = 'working'
            shop.post_check_meal[product] = shop.post_check_meal.get(product, 0) + number
            setattr(shop, time_var_name, NOW + timedelta(hours=2))
        else:
            shop.posts[post_id]['status'] = 'idle'

    def produce(self, post_id, product, number, time_var_name, product2=None):
        if product in self.rejected:
            return 0
        number = min(number, self.actual_limit)
        self.orders.append((product, number, product2))
        self.shop.posts[post_id]['status'] = 'working'
        self.shop.deduct_materials(product, number)
        setattr(self.shop, time_var_name, NOW + timedelta(hours=1))
        return number

    def run(self):
        with patch('module.island.island_shop_base.current_time', return_value=NOW):
            self.shop.run()


class IslandShopProductionTests(unittest.TestCase):
    def setUp(self):
        self.log_patch = patch('module.island.island_shop_base.logger')
        self.log_patch.start()
        self.addCleanup(self.log_patch.stop)

    def test_restaurant_replenishes_material_consumed_by_meal(self):
        ui = ShopUI(IslandRestaurant, [('hearty_meal', 7), ('tofu', 10)],
                    {'tofu': 10, 'omurice': 10})
        ui.run()
        self.assertEqual(ui.orders, [('hearty_meal', 7, None), ('tofu', 7, None)])
        self.assertEqual(ui.shop.warehouse_counts['tofu'], 3)

    def test_teahouse_replenishes_material_consumed_by_meal(self):
        ui = ShopUI(IslandTeahouse, [('floral_fruity', 7), ('apple_juice', 10)],
                    {'lavender_tea': 10, 'apple_juice': 10})
        ui.run()
        self.assertEqual(ui.orders, [('floral_fruity', 7, None), ('apple_juice', 7, None)])
        self.assertEqual(ui.shop.warehouse_counts['apple_juice'], 3)

    def test_teahouse_consumes_material_at_target_and_replenishes_it(self):
        ui = ShopUI(
            IslandTeahouse,
            [('strawberry_lemon', 14), ('sunny_honey', 14)],
            {
                'strawberry_lemon': 14,
                'sunny_honey': 7,
                'honey_lemon': 0,
                'fresh_honey': 108,
            },
        )

        ui.run()
        self.assertEqual(ui.orders, [
            ('strawberry_lemon', 7, None),
            ('honey_lemon', 7, None),
        ])
        self.assertEqual(ui.shop.to_post_products, {'sunny_honey': 7})

        # 模拟两个原料岗位收获完成，下一轮应能制作剩余 7 个阳光蜜水。
        ui.stock['strawberry_lemon'] += 7
        ui.stock['honey_lemon'] += 7
        ui.orders.clear()
        ui.run()
        self.assertEqual(ui.orders, [('sunny_honey', 7, None)])

    def test_teahouse_protects_material_below_target(self):
        ui = ShopUI(
            IslandTeahouse,
            [('strawberry_lemon', 14), ('sunny_honey', 14)],
            {
                'strawberry_lemon': 10,
                'sunny_honey': 7,
                'honey_lemon': 7,
                'fresh_honey': 108,
            },
        )

        ui.run()
        self.assertEqual(ui.orders, [('strawberry_lemon', 4, None)])
        self.assertEqual(len(ui.shop.get_idle_posts()), 1)

    def test_all_meal_materials_respect_target_boundary(self):
        shop_classes = (
            IslandRestaurant,
            IslandTeahouse,
            IslandGrill,
            IslandJuuEatery,
            IslandJuuCoffee,
        )
        for shop_class in shop_classes:
            ui = ShopUI(shop_class)
            shop = ui.shop
            for meal, composition in shop.meal_compositions.items():
                materials = composition['required']
                quantity_per = composition.get('quantity_per', 1)
                with self.subTest(shop=shop_class.__name__, meal=meal):
                    target = 7
                    shop.warehouse_counts = {material: target for material in materials}
                    shop._reserved_targets = {material: target for material in materials}
                    self.assertEqual(
                        shop.get_max_producible(meal, target),
                        target // quantity_per,
                    )

                    shop.warehouse_counts = {
                        material: target - 1 for material in materials
                    }
                    self.assertEqual(shop.get_max_producible(meal, target), 0)

    def test_restaurant_replenishes_special_material_after_deduction(self):
        ui = ShopUI(IslandRestaurant, [('tofu_meat', 3), ('tofu', 10)], {'tofu': 10})
        ui.run()
        self.assertEqual(ui.orders, [('tofu_meat', 3, None), ('tofu', 6, None)])

    def test_business_demand_precedes_seasonal_priority(self):
        cases = [
            (IslandRestaurant, 'tofu', 'double_bamboo_shoots', 'spring'),
            (IslandRestaurant, 'tofu', 'matsutake_chicken_soup', 'autumn'),
            (IslandTeahouse, 'apple_juice', 'spring_flower_tea', 'spring'),
            (IslandTeahouse, 'apple_juice', 'chrysanthemum_tea', 'autumn'),
        ]
        for cls, basic, priority, season in cases:
            with self.subTest(shop=cls.__name__, season=season):
                ui = ShopUI(cls, [(basic, 3)], seasonal=True, season=season)
                ui.run()
                # 营业槽位先占岗，季节优先只用剩下的空岗。
                self.assertEqual(ui.orders, [(basic, 3, None), (priority, 7, None)])

    def test_restaurant_seasonal_extra_batch_preserves_quantity_rule(self):
        ui = ShopUI(IslandRestaurant, [('double_bamboo_shoots', 3)], seasonal=True)
        ui.run()
        # 营业目标 3 先补齐，剩余空岗再补季节额外一批 7；总量与旧顺序一致。
        self.assertEqual(ui.orders, [('double_bamboo_shoots', 3, None),
                                     ('double_bamboo_shoots', 7, None)])

    def test_teahouse_seasonal_batch_counts_toward_base_target(self):
        ui = ShopUI(IslandTeahouse, [('spring_flower_tea', 7), ('apple_juice', 3)],
                    seasonal=True)
        ui.run()
        self.assertEqual(ui.orders, [('spring_flower_tea', 7, None), ('apple_juice', 3, None)])

    def test_partial_seasonal_order_tracks_actual_quantity(self):
        ui = ShopUI(IslandTeahouse, [('spring_flower_tea', 10)], seasonal=True,
                    working={'ISLAND_TEAHOUSE_POST1': ('spring_flower_tea', 4)})
        ui.actual_limit = 3
        ui.run()
        self.assertEqual(ui.orders, [('spring_flower_tea', 3, None)])
        self.assertEqual(ui.shop.to_post_products, {'spring_flower_tea': 3})
        self.assertNotIn('spring_flower_tea', ui.shop.warehouse_counts)

    def collect(self, ui):
        """按游戏结算下一轮库存：仓库扣料后的账 + 本轮已收获产量。"""
        stock = dict(ui.shop.warehouse_counts)
        for product, number, _ in ui.orders:
            stock[product] = stock.get(product, 0) + number
        ui.stock = stock
        ui.orders.clear()

    def test_autumn_teahouse_business_slots_do_not_starve_behind_seasonal_priority(self):
        """真实日志回归：营业槽位与套餐原料先补齐，季节优先不再抢空岗。"""
        ui = ShopUI(
            IslandTeahouse,
            [('floral_fruity', 6), ('lavender_tea', 6), ('fruit_paradise', 6),
             ('chrysanthemum_tea', 6), ('apple_juice', 270)],
            {'floral_fruity': 0, 'lavender_tea': 1, 'apple_juice': 0,
             'banana_mango': 530, 'strawberry_honey': 0, 'fruit_paradise': 0,
             'sunny_honey': 0, 'fresh_honey': 108},
            seasonal=True, season='autumn',
        )

        ui.run()
        # 花茶原料苹果汁为 0：先补花茶原料，而不是菊花茶额外批次。
        self.assertEqual(ui.orders, [('lavender_tea', 5, None), ('apple_juice', 6, None)])
        self.assertNotIn('chrysanthemum_tea', [product for product, _, _ in ui.orders])
        self.collect(ui)

        # 花茶开产并消耗两种原料；同一轮用剩余空岗补回薰衣草茶目标。
        ui.run()
        self.assertEqual(ui.orders, [('floral_fruity', 6, None), ('lavender_tea', 6, None)])
        self.collect(ui)

        # 前两槽满足后处理第 3 槽：先补草莓蜜沁原料，再用剩余空岗做第 4 槽营业目标。
        ui.run()
        self.assertEqual(ui.orders, [('strawberry_honey', 6, None),
                                     ('chrysanthemum_tea', 6, None)])
        self.collect(ui)

        # 第 3 槽成品与第 5 槽苹果汁继续按顺序开产；没有季节额外批次抢岗。
        ui.run()
        self.assertEqual(ui.orders, [('fruit_paradise', 6, None), ('apple_juice', 7, None)])

    # Add by MHY, 季节套餐扣掉营业原料后，剩余岗位应补回基础目标。
    def test_seasonal_batch_replenishes_consumed_business_material(self):
        ui = ShopUI(IslandTeahouse, [('apple_juice', 270)],
                    {'apple_juice': 270, 'lavender_tea': 7})
        ui.shop.get_priority_production = lambda produced=None: {'floral_fruity': 7}
        ui.run()
        self.assertEqual(ui.orders, [('floral_fruity', 7, None), ('apple_juice', 7, None)])
        self.assertEqual(ui.shop.warehouse_counts['apple_juice'], 263)

    def test_duplicate_slots_keep_order_with_seasonal_priority(self):
        ui = ShopUI(IslandTeahouse, [('apple_juice', 2), ('apple_juice', 3)],
                    seasonal=True, season='autumn')
        ui.run()
        # 同名槽位仍按 2、1 逐轮推进，不被合并；两个岗位都归营业需求，季节批次不插队。
        self.assertEqual(ui.orders, [('apple_juice', 2, None), ('apple_juice', 1, None)])

    def test_restaurant_seasonal_priority_waits_for_large_business_gap(self):
        ui = ShopUI(IslandRestaurant, [('double_bamboo_shoots', 10)], seasonal=True)
        ui.run()
        # 营业目标 10 需要两个岗位各一批；没有剩余空岗时不再追加季节额外批次。
        self.assertEqual(ui.orders, [('double_bamboo_shoots', 7, None),
                                     ('double_bamboo_shoots', 3, None)])

    def test_seasonal_special_food_does_not_fill_remaining_posts(self):
        for cls in (IslandRestaurant, IslandTeahouse):
            with self.subTest(shop=cls.__name__):
                ui = ShopUI(cls, seasonal=True)
                ui.run()
                self.assertEqual(len(ui.orders), 1)
                self.assertEqual(len(ui.shop.get_idle_posts()), 1)

    def test_seasonal_then_away_cook_fills_remaining_post(self):
        for cls, away in ((IslandRestaurant, 'tofu'), (IslandTeahouse, 'apple_juice')):
            with self.subTest(shop=cls.__name__):
                ui = ShopUI(cls, seasonal=True, away=away)
                ui.run()
                self.assertEqual(len(ui.orders), 2)
                self.assertEqual(ui.orders[-1], (away, 7, None))

    def test_run_resets_unavailable_characters_and_products(self):
        for cls, product in ((IslandRestaurant, 'tofu'), (IslandTeahouse, 'apple_juice')):
            with self.subTest(shop=cls.__name__):
                ui = ShopUI(cls, [(product, 1)])
                ui.shop.chef_unavailable_products.add(product)
                ui.shop.unavailable_characters.add('WorkerJuu')
                ui.run()
                self.assertEqual(ui.orders, [(product, 1, None)])
                self.assertEqual(ui.shop.unavailable_characters, set())

    def test_repeated_run_counts_existing_work_once(self):
        ui = ShopUI(IslandRestaurant, [('tofu', 5)],
                    working={'ISLAND_RESTAURANT_POST1': ('tofu', 3)})
        ui.run()
        self.assertEqual(ui.orders, [('tofu', 2, None)])
        ui.orders.clear()
        ui.run()
        self.assertEqual(ui.orders, [('tofu', 2, None)])
        self.assertEqual(ui.shop.post_check_meal, {'tofu': 3})

    def test_existing_work_cannot_be_consumed_as_meal_material(self):
        ui = ShopUI(IslandRestaurant, [('hearty_meal', 7)], {'omurice': 7},
                    working={'ISLAND_RESTAURANT_POST1': ('tofu', 7)})
        ui.run()
        self.assertEqual(ui.orders, [])

    def test_strict_retry_preserves_all_previously_skipped_products(self):
        for cls, names in ((IslandRestaurant, ('tofu', 'omurice', 'salad')),
                           (IslandTeahouse, ('apple_juice', 'banana_mango', 'lavender_tea'))):
            with self.subTest(shop=cls.__name__):
                ui = ShopUI(cls, [(name, 1) for name in names])
                schedule = ui.shop.schedule_production
                attempts = Counter()

                def stalled_schedule():
                    # 模拟排产无进展且未标记角色不可用，触发严格扫描的兜底路径。
                    product = next(iter(ui.shop.to_post_products))
                    attempts[product] += 1
                    if product == names[-1]:
                        schedule()

                ui.shop.schedule_production = stalled_schedule
                ui.run()
                self.assertEqual(ui.orders, [(names[-1], 1, None)])
                self.assertEqual(attempts[names[0]], 3)
                self.assertEqual(attempts[names[1]], 2)

    def test_other_shops_keep_base_then_away_cook_and_delay(self):
        for cls, product in ((IslandGrill, 'roasted_skewer'),
                             (IslandJuuCoffee, 'iced_coffee'),
                             (IslandJuuEatery, 'apple_pie')):
            with self.subTest(shop=cls.__name__):
                ui = ShopUI(cls, [(product, 3)], away=product)
                ui.run()
                self.assertEqual(ui.orders, [(product, 3, None), (product, 7, None)])
                self.assertEqual(ui.shop.config.task_delay.call_args.kwargs['target'],
                                 [NOW + timedelta(hours=1), NOW + timedelta(hours=1),
                                  NOW + timedelta(hours=6)])

    def test_full_posts_skip_warehouse_and_preserve_delay(self):
        ui = ShopUI(IslandRestaurant, working={
            'ISLAND_RESTAURANT_POST1': ('tofu', 7),
            'ISLAND_RESTAURANT_POST2': ('omurice', 7),
        })
        ui.shop.get_warehouse_counts = Mock(side_effect=AssertionError('满岗不应访问仓库'))
        ui.run()
        self.assertEqual(ui.orders, [])
        self.assertEqual(ui.shop.config.task_delay.call_args.kwargs['target'],
                         [NOW + timedelta(hours=2), NOW + timedelta(hours=2),
                          NOW + timedelta(hours=6)])

    def test_island_error_still_raises_after_setting_delay(self):
        ui = ShopUI(IslandTeahouse)
        ui.shop.goto_postmanage.side_effect = lambda: setattr(ui.shop, 'island_error', True)
        with self.assertRaises(GameBugError):
            ui.run()
        ui.shop.config.task_delay.assert_called_once()


class TeahouseSeasonalSelectionTests(unittest.TestCase):
    """固定坐标季节饮品只在配置季节生效；错误季节的手填项走模板搜索。"""

    def test_fixed_coordinate_drink_is_only_armed_in_its_season(self):
        cases = (
            ('spring', 'spring_flower_tea', FIXED_SELECT_SPRING_FLOWER_TEA),
            ('summer', 'watermelon_juice', FIXED_SELECT_SPRING_FLOWER_TEA),
            ('autumn', 'chrysanthemum_tea', FIXED_SELECT_CHRYSANTHEMUM_TEA),
            ('winter', None, None),
        )
        for season, expected, fixed in cases:
            with self.subTest(season=season):
                drink = ShopUI(IslandTeahouse, seasonal=True, season=season).shop.seasonal_high_priority_drink
                self.assertEqual(drink['name'] if drink else None, expected)
                if drink:
                    self.assertIs(drink['selection'], fixed)

    def make_shop(self, products, seasonal, season):
        """按真实配置键构造茶馆，让 setup_config 读到 Meal 槽位。"""
        config = SimpleNamespace(
            IslandTeahouse_ChefFilter='WorkerJuu',
            IslandTeahouse_Seasonal=seasonal,
            cross_get=Mock(return_value=season),
            task_delay=Mock(),
        )
        for index, (name, number) in enumerate(products, 1):
            setattr(config, f'IslandTeahouse_Meal{index}', name)
            setattr(config, f'IslandTeahouse_MealNumber{index}', number)

        def init_island(shop, config, device=None, task=None):
            shop.config = config
            shop.device = device
            shop.unavailable_characters = set()

        with patch.object(Island, '__init__', init_island), patch(
                'module.island.island_shop_base.get_global_season_config',
                side_effect=SeasonConfig,
        ):
            return IslandTeahouse(config)

    def test_off_season_configured_chrysanthemum_uses_template_search(self):
        for seasonal in (False, True):
            with self.subTest(seasonal=seasonal):
                shop = self.make_shop([('chrysanthemum_tea', 6)], seasonal, 'spring')
                if seasonal:
                    self.assertEqual(shop.seasonal_high_priority_drink['name'],
                                     'spring_flower_tea')
                else:
                    self.assertIsNone(shop.seasonal_high_priority_drink)
                # 春/冬错误季节手填菊花茶时走常规模板搜索，而不是秋季固定第二格。
                self.assertIs(shop.name_to_config['chrysanthemum_tea']['selection'],
                              SELECT_CHRYSANTHEMUM_TEA)
                self.assertIsNot(shop.name_to_config['chrysanthemum_tea']['selection'],
                                 FIXED_SELECT_CHRYSANTHEMUM_TEA)


if __name__ == '__main__':
    unittest.main()
