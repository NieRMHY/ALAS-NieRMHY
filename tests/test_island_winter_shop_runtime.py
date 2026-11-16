"""冬季店铺运行时：真实 IslandShopBase.run 的有限产能、账本与营业线。

这些用例只新增测试文件，不碰生产代码：用 tests.test_island_shop_production.ShopUI
模拟岗位/仓库/下单，保留 IslandShopBase.run 的真实排产、冬季任务账本与常驻分支。
ShopUI 的 cross_get 原本固定返回 season，冬季配置需要按键取值；本文件局部替换，
并把 island_winter_meals.STATE_DIR 指到临时目录，避免写真实 config/island。
"""

import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tests.test_island_shop_production import NOW, ShopUI

from module.island import island_winter_meals
from module.island import island_shop_base
from module.island.island_shop_base import IslandShopBase
from module.island.island_grill import IslandGrill
from module.island.island_juu_coffee import IslandJuuCoffee
from module.island.island_juu_eatery import IslandJuuEatery


SEASON_GROUP = 'IslandSeasonPlan.IslandSeasonPlan'
DEFAULT_WINTER_VALUES = {
    'IslandPlan.IslandPlan.Season': 'winter',
    f'{SEASON_GROUP}.WinterTaskEnabled': True,
    f'{SEASON_GROUP}.MealBuffer': 0,
    'IslandBusiness.IslandBusiness.ShopLevel': 'diamond',
    # 默认不激活三项餐品任务；需要的用例单独打开。
    f'{SEASON_GROUP}.Need_rice_mango': 0,
    f'{SEASON_GROUP}.Need_strawberry_charlotte': 0,
    f'{SEASON_GROUP}.Need_chicken_potato': 0,
}


def winter_values(**overrides):
    """冬季配置值：Need_/Done_ 等短名自动补上 IslandSeasonPlan 前缀。"""
    values = dict(DEFAULT_WINTER_VALUES)
    for key, value in overrides.items():
        if key.startswith('Island'):
            values[key] = value
        else:
            values[f'{SEASON_GROUP}.{key}'] = value
    return values


class WinterShopUI(ShopUI):
    """ShopUI 的冬季补丁层：按键取配置、严格 warehouse_observations、芝士库存。"""

    def __init__(self, shop_class, products=(), stock=None, *, away=None,
                 working=None, post_number=2, config=None):
        super().__init__(shop_class, products, stock, seasonal=False,
                         season='winter', away=away, working=working)
        self.values = dict(DEFAULT_WINTER_VALUES)
        self.values.update(config or {})
        self.shop.config.cross_get = self._cross_get
        setattr(self.shop.config, self.shop.config_post_number, post_number)
        for index in range(len(self.shop.posts) + 1, post_number + 1):
            post_id = f'ISLAND_{self.shop.shop_type.upper()}_POST{index}'
            self.shop.posts[post_id] = {'status': 'none', 'button': Mock()}
        self.actual_zero = False

    def _cross_get(self, key, default=None):
        return self.values.get(key, default)

    def read_stock(self):
        shop = self.shop
        observations = {}
        counts = {}
        for dish in shop.shop_items:
            value = self.stock.get(dish['name'], 0)
            observations[dish['name']] = value
            counts[dish['name']] = 0 if value is None else value
        for name, value in self.stock.items():
            if name not in observations:
                observations[name] = value
                counts[name] = 0 if value is None else value
        # 芝士/牛奶是跨店原料，仓库里读不到时按已知 0 处理；未知必须显式传 None。
        for name in ('cheese', 'milk'):
            observations.setdefault(name, 0)
            counts.setdefault(name, 0)
        shop.warehouse_observations = observations
        shop.warehouse_counts = counts
        if hasattr(shop, 'cheese_stock'):
            cheese = observations.get('cheese', 0)
            shop.cheese_stock = 0 if cheese is None else cheese
        if hasattr(shop, 'milk_stock'):
            shop.milk_stock = counts.get('milk', 0)
        return counts

    def check_post(self, post_id, time_var_name):
        if post_id in self.working:
            product, number = self.working[post_id]
            if product is None or number <= 0 or product not in self.shop.name_to_config:
                self.shop.posts[post_id]['status'] = 'working'
                setattr(self.shop, time_var_name, NOW + timedelta(hours=2))
                self.shop._winter_queue_unknown = True
                return
        return super().check_post(post_id, time_var_name)

    def produce(self, post_id, product, number, time_var_name, product2=None):
        if self.actual_zero:
            self.orders.append((product, number, product2))
            self.shop.posts[post_id]['status'] = 'working'
            return 0
        return super().produce(post_id, product, number, time_var_name, product2)


class IslandWinterShopRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.logger_patch = patch('module.island.island_shop_base.logger')
        self.logger_patch.start()
        self.addCleanup(self.logger_patch.stop)

        self.state_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.state_dir.cleanup)
        self.state_patch = patch.object(island_winter_meals, 'STATE_DIR',
                                        self.state_dir.name)
        self.state_patch.start()
        self.addCleanup(self.state_patch.stop)

        self.now_patch = patch.object(island_winter_meals, 'now', return_value=NOW)
        self.now_patch.start()
        self.addCleanup(self.now_patch.stop)

    def shop(self, shop_class, products=(), stock=None, **kwargs):
        return WinterShopUI(shop_class, products, stock, **kwargs)

    def ledger(self):
        paths = sorted(Path(self.state_dir.name).glob('winter_meals_*.json'))
        self.assertEqual(len(paths), 1, f'应有且只有一个冬季账本: {paths}')
        return json.loads(paths[0].read_text(encoding='utf-8'))

    def test_ordinary_orders_precede_finite_then_away(self):
        ui = self.shop(
            IslandJuuEatery,
            [('apple_pie', 3)],
            {'apple_pie': 0},
            away='seafood_rice',
            post_number=3,
            config=winter_values(Need_rice_mango=1),
        )

        ui.run()

        self.assertEqual(ui.orders, [
            ('apple_pie', 3, None),
            ('rice_mango', 1, None),
            ('seafood_rice', 7, None),
        ])

    def test_duplicate_slots_keep_order_and_restore_in_finally(self):
        ui = self.shop(
            IslandJuuEatery,
            [('apple_pie', 2), ('apple_pie', 3)],
            {'apple_pie': 0},
            post_number=2,
        )
        original = ui.shop.post_products

        ui.run()

        # 第一个槽位补 2，第二个同名槽位只补剩余 1，说明重复槽位没有被合并。
        self.assertEqual(ui.orders, [('apple_pie', 2, None), ('apple_pie', 1, None)])
        self.assertEqual(ui.shop.post_products, [('apple_pie', 2), ('apple_pie', 3)])
        self.assertIs(ui.shop.post_products, original)

        # 中途异常也必须恢复原槽位列表，不能把冬季叠加留在实例上。
        failed = self.shop(
            IslandJuuEatery,
            [('apple_pie', 2), ('apple_pie', 3)],
            {'apple_pie': 0},
            post_number=2,
        )
        failed_original = failed.shop.post_products
        failed.shop.goto_postmanage.side_effect = RuntimeError('boom')
        with self.assertRaises(RuntimeError):
            failed.run()
        self.assertEqual(failed.shop.post_products, [('apple_pie', 2), ('apple_pie', 3)])
        self.assertIs(failed.shop.post_products, failed_original)

    def test_unknown_stock_pauses_finite_production(self):
        ui = self.shop(
            IslandJuuEatery,
            stock={'rice_mango': None},
            post_number=1,
            config=winter_values(Need_rice_mango=1),
        )

        ui.run()

        self.assertEqual(ui.orders, [])
        self.assertIsNone(self.ledger()['totals']['rice_mango'])

    def test_unknown_queue_pauses_finite_production(self):
        ui = self.shop(
            IslandJuuEatery,
            stock={'rice_mango': 0},
            working={'ISLAND_JUU_EATERY_POST1': (None, 0)},
            post_number=2,
            config=winter_values(Need_rice_mango=1),
        )

        ui.run()

        self.assertEqual(ui.orders, [])
        self.assertTrue(ui.shop._winter_queue_unknown)

    def test_known_zero_allows_finite_production(self):
        ui = self.shop(
            IslandJuuEatery,
            stock={'rice_mango': 0},
            post_number=1,
            config=winter_values(Need_rice_mango=1),
        )

        ui.run()

        self.assertEqual(ui.orders, [('rice_mango', 1, None)])
        self.assertEqual(self.ledger()['totals']['rice_mango'], 1)

    def test_wip_counts_against_finite_target(self):
        ui = self.shop(
            IslandJuuEatery,
            stock={'rice_mango': 0},
            working={'ISLAND_JUU_EATERY_POST1': ('rice_mango', 1)},
            post_number=2,
            config=winter_values(Need_rice_mango=1),
        )

        ui.run()

        self.assertEqual(ui.orders, [])
        self.assertEqual(self.ledger()['totals']['rice_mango'], 1)

    def test_partial_actual_charges_spent_by_actual(self):
        ui = self.shop(
            IslandJuuEatery,
            stock={'rice_mango': 0},
            post_number=1,
            config=winter_values(Need_rice_mango=7),
        )
        ui.actual_limit = 3

        ui.run()

        self.assertEqual(ui.orders, [('rice_mango', 3, None)])
        # 芒果糯米饭 20 分钟/个，实际只生产 3 个，不能按请求的 7 个记工时。
        self.assertEqual(self.ledger()['spent']['juu_eatery'], 60)

    def test_unknown_actual_keeps_reservation_without_redispatch(self):
        ui = self.shop(
            IslandJuuEatery,
            stock={'rice_mango': 0},
            post_number=1,
            config=winter_values(Need_rice_mango=7),
        )
        ui.actual_zero = True

        ui.run()

        self.assertEqual(ui.orders, [('rice_mango', 7, None)])
        self.assertEqual(self.ledger()['spent']['juu_eatery'], 140)
        self.assertIsNone(self.ledger()['totals']['rice_mango'])

        # 岗位仍在工作但数量读不到：下一轮应保留预占，不再派同一批。
        ui.orders.clear()
        ui.working = {'ISLAND_JUU_EATERY_POST1': (None, 0)}
        ui.run()

        self.assertEqual(ui.orders, [])
        self.assertEqual(self.ledger()['spent']['juu_eatery'], 140)

    def test_unknown_charlotte_output_pauses_cross_shop_cheese(self):
        config = winter_values(Need_strawberry_charlotte=7)
        eatery = self.shop(
            IslandJuuEatery, stock={'strawberry_charlotte': 0, 'cheese': 14},
            post_number=1, config=config)
        eatery.actual_zero = True
        eatery.run()
        self.assertEqual(eatery.orders, [('strawberry_charlotte', 7, None)])
        self.assertIsNone(self.ledger()['totals']['strawberry_charlotte'])

        coffee = self.shop(IslandJuuCoffee, stock={'cheese': 0},
                           post_number=1, config=config)
        coffee.run()
        self.assertEqual(coffee.orders, [])

    def test_done_or_zero_need_restores_away_cook(self):
        cases = (
            ('done', winter_values(Need_strawberry_charlotte=25,
                                   Done_strawberry_charlotte=True)),
            ('need-zero', winter_values(Need_strawberry_charlotte=0)),
        )
        for label, config in cases:
            with self.subTest(case=label):
                ui = self.shop(
                    IslandJuuEatery,
                    stock={'cheese': 100},
                    away='strawberry_charlotte',
                    post_number=1,
                    config=config,
                )

                ui.run()

                self.assertEqual(ui.orders, [('strawberry_charlotte', 7, None)])

    def test_active_tasks_gate_reachable_away_combos(self):
        cases = (
            ('succulently_sweet', IslandJuuEatery,
             {'rice_mango': 7, 'corn_cup': 7},
             winter_values(Need_rice_mango=1)),
            ('berry_orange', IslandJuuEatery,
             {'strawberry_charlotte': 7, 'orange_pie': 7},
             winter_values(Need_strawberry_charlotte=1)),
            ('wake_up_call', IslandJuuCoffee,
             {'cheese': 7, 'iced_coffee': 7},
             winter_values(Need_strawberry_charlotte=1)),
            ('carnival', IslandGrill,
             {'roasted_skewer': 7, 'chicken_potato': 7},
             winter_values(Need_chicken_potato=1)),
        )
        for away, shop_class, stock, config in cases:
            with self.subTest(away=away):
                ui = self.shop(shop_class, stock=stock, away=away,
                               post_number=1, config=config)

                ui.run()

                # 这些套餐的原料链命中活跃冬季任务（含芝士 -> 夏洛特），应暂停常驻。
                self.assertEqual(ui.orders, [])

    def test_finite_order_full_stops_next_round(self):
        ui = self.shop(
            IslandJuuEatery,
            stock={'rice_mango': 0},
            post_number=1,
            config=winter_values(Need_rice_mango=7),
        )

        ui.run()
        self.assertEqual(ui.orders, [('rice_mango', 7, None)])

        # 模拟 7 个全部入库，下一轮目标已满，不再补单。
        ui.orders.clear()
        ui.stock['rice_mango'] = 7
        ui.run()

        self.assertEqual(ui.orders, [])
        self.assertEqual(self.ledger()['totals']['rice_mango'], 7)

    def test_large_meal_stock_target_does_not_eat_daily_budget(self):
        config = winter_values(Need_rice_mango=1)
        config['IslandJuuEatery.IslandJuuEatery.Meal1'] = 'seafood_rice'
        config['IslandJuuEatery.IslandJuuEatery.MealNumber1'] = 100
        ui = self.shop(
            IslandJuuEatery,
            stock={'seafood_rice': 100, 'rice_mango': 0},
            post_number=1,
            config=config,
        )

        ui.run()

        # MealNumber=100 是库存目标，不是每天都要重做 100 个；不能把日预算扣成 0。
        self.assertEqual(ui.orders, [('rice_mango', 1, None)])

    def test_spare_minutes_counts_one_shelf_round(self):
        values = winter_values()
        values['IslandJuuCoffee.IslandJuuCoffee.PostNumber'] = 1
        for slot in range(1, 5):
            values[f'IslandBusiness.IslandBusinessShop5.Product{slot}'] = 'cheese'
        config = SimpleNamespace(
            cross_get=lambda key, default=None: values.get(key, default))

        # 4 格 x 6 个芝士 x 40 分钟 = 960 分钟；一天一岗 1296 分钟，剩 336。
        # 大额 MealNumber 不参与这段，但货架这一轮必须保留。
        self.assertEqual(
            island_winter_meals.spare_minutes(config, {}, set(), 'juu_coffee'),
            24 * 60 * 0.9 - 24 * 40,
        )

    def test_daily_budget_accumulates_across_rounds(self):
        ui = self.shop(
            IslandJuuEatery,
            stock={'rice_mango': 0},
            post_number=1,
            config=winter_values(Need_rice_mango=7),
        )
        ui.actual_limit = 3

        ui.run()
        self.assertEqual(ui.orders, [('rice_mango', 3, None)])
        self.assertEqual(self.ledger()['spent']['juu_eatery'], 60)

        ui.orders.clear()
        ui.stock['rice_mango'] = 3
        ui.run()

        self.assertEqual(ui.orders, [('rice_mango', 3, None)])
        self.assertEqual(self.ledger()['spent']['juu_eatery'], 120)

    def test_cheese_keeps_business_reserve(self):
        cases = (
            (6, []),
            (8, [('strawberry_charlotte', 1, None)]),
        )
        for cheese, expected in cases:
            with self.subTest(cheese=cheese):
                config = winter_values(Need_strawberry_charlotte=1)
                config['IslandBusiness.IslandBusinessShop5.Product1'] = 'cheese'
                ui = self.shop(
                    IslandJuuEatery,
                    stock={'strawberry_charlotte': 0, 'cheese': cheese},
                    post_number=1,
                    config=config,
                )

                ui.run()

                self.assertEqual(ui.orders, expected)
                if expected:
                    self.assertEqual(self.ledger()['spent']['juu_eatery'], 35)

    def test_post_check_marks_only_unreadable_queue_unknown(self):
        ui = self.shop(IslandJuuEatery, stock={'rice_mango': 0}, post_number=1)
        shop = ui.shop
        shop.post_close = Mock()
        shop.post_open = Mock(return_value=True)
        shop.post_get_and_close = Mock()
        shop.device = Mock()
        shop.device.screenshot.return_value = object()
        shop.device.image = object()
        shop.device.sleep = Mock()
        shop.appear = Mock(side_effect=lambda button, **kwargs: button is island_shop_base.ISLAND_WORKING)

        class FakeDigit:
            def __init__(self, *args, **kwargs):
                self.last_valid = False

            def ocr(self, image):
                return 0

        class FakeDuration:
            def __init__(self, *args, **kwargs):
                pass

            def ocr(self, image):
                return timedelta(minutes=30)

        class KnownDigit:
            def __init__(self, *args, **kwargs):
                self.last_valid = True

            def ocr(self, image):
                return 7

        shop.post_product_check = Mock(return_value=None)
        with patch.object(island_shop_base, 'Digit', FakeDigit), \
                patch.object(island_shop_base, 'Duration', FakeDuration), \
                patch.object(island_shop_base, 'current_time', return_value=NOW):
            # ShopUI 的实例属性覆盖了假 UI 的巡检；这里显式走真实基类方法。
            IslandShopBase.post_check(shop, 'ISLAND_JUU_EATERY_POST1', 'time_eatery1')

        self.assertTrue(shop._winter_queue_unknown)
        self.assertEqual(shop.posts['ISLAND_JUU_EATERY_POST1']['status'], 'working')

        # 能读到商品和数量时不打未知标记，并正常记入在制库存。
        shop._winter_queue_unknown = False
        shop.post_check_meal = {}
        shop.post_product_check = Mock(return_value='rice_mango')
        with patch.object(island_shop_base, 'Digit', KnownDigit), \
                patch.object(island_shop_base, 'Duration', FakeDuration), \
                patch.object(island_shop_base, 'current_time', return_value=NOW):
            IslandShopBase.post_check(shop, 'ISLAND_JUU_EATERY_POST1', 'time_eatery1')

        self.assertFalse(shop._winter_queue_unknown)
        self.assertEqual(shop.post_check_meal, {'rice_mango': 7})


class IslandBatchConfirmationTests(unittest.TestCase):
    def form(self, gray):
        shop = ShopUI(IslandJuuEatery).shop
        shop.device = Mock()
        shop.loop = Mock(return_value=iter([None]))
        shop.appear_then_click = Mock(return_value=False)
        shop.appear = Mock(side_effect=lambda button, **kwargs:
                           button is island_shop_base.ISLAND_SELECT_PRODUCT_CHECK)
        shop.post_open = Mock()
        shop.select_product = Mock(return_value=True)
        shop.produce_check = Mock(side_effect=gray)
        shop.post_add_one = Mock()
        shop.back_to_postmanage_from_dispatch = Mock()
        shop.wait_until_appear = Mock()
        shop.deduct_materials = Mock()
        shop.special_food = 'strawberry_charlotte'
        shop.posts['ISLAND_JUU_EATERY_POST1']['status'] = 'idle'
        return shop

    def test_gray_after_increment_returns_without_submitting(self):
        for gray, backup in (([False, True], None), ([True, False, True], 'rice_mango')):
            with self.subTest(backup=backup):
                shop = self.form(gray)
                actual = IslandShopBase.post_produce(
                    shop, 'ISLAND_JUU_EATERY_POST1', 'strawberry_charlotte', 7,
                    'time_eatery1', product2=backup)
                self.assertEqual(actual, 0)
                shop.post_add_one.assert_called_once_with(6)
                shop.back_to_postmanage_from_dispatch.assert_called_once()
                self.assertFalse(any(call.args[0] is island_shop_base.POST_ADD_ORDER
                                     for call in shop.device.click.call_args_list))
                self.assertEqual(shop.posts['ISLAND_JUU_EATERY_POST1']['status'], 'idle')

    def test_backup_deducts_actual_product_and_quantity(self):
        shop = self.form([True, False, False])
        with patch.object(island_shop_base, 'Digit') as digit, \
                patch.object(island_shop_base, 'Duration') as duration:
            digit.return_value.ocr.return_value = 3
            digit.return_value.last_valid = True
            duration.return_value.ocr.return_value = timedelta(minutes=60)
            actual = IslandShopBase.post_produce(
                shop, 'ISLAND_JUU_EATERY_POST1', 'strawberry_charlotte', 7,
                'time_eatery1', product2='rice_mango')
        self.assertEqual(actual, 3)
        shop.deduct_materials.assert_called_once_with('rice_mango', 3)
        self.assertEqual(shop.posts['ISLAND_JUU_EATERY_POST1']['status'], 'working')

    def test_unreadable_actual_output_marks_queue_unknown(self):
        shop = self.form([False, False])
        with patch.object(island_shop_base, 'Digit') as digit, \
                patch.object(island_shop_base, 'Duration') as duration:
            digit.return_value.ocr.return_value = 0
            digit.return_value.last_valid = False
            duration.return_value.ocr.return_value = timedelta(minutes=60)
            actual = IslandShopBase.post_produce(
                shop, 'ISLAND_JUU_EATERY_POST1', 'strawberry_charlotte', 7, 'time_eatery1')
        self.assertEqual(actual, 0)
        self.assertTrue(shop._winter_queue_unknown)
        self.assertEqual(shop.posts['ISLAND_JUU_EATERY_POST1']['status'], 'working')


if __name__ == '__main__':
    unittest.main()
