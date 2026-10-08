"""商店回归官源后的迁移、购买规则与保留功能验证。"""

import copy
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.config.config_updater import ConfigUpdater
from module.config.redirect_utils.shop import SHOP_TASKS, migrate_shop_options
from module.shop.shop_general import GeneralShop_250814
from module.shop_event.shop_event import EventShop


class ShopMigrationTests(unittest.TestCase):
    def test_advanced_tasks_are_paused_and_scripts_removed_without_changing_input(self):
        old = {task: {'Scheduler': {'Enable': True}, 'ShopAdvanced': {'Mode': 'advanced', 'Script': 'old'}}
               for task in SHOP_TASKS}
        original = copy.deepcopy(old)
        migrated, warnings = migrate_shop_options(old, old)
        self.assertEqual(old, original)
        self.assertEqual(len(warnings), len(SHOP_TASKS))
        for task in SHOP_TASKS:
            self.assertFalse(migrated[task]['Scheduler']['Enable'])
            self.assertNotIn('ShopAdvanced', migrated[task])

    def test_quantity_suffix_is_removed_in_order_and_task_paused(self):
        old = {'EventShop': {'Scheduler': {'Enable': True}, 'EventShop': {
            'PresetFilter': 'custom', 'CustomFilter': 'Cube:5 > Oil : 2 > EquipSSR > Coin:0',
        }}}
        migrated, warnings = migrate_shop_options(old, old)
        self.assertEqual('Cube > Oil > EquipSSR > Coin', migrated['EventShop']['EventShop']['CustomFilter'])
        self.assertFalse(migrated['EventShop']['Scheduler']['Enable'])
        self.assertEqual(len(warnings), 1)
        # 用户确认并重新启用后，重复读取不能再暂停。
        migrated['EventShop']['Scheduler']['Enable'] = True
        self.assertEqual((migrated, []), migrate_shop_options(migrated, migrated))

    def test_normal_filters_and_task_switches_are_preserved(self):
        old = {'EventShop': {'Scheduler': {'Enable': True}, 'EventShop': {
            'CustomFilter': 'Cube > Oil', 'BuyURShip': 1,
        }}, 'ShopFrequent': {'Scheduler': {'Enable': False}, 'ShopAdvanced': {'Mode': 'legacy'}}}
        migrated, warnings = migrate_shop_options(old, old)
        self.assertTrue(migrated['EventShop']['Scheduler']['Enable'])
        self.assertFalse(migrated['ShopFrequent']['Scheduler']['Enable'])
        self.assertEqual(old['EventShop']['EventShop'], migrated['EventShop']['EventShop'])
        self.assertEqual([], warnings)

    def test_runtime_update_applies_migration_without_touching_files(self):
        template = json.loads(Path('config/template.json').read_text(encoding='utf-8'))
        template['EventShop']['Scheduler']['Enable'] = True
        template['EventShop']['ShopAdvanced'] = {'Mode': 'advanced', 'Script': 'old'}
        migrated = ConfigUpdater().config_update(template)
        self.assertFalse(migrated['EventShop']['Scheduler']['Enable'])
        self.assertNotIn('ShopAdvanced', migrated['EventShop'])


class ShopBehaviorTests(unittest.TestCase):
    @staticmethod
    def make_event_shop(ended, affordable):
        shop = object.__new__(EventShop)
        shop.config = SimpleNamespace(EventShop_BuyURShip=2, EventShop_UnlockSSRShip=True,
                                      EventShop_PresetFilter='custom', EventShop_CustomFilter='Cube > Coin')
        shop.__dict__['is_event_ended'] = ended
        items = [SimpleNamespace(name=name, group=name.lower(), sub_genre=None, tier=None, count=5)
                 for name in ('Cube', 'Coin')]
        shop.event_shop_load_ensure = Mock()
        shop.scan_all = Mock(return_value=items)
        shop.get_current_pts = Mock()
        shop.handle_items_related_with_urpt = Mock(return_value=(items, []))
        shop.handle_unobtained_items = Mock(return_value=(items, []))
        shop.calculate_affordable_amount = Mock(side_effect=affordable)
        shop.event_shop_buy_item = Mock()
        return shop, items

    def test_active_event_stops_after_partial_priority_purchase(self):
        shop, items = self.make_event_shop(False, [2])
        shop._run()
        shop.event_shop_buy_item.assert_called_once_with(items[0], amount=2)
        shop.handle_items_related_with_urpt.assert_called_once_with(items, 2)
        shop.handle_unobtained_items.assert_called_once_with(items, True)

    def test_ended_event_skips_unaffordable_item_and_buys_next(self):
        shop, items = self.make_event_shop(True, [0, 5])
        shop._run()
        shop.event_shop_buy_item.assert_called_once_with(items[1])

    def test_ur_reserve_and_oil_capacity_still_limit_purchases(self):
        shop = object.__new__(EventShop)
        shop.pt, shop.pt_preserved, shop.urpt = 1000, 300, 20
        shop.get_oil = Mock(return_value=24000)
        oil = SimpleNamespace(name='Oil', count=10, price=100, cost='pt')
        ur = SimpleNamespace(name='ShipUR', count=1, price=200, cost='URpt')
        self.assertEqual(1, shop.calculate_affordable_amount(oil))
        self.assertEqual(0, shop.calculate_affordable_amount(ur))

    def test_empty_general_filter_still_runs_overflow_handler(self):
        shop = object.__new__(GeneralShop_250814)
        shop.__dict__['shop_filter'] = ''
        shop._validate_config_values = Mock()
        shop._meowfficer_overflow_buy = Mock()
        shop.shop_buy = Mock()
        shop.run()
        shop.shop_buy.assert_not_called()
        shop._meowfficer_overflow_buy.assert_called_once()

    def test_overflow_cat_purchase_keeps_navigation_and_threshold(self):
        shop = object.__new__(GeneralShop_250814)
        shop.config = SimpleNamespace(GeneralShop_OverflowCoins=500000)
        shop.device = Mock()
        shop._currency = 550000
        shop.shop_currency = Mock()
        shop.ui_goto = Mock()
        shop.ui_goto_main = Mock()
        with patch('module.meowfficer.buy.MeowfficerBuy') as factory:
            shop._meowfficer_overflow_buy()
        factory.return_value.meow_overflow_buy.assert_called_once_with(overflow_coins=500000)
        shop.ui_goto_main.assert_called_once()

    def test_shop_balance_is_still_recorded_to_dashboard(self):
        from module.shop.shop_status import ShopStatus

        shop = object.__new__(ShopStatus)
        shop.config = Mock()
        shop.device = SimpleNamespace(image=None)
        with patch('module.shop.shop_status.OCR_SHOP_GOLD_COINS.ocr', return_value=12345), \
                patch('module.shop.shop_status.LogRes') as recorder:
            self.assertEqual(12345, shop.status_get_gold_coins())
        self.assertEqual(('Coin', 12345), recorder.return_value.record.call_args.args)
        shop.config.update.assert_called_once()


if __name__ == '__main__':
    unittest.main()
