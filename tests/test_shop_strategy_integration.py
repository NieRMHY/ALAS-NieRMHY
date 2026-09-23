"""高级商店策略与现有购买选择器的无设备回归测试。"""

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from module.private_quarters.shop import PQShop
from module.os_shop.shop import OSShop
from module.shop.base import ShopBase
from module.shop.shop_general import GeneralShop_250814
from module.shop.shop_guild import GuildShop_250814
from module.shop.shop_merit import MeritShop_250814
from module.shop_event.shop_event import EventShop


def make_item(**overrides):
    """构造与通用商店选择器兼容的商品替身。"""
    values = {
        'name': 'Cube',
        'cost': 'Coins',
        'price': 100,
        'count': 1,
        'group': 'cube',
        'sub_genre': None,
        'tier': None,
        'is_valid': True,
        'area': (10, 20, 30, 40),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class StrategyShop(ShopBase):
    """只覆盖策略所需数据源，避免连接真实设备。"""

    def __init__(self, script, currency=1_000):
        self.config = SimpleNamespace(
            ShopAdvanced_Mode='advanced',
            ShopAdvanced_Script=script,
            task=SimpleNamespace(command='ShopFrequent'),
        )
        self._currency = currency


class TestShopStrategyIntegration(TestCase):
    """验证高级模式不会回退旧过滤器，且硬性资格先于脚本执行。"""

    def test_general_strategy_selects_script_priority_without_legacy_filter(self):
        shop = StrategyShop('''
return shop.plan {
    candidates = candidates:order_by("price", "asc"):take(2)
}
''')
        expensive = make_item(name='Expensive', price=500)
        cheap = make_item(name='Cheap', price=100, area=(40, 20, 60, 40))

        selected = shop.shop_get_item_to_buy([expensive, cheap])

        self.assertIs(cheap, selected)
        self.assertEqual(1, selected._shop_strategy_quantity)

    def test_general_strategy_error_skips_without_legacy_fallback(self):
        shop = StrategyShop('return os.execute("bad")')
        item = make_item()

        self.assertIsNone(shop.shop_get_item_to_buy([item]))

    def test_general_strategy_records_actual_purchase_for_session_limit(self):
        shop = StrategyShop('''
return shop.plan {
    max_spend = { Coins = 100 },
    candidates = candidates:take(1)
}
''')
        item = make_item(price=100)
        selected = shop.shop_get_item_to_buy([item])
        shop.shop_strategy_record_purchase(selected)

        refreshed = make_item(price=100)
        self.assertIsNone(shop.shop_get_item_to_buy([refreshed]))

    def test_private_quarters_strategy_uses_gem_balance_without_legacy_toggle(self):
        shop = object.__new__(PQShop)
        shop.config = SimpleNamespace(
            ShopAdvanced_Mode='advanced',
            ShopAdvanced_Script='return shop.plan { candidates = candidates:take(1) }',
            PrivateQuarters_BuyRoses=False,
            PrivateQuarters_BuyCake=False,
            task=SimpleNamespace(command='PrivateQuarters'),
        )
        shop._currency = 0
        shop.gems = 500
        cake = make_item(name='GiftCake', cost='Gems', price=210, sub_genre='cake')

        with patch('module.private_quarters.shop.logger'):
            selected = shop.shop_get_item_to_buy([cake])

        self.assertIs(cake, selected)

    def test_event_strategy_excludes_legacy_ur_stages(self):
        """高级活动策略只接收普通 PT 商品，避免旧 UR 阶段绕过会话预算。"""
        ordinary = make_item(name='Cube', cost='pt')
        ur_points = make_item(name='URpt', cost='pt')
        ur_ship = make_item(name='ShipUR', cost='URpt')

        self.assertEqual([ordinary], EventShop._advanced_strategy_candidates([
            ordinary, ur_points, ur_ship,
        ]))

    def test_event_strategy_records_only_pt_confirmed_purchase(self):
        """活动商店只有回读到精确 PT 消耗时才计入高级策略会话。"""
        shop = object.__new__(EventShop)
        shop.pt = 100
        shop._advanced_strategy_session = {
            'spent': {}, 'purchased': {}, 'inventory_purchased': {}, 'cap_usage': {},
        }
        item = make_item(cost='pt', price=10)
        item._shop_strategy_candidate_id = 'cube'
        item._shop_strategy_cost = 'pt'
        item._shop_strategy_cap_usage_keys = ()
        shop.event_shop_buy_item = lambda _item, amount: setattr(shop, 'pt', 100 - amount * 10)
        shop.get_current_pts = lambda: None

        self.assertTrue(shop._advanced_strategy_buy_item(item, 2))
        self.assertEqual({'pt': 20}, shop._advanced_strategy_session['spent'])
        self.assertEqual({'cube': 2}, shop._advanced_strategy_session['purchased'])

        shop.pt = 80
        shop.event_shop_buy_item = lambda _item, amount: None
        self.assertFalse(shop._advanced_strategy_buy_item(item, 1))
        self.assertEqual({'pt': 20}, shop._advanced_strategy_session['spent'])

    def test_opsi_strategy_quantity_bypasses_legacy_maximum_heuristic(self):
        """大世界高级计划的数量不能被旧的接近最大值逻辑放大。"""
        shop = SimpleNamespace(
            device=SimpleNamespace(image=object()),
            get_currency_coins=lambda item: 600,
            _opsi_shop_strategy_enabled=lambda: True,
            interval_clear=lambda *_: None,
            ui_ensure_index=Mock(),
        )
        item = make_item(cost='YellowCoins', price=10, count=100)
        item._shop_strategy_quantity = 60

        with patch('module.os_shop.shop.OCR_SHOP_AMOUNT') as amount_ocr:
            amount_ocr.ocr.return_value = 100
            result = OSShop.shop_buy_amount_handler(shop, item)

        self.assertTrue(result)
        self.assertEqual(60, item._shop_strategy_executed_quantity)
        self.assertEqual(60, shop.ui_ensure_index.call_args.args[0])

    def test_opsi_strategy_is_scoped_to_port_purchase_flow(self):
        """OpsiShop 高级策略不能泄漏到地图事件中的明石商店。"""
        from module.os_shop.selector import Selector

        selector = object.__new__(Selector)
        selector.config = SimpleNamespace(
            task=SimpleNamespace(command='OpsiShop'),
            ShopAdvanced_Mode='advanced',
        )

        self.assertFalse(selector._opsi_shop_strategy_enabled())
        with selector.opsi_shop_strategy_scope():
            self.assertTrue(selector._opsi_shop_strategy_enabled())
        self.assertFalse(selector._opsi_shop_strategy_enabled())

    def test_general_advanced_mode_skips_refresh_and_overflow_purchase(self):
        """高级模式的预算不能被旧刷新或金币溢出购买绕过。"""
        shop = object.__new__(GeneralShop_250814)
        shop.config = SimpleNamespace(GeneralShop_Refresh=True)
        shop.shop_filter = 'Cube'
        shop.shop_strategy_enabled = lambda: True
        shop._validate_config_values = Mock()
        shop.shop_buy = Mock(return_value=True)
        shop.shop_refresh = Mock(return_value=True)
        shop._meowfficer_overflow_buy = Mock()

        shop.run()

        shop.shop_refresh.assert_not_called()
        shop._meowfficer_overflow_buy.assert_not_called()

    def test_other_advanced_shops_skip_legacy_refresh(self):
        """舰队和功勋商店的刷新同样不能绕过高级策略预算。"""
        for cls, field in ((GuildShop_250814, 'GuildShop_Refresh'), (MeritShop_250814, 'MeritShop_Refresh')):
            with self.subTest(cls=cls.__name__):
                shop = object.__new__(cls)
                shop.config = SimpleNamespace(**{field: True, 'MeritShop_BuyUnobtainedShip': False})
                shop.shop_filter = 'Cube'
                shop.shop_strategy_enabled = lambda: True
                shop.shop_buy = Mock(return_value=True)
                shop.shop_refresh = Mock(return_value=True)

                shop.run()

                shop.shop_refresh.assert_not_called()
