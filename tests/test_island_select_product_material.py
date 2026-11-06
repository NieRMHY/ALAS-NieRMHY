"""用假 UI 验证岗位材料补货：买不起时按页面单次需求派遣或跳过，并关闭残留的购买弹窗。"""

import unittest
from unittest.mock import Mock, patch

from module.island.island import (
    ISLAND_SELECT_PRODUCT_CHECK,
    ISLAND_SHOP_CONFIRM,
    ISLAND_SHOPPING_CHECK,
    ISLAND_SHOPPING_CLOSE,
    MATERIAL_INSUFFICIENT,
    MATERIAL_READY,
    MATERIAL_RESTOCKED,
    Island,
)


SHOP_CHECK = object()
ITEM_BUTTON = object()


def make_island():
    with patch.object(Island, '__init__', lambda self: None):
        island = Island()
    island.device = Mock()
    island.interval_clear = Mock()
    island.loop = Mock(side_effect=lambda **kwargs: iter(range(30)))
    return island


class FakeTimer:
    """不依赖真实时间：启动后第一次 reached() 即视为到期。"""

    def __init__(self, *args, **kwargs):
        self._started = False

    def start(self):
        self._started = True
        return self

    def started(self):
        return self._started

    def reached(self):
        return True

    def reset(self):
        self._started = True
        return self


class PlanSelectProductMaterialTests(unittest.TestCase):
    plan = staticmethod(Island.plan_select_product_material)

    def test_target_reached_needs_no_purchase(self):
        self.assertEqual(self.plan(99, 99, 9), (MATERIAL_READY, 0))

    def test_first_attempt_tops_up_to_target(self):
        self.assertEqual(self.plan(35, 99, 9), ('buy', 64))

    def test_failed_top_up_plants_when_one_order_is_covered(self):
        self.assertEqual(self.plan(35, 99, 9, failed_quantity=64), (MATERIAL_READY, 0))

    def test_failed_top_up_retries_only_page_shortfall(self):
        self.assertEqual(self.plan(5, 99, 9, failed_quantity=94), ('buy', 4))

    def test_failed_page_shortfall_skips_post(self):
        self.assertEqual(self.plan(5, 99, 9, failed_quantity=4), (MATERIAL_INSUFFICIENT, 0))
        self.assertEqual(self.plan(0, 99, 9, failed_quantity=9), (MATERIAL_INSUFFICIENT, 0))

    def test_unknown_page_requirement_uses_existing_stock(self):
        self.assertEqual(self.plan(35, 99, 0, failed_quantity=64), (MATERIAL_READY, 0))
        self.assertEqual(self.plan(0, 99, 0, failed_quantity=99), (MATERIAL_INSUFFICIENT, 0))

    def test_parse_page_requirement(self):
        parse = Island.parse_select_product_material_required
        self.assertEqual(parse('35/9'), 9)
        self.assertEqual(parse('110/(2+6)'), 8)
        self.assertEqual(parse('35'), 0)


class EnsureSelectProductMaterialTests(unittest.TestCase):
    def setUp(self):
        logger_patch = patch('module.island.island.logger')
        logger_patch.start()
        self.addCleanup(logger_patch.stop)
        self.island = make_island()
        self.stock = 35
        self.island.ocr_select_product_material_detail = Mock(
            side_effect=lambda expected_quantity: (self.stock, f'{self.stock}/9'))
        self.island.goto_shop_from_select_product = Mock(return_value=True)
        self.island.back_to_select_product_after_shop = Mock(return_value=True)
        self.buys = []

        def buy(quantity, **kwargs):
            self.buys.append(quantity)
            return False

        self.island.buy_shop_item = Mock(side_effect=buy)

    def ensure(self):
        return self.island.ensure_select_product_material(
            item_button=ITEM_BUTTON, required_quantity=99, shop_check=SHOP_CHECK, item_name='corn')

    def test_unaffordable_top_up_still_plants_with_owned_seeds(self):
        # 真实日志：35/9，补买 64 个失败后应直接种，而不是反复进商店
        self.assertEqual(self.ensure(), MATERIAL_RESTOCKED)
        self.island.back_to_select_product_after_shop.assert_called_once()
        self.assertEqual(self.ensure(), MATERIAL_READY)
        self.assertEqual(self.buys, [64])

    def test_short_seeds_retry_shortfall_then_skip(self):
        self.stock = 5
        self.assertEqual(self.ensure(), MATERIAL_RESTOCKED)
        self.assertEqual(self.ensure(), MATERIAL_RESTOCKED)
        self.assertEqual(self.ensure(), MATERIAL_INSUFFICIENT)
        self.assertEqual(self.buys, [94, 4])

    def test_successful_purchase_keeps_old_flow(self):
        self.island.buy_shop_item = Mock(return_value=True)
        self.assertEqual(self.ensure(), MATERIAL_RESTOCKED)
        self.stock = 99
        self.assertEqual(self.ensure(), MATERIAL_READY)


class ShoppingPopupTests(unittest.TestCase):
    def setUp(self):
        for target in ('module.island.island.logger', 'module.island.island.Timer'):
            patcher = patch(target, FakeTimer) if target.endswith('Timer') else patch(target)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.island = make_island()
        self.popup_open = True
        self.clicks = []

        def click(button):
            self.clicks.append(button)
            if button is ISLAND_SHOPPING_CLOSE:
                self.popup_open = False

        self.island.device.click = click

    def appear(self, button, **kwargs):
        if button is ISLAND_SHOPPING_CHECK:
            return self.popup_open
        if button is ISLAND_SHOP_CONFIRM:
            return self.popup_open
        if button is SHOP_CHECK:
            return not self.popup_open
        return False

    def test_popup_that_stays_open_is_closed_and_reported_as_failure(self):
        self.island.appear = self.appear
        self.island.appear_then_click = lambda button, **kwargs: (
            self.island.device.click(button) or True) if self.appear(button) else False
        self.island.set_buy_number = Mock()

        self.assertFalse(self.island.buy_shop_item(ITEM_BUTTON, 64, SHOP_CHECK, item_name='corn'))
        self.assertEqual(self.clicks.count(ISLAND_SHOP_CONFIRM), 1)
        self.assertIn(ISLAND_SHOPPING_CLOSE, self.clicks)
        self.assertFalse(self.popup_open)

    def test_back_to_select_product_closes_leftover_popup(self):
        def appear(button, **kwargs):
            if button is ISLAND_SELECT_PRODUCT_CHECK:
                return not self.popup_open
            return button is ISLAND_SHOPPING_CHECK and self.popup_open

        self.island.appear = appear
        self.island.appear_then_click = Mock(return_value=False)

        self.assertTrue(self.island.back_to_select_product_after_shop())
        self.assertEqual(self.clicks, [ISLAND_SHOPPING_CLOSE])


if __name__ == '__main__':
    unittest.main()
