"""资源管理完整链路使用临时配置、SQLite、模拟帧及已有奖励截图。"""
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
from starlette.testclient import TestClient

from module.api.app import create_app
from module.api.config_service import ConfigService
from module.api.protocol import ApiError, ResourceFlowsParams
from module.api.resource_service import resource_flows
from module.statistics import resource_flow as flow
from module.statistics.resource_tracking import RewardTracker, record_purchase, record_research_cost
from tests.test_api import fixture


class ResourceFlowTests(unittest.TestCase):
    def setUp(self):
        self.directory = self.enterContext(tempfile.TemporaryDirectory())
        self.root = fixture(self.directory)
        self.enterContext(patch('module.statistics.resource_stats._LOCAL_DB', str(self.root / 'config/azurstats_local.db')))
        self.config = SimpleNamespace(config_name='testpilot', task=SimpleNamespace(command='Main'))
        self.time = datetime(2026, 10, 7, 12)
        self.enterContext(patch('module.statistics.resource_flow.now', side_effect=lambda: self.time))
        self.configs = ConfigService(self.root)

    def report(self, **params):
        return resource_flows(self.configs, ResourceFlowsParams(instance='testpilot',
            start='2026-10-07 00:00:00', end='2026-10-08 00:00:00', **params))

    def test_confirmed_transactions_reconcile_without_double_count(self):
        with flow.task_session('testpilot', 'Main'):
            flow.observe(self.config, 'Oil', 24000)
            flow.observe(self.config, 'Coin', 10000)
            flow.record(self.config, {'Oil': -100, 'Coin': 500}, '战斗结算', event_key='battle-1')
            flow.record(self.config, {'Oil': -100, 'Coin': 500}, '战斗结算', event_key='battle-1')
            flow.observe(self.config, 'Oil', 23900)
            flow.observe(self.config, 'Coin', 10500)
        result = self.report()
        self.assertEqual(2, result['total'])
        oil = next(item for item in result['resources'] if item['key'] == 'Oil')
        self.assertEqual((0, 100, 0, 23900), (oil['income'], oil['expense'], oil['adjustment'], oil['current']))
        self.assertEqual({'Main'}, {entry['task'] for entry in result['entries']})

    def test_same_run_delta_is_attributed_but_offline_gap_and_pt_reset_are_not(self):
        with flow.task_session('testpilot', 'Event'):
            flow.observe(self.config, 'Oil', 24000)
            flow.observe(self.config, 'Pt', 1000)
            flow.observe(self.config, 'Oil', 23500)
            flow.observe(self.config, 'Pt', 1200)
            flow.observe(self.config, 'Pt', 0)
        with flow.task_session('testpilot', 'Commission'):
            flow.observe(self.config, 'Oil', 23700)
        result = self.report()
        self.assertEqual(4, result['total'])
        self.assertEqual(2, len([entry for entry in result['entries'] if entry['evidence'] == 'adjustment']))
        self.assertEqual({'Event'}, {entry['task'] for entry in result['entries'] if entry['evidence'] == 'observed'})
        self.assertEqual(0, next(item for item in result['resources'] if item['key'] == 'Pt')['expense'])

    def test_first_read_and_invalid_read_are_not_income_or_zero(self):
        flow.observe(self.config, 'Oil', None)
        flow.observe(self.config, 'Coin', False)
        self.assertEqual(0, self.report()['total'])
        flow.observe(self.config, 'Oil', 24000)
        result = self.report()
        self.assertEqual(0, result['total'])
        self.assertIsNone(next(item for item in result['resources'] if item['key'] == 'Coin')['current'])

    def test_event_shop_pt_spending_is_not_an_event_reset(self):
        with flow.task_session('testpilot', 'EventShop'):
            flow.observe(self.config, 'Pt', 1500)
            flow.observe(self.config, 'Pt', 900)
        result = self.report(resource='Pt')
        self.assertEqual((600, 'EventShop', 'observed'),
                         (result['flows'][0]['expense'], result['flows'][0]['task'], result['flows'][0]['evidence']))

    def test_verified_storage_snapshot_updates_inventory_without_fake_income(self):
        from module.storage.statistics import StorageStatistics
        task = StorageStatistics.__new__(StorageStatistics)
        task.config = self.config
        self.config.StorageStatistics_RunIntervalDays = 7
        self.config.task_delay = Mock()
        task.ui_goto_storage = Mock()
        task._storage_enter_material = Mock()
        task._scan_pass = Mock(return_value=SimpleNamespace(rows=[], pages=1))
        catalog = Mock(servers=['cn'], version=1)
        catalog.snapshot_items.return_value = [{'id': 'Chip', 'amount': 13393}]
        with flow.task_session('testpilot', 'StorageStatistics'), patch('module.storage.statistics.StorageCatalog', return_value=catalog), patch('module.storage.statistics.save_snapshot') as save:
            task.run()
        self.assertEqual(1, task._scan_pass.call_count)
        self.config.task_delay.assert_called_once_with(minute=10080)
        save.assert_called_once()
        self.assertEqual(0, self.report()['total'])
        self.assertEqual(13393, next(item for item in self.report()['resources'] if item['key'] == 'Chip')['current'])

    def test_single_campaign_final_read_keeps_last_oil_cost_in_its_task(self):
        from module.campaign.run import CampaignRun
        from module.ui.page import page_campaign
        campaign = CampaignRun.__new__(CampaignRun)
        campaign.config = self.config
        campaign.device = Mock()
        ui = Mock()
        ui.ui_page_appear.side_effect = lambda page: page is page_campaign
        ui._get_num.side_effect = lambda button, name, *args, **kwargs: 23880 if name.endswith('Oil') else 10215
        ui.loop.return_value = range(2)
        self.config.save = Mock()
        with flow.task_session('testpilot', 'Main'):
            flow.observe(self.config, 'Oil', 24000)
            flow.observe(self.config, 'Coin', 10000)
            flow.record(self.config, {'Coin': 215}, '战斗奖励', evidence='recognition')
            campaign._run = Mock(return_value=None)
            with patch('module.campaign.campaign_status.CampaignStatus', return_value=ui), patch('module.log_res.LogRes') as log:
                log.return_value.record.side_effect = lambda name, value, **kwargs: flow.observe(self.config, name, value)
                campaign.run('12-4', total=1)
        result = self.report()
        self.assertEqual(120, next(item for item in result['resources'] if item['key'] == 'Oil')['expense'])
        self.assertEqual(215, next(item for item in result['resources'] if item['key'] == 'Coin')['income'])
        self.assertEqual({'Main'}, {entry['task'] for entry in result['entries']})
        ui.ui_ensure.assert_not_called()
        campaign.device.click.assert_not_called()

    def test_campaign_failure_does_not_read_more_frames_before_recovery(self):
        from module.campaign.run import CampaignRun
        from module.exception import GameStuckError
        campaign = CampaignRun.__new__(CampaignRun)
        campaign._run = Mock(side_effect=GameStuckError('模拟卡住'))
        with patch('module.statistics.resource_tracking.observe_campaign_end') as read:
            with self.assertRaises(GameStuckError):
                campaign.run('12-4')
        read.assert_not_called()

    def test_user_stop_skips_final_campaign_observation(self):
        from threading import Event
        from module.statistics.resource_tracking import observe_campaign_end
        stop = Event()
        stop.set()
        self.config._scheduler_runtime = SimpleNamespace(script=SimpleNamespace(stop_event=stop))
        with flow.task_session('testpilot', 'Main'), patch('module.campaign.campaign_status.CampaignStatus') as ui:
            observe_campaign_end(self.config, Mock())
        ui.assert_not_called()

    def test_filter_pagination_full_totals_and_export_watermark(self):
        with flow.task_session('testpilot', 'Commission'):
            for index in range(125):
                flow.record(self.config, {'Oil': 10, 'Cube': 1}, '领取', event_key=str(index))
        with flow.task_session('testpilot', 'Research'):
            flow.record(self.config, {'Cube': -2}, '科研')
        first = self.report(resource='Oil', task='Commission', limit=20)
        self.assertEqual(125, first['total'])
        self.assertEqual(1250, first['flows'][0]['income'])
        self.assertEqual({'Commission', 'Research'}, set(first['tasks']))
        ids = {row['id'] for row in first['entries']}
        with flow.task_session('testpilot', 'Commission'):
            flow.record(self.config, {'Oil': 999}, '并发新记录')
        second = self.report(resource='Oil', task='Commission', offset=20, limit=1000, through_id=first['throughId'])
        self.assertEqual(125, second['total'])
        self.assertFalse(ids.intersection(row['id'] for row in second['entries']))
        self.assertEqual(105, len(second['entries']))

    def test_instance_isolation_and_session_restore_after_exception(self):
        with self.assertRaises(RuntimeError), flow.task_session('testpilot', 'Commission'):
            flow.record(self.config, {'Coin': 50}, '领取')
            raise RuntimeError('模拟任务中断')
        self.assertIsNone(flow.session_for(self.config))
        other = SimpleNamespace(config_name='other', task=SimpleNamespace(command='Main'))
        with flow.task_session('other', 'Main'):
            flow.record(other, {'Coin': 999}, '其他实例')
        self.assertEqual(50, self.report()['flows'][0]['income'])

    def test_purchase_receipt_and_confirmed_cost_do_not_duplicate_goods(self):
        item = SimpleNamespace(cost='Coins', price=20, amount=3, name='Cubes', is_known_item=lambda: True)
        with flow.task_session('testpilot', 'ShopFrequent') as state:
            flow.observe(self.config, 'Coin', 100)
            flow.record(self.config, {'Cube': 6}, '奖励领取', evidence='recognition')
            state['rewards']['Cube'] = 6
            record_purchase(self.config, item, quantity=2, receipts={})
            flow.observe(self.config, 'Coin', 60)
        result = self.report()
        cube = next(item for item in result['resources'] if item['key'] == 'Cube')
        self.assertEqual(6, cube['income'])
        self.assertEqual(40, next(item for item in result['resources'] if item['key'] == 'Coin')['expense'])

    def test_research_exact_cost_and_unknown_quantity(self):
        project = SimpleNamespace(name='H-test', data={'input': [{'name': 'Coins', 'amount': 1500}, {'name': 'Cubes', 'amount': 2}, {'name': 'Unknown'}]})
        with flow.task_session('testpilot', 'Research'):
            record_research_cost(self.config, project)
        self.assertEqual({'Coin': 1500, 'Cube': 2}, {row['resource']: row['expense'] for row in self.report()['flows']})

    def test_shop_and_voucher_keep_confirmed_bulk_accounting_without_scripts(self):
        from module.shop.clerk import ShopClerk
        from module.shop.shop_voucher import VoucherShop
        from module.ui.assets import BACK_ARROW, SHOP_BACK_ARROW

        for shop_type, arrow in ((ShopClerk, SHOP_BACK_ARROW), (VoucherShop, BACK_ARROW)):
            with self.subTest(shop=shop_type.__name__):
                shop = object.__new__(shop_type)
                shop.config, shop.device = self.config, Mock()
                shop.shop_interval_clear = shop.interval_reset = Mock()
                shop.appear = Mock(side_effect=lambda button, **kwargs: button is arrow and 'interval' not in kwargs)
                shop.appear_then_click = shop.handle_retirement = shop.shop_obstruct_handle = Mock(return_value=False)
                shop.info_bar_count = Mock(return_value=0)
                shop.shop_purchase_result_handle = Mock(side_effect=[True, False])
                item = SimpleNamespace(cost='Coins', price=20, amount=2, name='Cubes', is_known_item=lambda: True)
                def handle_quantity(_item):
                    _item._resource_purchase_quantity = 7
                    shop.shop_buy_handle.return_value = False
                    shop.shop_buy_handle.side_effect = None
                    return True
                shop.shop_buy_handle = Mock(side_effect=handle_quantity)
                with flow.task_session('testpilot', 'ShopFrequent'):
                    shop.shop_buy_execute(item)
        result = self.report()
        self.assertEqual(280, next(row for row in result['resources'] if row['key'] == 'Coin')['expense'])
        self.assertEqual(28, next(row for row in result['resources'] if row['key'] == 'Cube')['income'])

    def test_shop_and_voucher_information_bar_does_not_count_as_purchase(self):
        from module.shop.clerk import ShopClerk
        from module.shop.shop_voucher import VoucherShop
        from module.ui.assets import BACK_ARROW, SHOP_BACK_ARROW

        for shop_type, arrow in ((ShopClerk, SHOP_BACK_ARROW), (VoucherShop, BACK_ARROW)):
            with self.subTest(shop=shop_type.__name__):
                shop = object.__new__(shop_type)
                shop.config, shop.device = self.config, Mock()
                shop.shop_interval_clear = shop.interval_reset = Mock()
                shop.appear = Mock(side_effect=lambda button, **kwargs: button is arrow and 'interval' not in kwargs)
                shop.appear_then_click = shop.handle_retirement = shop.shop_buy_handle = Mock(return_value=False)
                shop.shop_obstruct_handle = shop.shop_purchase_result_handle = Mock(return_value=False)
                shop.info_bar_count = Mock(side_effect=[1, 0])
                item = SimpleNamespace(cost='Coins', price=20, amount=2, name='Cubes', is_known_item=lambda: True)
                with flow.task_session('testpilot', 'ShopFrequent'):
                    shop.shop_buy_execute(item)
        self.assertEqual(0, self.report()['total'])

    def test_opsi_partial_batch_records_executed_quantity(self):
        from module.os_shop.shop import OSShop

        shop = object.__new__(OSShop)
        shop.config, shop.device = self.config, Mock()
        shop.get_currency_coins = Mock(return_value=300)
        shop.get_coins_no_limit = Mock(return_value=1000)
        shop.interval_clear = shop.ui_ensure_index = Mock()
        item = SimpleNamespace(price=10, count=100)
        with patch('module.os_shop.shop.OCR_SHOP_AMOUNT.ocr', return_value=1):
            self.assertTrue(shop.shop_buy_amount_handler(item))
        self.assertEqual(10, item._resource_purchase_quantity)

    def test_shop_batch_accounting_uses_affordable_quantity(self):
        from module.shop.clerk import ShopClerk

        shop = object.__new__(ShopClerk)
        shop.config, shop.device = self.config, Mock()
        shop._currency = 100
        shop.appear = shop.appear_then_click = Mock(return_value=False)
        shop.ui_ensure_index = Mock()
        item = SimpleNamespace(price=20)
        with patch('module.shop.clerk.OCR_SHOP_AMOUNT.ocr', return_value=30):
            self.assertTrue(shop.shop_buy_amount_execute(item))
        self.assertEqual(5, item._resource_purchase_quantity)
        self.assertEqual(5, shop.ui_ensure_index.call_args.args[0])

    def test_opsi_confirmed_bulk_purchase_keeps_ledger(self):
        from module.os_shop.shop import OSShop
        from module.shop.assets import SHOP_BUY_CONFIRM_AMOUNT
        from module.os_shop.assets import PORT_SUPPLY_CHECK

        shop = object.__new__(OSShop)
        shop.config, shop.device = self.config, Mock()
        shop.interval_clear = shop.interval_reset = Mock()
        shop.appear_then_click = shop.handle_popup_confirm = Mock(return_value=False)
        shop.handle_map_get_items = Mock(side_effect=[False, True, False])
        shop.appear = Mock(side_effect=lambda button, **kwargs: button is SHOP_BUY_CONFIRM_AMOUNT or button is PORT_SUPPLY_CHECK)
        item = SimpleNamespace(cost='YellowCoins', price=20, amount=2, name='Cubes', is_known_item=lambda: True)
        def handle_quantity(_item):
            _item._resource_purchase_quantity = 7
            return True
        shop.shop_buy_amount_handler = Mock(side_effect=handle_quantity)
        with flow.task_session('testpilot', 'OpsiShop'):
            self.assertTrue(shop.os_shop_buy_execute(item))
        result = self.report()
        self.assertEqual(140, next(row for row in result['resources'] if row['key'] == 'YellowCoin')['expense'])
        self.assertEqual(14, next(row for row in result['resources'] if row['key'] == 'Cube')['income'])

    def test_build_confirmed_orders_attribute_cube_and_coin_spending(self):
        from module.gacha.gacha_reward import RewardGacha
        gacha = RewardGacha.__new__(RewardGacha)
        config = SimpleNamespace(config_name='testpilot', Gacha_Pool='heavy', Gacha_Amount=2,
                                 Gacha_UseTicket=False, Gacha_UseDrill=False)
        gacha.config = config
        gacha.device = Mock()
        gacha.gacha_flush_queue = Mock()
        gacha.ui_goto_gacha = Mock()
        gacha.get_coin = Mock(return_value=10000)
        gacha.gacha_goto_pool = Mock(return_value='heavy')
        gacha.gacha_calculate = Mock(return_value=2)
        gacha.gacha_prep = Mock(side_effect=lambda amount: amount > 0)
        gacha.gacha_submit = Mock()
        with flow.task_session('testpilot', 'Gacha'), patch('module.gacha.gacha_reward.OCR_BUILD_CUBE_COUNT') as ocr, patch('module.gacha.gacha_reward.LogRes'):
            ocr.ocr.return_value = 100
            self.assertTrue(gacha.gacha_run())
        self.assertEqual({'Coin': 3000, 'Cube': 4}, {row['resource']: row['expense'] for row in self.report()['flows']})
        self.assertEqual({'Gacha'}, {row['task'] for row in self.report()['flows']})
        # 提交失败时没有新增消耗，不能按计划次数预先扣账。
        gacha.gacha_submit.side_effect = RuntimeError('模拟提交失败')
        with flow.task_session('testpilot', 'Gacha'), patch('module.gacha.gacha_reward.OCR_BUILD_CUBE_COUNT'), patch('module.gacha.gacha_reward.LogRes'):
            with self.assertRaises(RuntimeError):
                gacha.gacha_run()
        self.assertEqual(2, self.report()['total'])

    def test_oil_food_price_is_kept_when_natural_recovery_offsets_the_net_cost(self):
        from module.scheduler.oil_control import NativeOilControl
        self.config.save = Mock()
        runtime = SimpleNamespace(script=SimpleNamespace(config=self.config, device=Mock()))
        control = NativeOilControl(runtime)
        control.action, control.oil, control.goal = 'buy', 25000, 24000
        dorm = Mock(_oil_food_purchase=(21, 1050))
        dorm.dorm_buy_oil_food.return_value = True
        with flow.task_session('testpilot', 'OilControl'):
            flow.observe(self.config, 'Oil', 25000)
        with flow.task_session('testpilot', 'OilControl'), patch('module.dorm.dorm.RewardDorm', return_value=dorm), patch('module.scheduler.resources.observe_oil', return_value=23952), patch('module.log_res.LogRes') as log:
            log.return_value.record.side_effect = lambda name, value, **kwargs: flow.observe(self.config, name, value)
            control.run_action()
        oil = next(item for item in self.report()['resources'] if item['key'] == 'Oil')
        self.assertEqual((1050, 2), (oil['expense'], oil['adjustment']))
        food = next(item for item in self.report()['resources'] if item['key'] == 'Food')
        self.assertEqual(21, food['income'])

    def test_reward_retry_counts_once_then_identical_new_dialog_counts_again(self):
        from module.combat import assets
        from module.handler import assets as handler
        visible = True
        for button in (assets.GET_ITEMS_1, assets.GET_ITEMS_2, assets.GET_ITEMS_3):
            self.enterContext(patch.object(button, 'match_template_color', side_effect=lambda *args, **kwargs: visible))
        self.enterContext(patch.object(handler.INFO_BAR_1, 'appear_on', return_value=False))
        parser = Mock()
        parser.stats_get_items.return_value = [SimpleNamespace(name='Coins', amount=215, is_known_item=lambda: True)]
        self.enterContext(patch('module.statistics.resource_tracking.reward_parser', return_value=parser))
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        with flow.task_session('testpilot', 'Commission'):
            tracker = RewardTracker(self.config)
            for _ in range(5):
                tracker.frame(image, clicked=True)
            visible = False
            tracker.frame(image); tracker.frame(image)
            visible = True
            tracker.frame(image, clicked=True)
        self.assertEqual(2, self.report()['total'])
        self.assertEqual(430, self.report()['flows'][0]['income'])

    def test_existing_screenshot_is_parsed_into_task_income(self):
        from module.base.utils import load_image
        image = load_image(str(Path(__file__).parent / 'fixtures/opsi_requested_items/boss_get_items_3.png'))
        with flow.task_session('testpilot', 'OpsiMonthlyBoss'):
            RewardTracker(self.config).frame(image, clicked=True)
        result = self.report()
        self.assertGreater(result['total'], 0)
        self.assertEqual({'OpsiMonthlyBoss'}, {entry['task'] for entry in result['entries']})
        self.assertTrue(all(entry['amount'] > 0 for entry in result['entries']))

    def test_quick_commission_group_and_multiple_reward_layouts_are_not_missed(self):
        from module.combat import assets
        from module.commission.assets import EXP_INFO_S_REWARD
        from module.handler import assets as handler
        layout = 0
        for index, button in enumerate((assets.GET_ITEMS_1, assets.GET_ITEMS_2, assets.GET_ITEMS_3)):
            self.enterContext(patch.object(button, 'match_template_color', side_effect=lambda *args, index=index, **kwargs: layout == index))
        self.enterContext(patch.object(EXP_INFO_S_REWARD, 'match_template_color', side_effect=lambda *args, **kwargs: layout == -1))
        self.enterContext(patch.object(handler.INFO_BAR_1, 'appear_on', return_value=False))
        parser = Mock()
        parser.stats_get_items.return_value = [SimpleNamespace(name='Oil', amount=500, is_known_item=lambda: True)]
        self.enterContext(patch('module.statistics.resource_tracking.reward_parser', return_value=parser))
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        with flow.task_session('testpilot', 'Commission'):
            tracker = RewardTracker(self.config)
            tracker.frame(image, clicked=True)
            layout = 1
            tracker.frame(image, clicked=True)
            layout = 0
            tracker.frame(image, clicked=True)  # 同组返回上一页不重复。
            layout = -1
            tracker.frame(image)  # 只有一帧经验结算仍确认新委托。
            layout = 0
            tracker.frame(image, clicked=True)
        self.assertEqual(3, self.report()['total'])
        self.assertEqual(1500, self.report()['flows'][0]['income'])

    def test_api_rejects_invalid_ranges_without_device_access(self):
        for params in ({'start': 'bad'}, {'start': '2026-10-08', 'end': '2026-10-07'}, {'start': '2020-01-01', 'end': '2026-01-01'}, {'start': '2026-10-07T00:00:00Z'}):
            with self.assertRaises(ApiError):
                resource_flows(self.configs, ResourceFlowsParams(instance='testpilot', **params))

    def test_real_websocket_ledger_query_and_oil_config_patch(self):
        with flow.task_session('testpilot', 'Commission'):
            flow.record(self.config, {'Oil': 1000, 'Cube': 2}, '奖励领取')
        app = create_app(root=self.root, password='', manage_runtime=False, mount_mcp=False)
        with TestClient(app) as client, client.websocket_connect('/api/v1/ws') as socket:
            socket.receive_json()
            sequence = 0
            def call(method, params):
                nonlocal sequence
                sequence += 1
                request_id = f'resource-{sequence}'
                socket.send_json({'v': 1, 'type': 'request', 'id': request_id, 'method': method, 'params': params})
                while True:
                    response = socket.receive_json()
                    if response.get('id') == request_id:
                        self.assertTrue(response['ok'], response)
                        return response['result']
            result = call('statistics.resourceFlows', {'instance': 'testpilot', 'start': '2026-10-07', 'end': '2026-10-08'})
            self.assertEqual(2, result['total'])
            self.assertEqual(24000, result['oilControl']['target'])
            call('config.patch', {'instance': 'testpilot', 'changes': [{'path': 'General.OilControl.Target', 'value': 23000}, {'path': 'General.OilControl.Enable', 'value': False}]})
            result = call('statistics.resourceFlows', {'instance': 'testpilot', 'resource': 'Oil', 'start': '2026-10-07', 'end': '2026-10-08'})
            self.assertEqual({'enable': False, 'target': 23000}, result['oilControl'])
            self.assertEqual(1, result['total'])


if __name__ == '__main__':
    unittest.main()
