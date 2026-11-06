"""使用模拟库存、固定服务器时间和临时配置验证后宅跨天保留。"""

import json
import os
import tempfile
import unittest
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import MethodType, SimpleNamespace
from unittest.mock import Mock, patch

from module.config.config import AzurLaneConfig
from module.config.config_generated import GeneratedConfig
from module.device.control import Control
from module.device.device import Device
from module.dorm.dorm import FOOD_FEED_AMOUNT, OCR_FILL, Food, RewardDorm
from module.exception import GameStuckError, GameTooManyClickError


class DormFoodReserveTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 15, 4, tzinfo=timezone.utc)
        self.enterContext(patch.dict(os.environ, {'AZURPILOT_NTP_DISABLE': '1'}))
        self.enterContext(patch('module.config.server.server', 'cn'))
        self.enterContext(patch('module.dorm.dorm.current_time', side_effect=lambda tz: self.now.astimezone(tz)))
        self.config = SimpleNamespace(
            Dorm_ReserveFood=True,
            Dorm_FeedReserveState=None,
            Dorm_FeedFilter=GeneratedConfig.Dorm_FeedFilter,
        )
        self.amounts = [0] * 6
        self.fill = 90000
        self.dorm = self.make_dorm(self.config)

    def make_dorm(self, config):
        dorm = RewardDorm.__new__(RewardDorm)
        dorm.config = config
        dorm.device = Mock(image=object())
        dorm._dorm_food = SimpleNamespace(buttons=[object() for _ in FOOD_FEED_AMOUNT])
        dorm.loop = Mock(side_effect=lambda **kwargs: iter([None]))
        dorm.handle_info_bar = Mock(return_value=False)
        dorm.dorm_food_get = Mock(side_effect=lambda: (
            [Food(feed, amount) for feed, amount in zip(FOOD_FEED_AMOUNT, self.amounts)], self.fill,
        ))

        def consume(button, count, reserve=None):
            index = dorm._dorm_food.buttons.index(button)
            self.assertGreater(count, 0)
            self.assertLessEqual(count, self.amounts[index])
            self.amounts[index] -= count
            self.fill -= FOOD_FEED_AMOUNT[index] * count
            if reserve is not None:
                self.assertGreaterEqual(sum(self.amounts), reserve)

        dorm._dorm_feed_click = Mock(side_effect=consume)
        return dorm

    def use_observed_feeding(self, dropped=(), delay_frames=1, click_latency=0):
        """运行真实喂食与截图循环，按每帧 0.5 秒模拟库存更新延迟。"""
        self.elapsed = 100.0
        self.frame = 0
        self.pending = []
        self.click_stock = []
        self.click_times = []
        self.click_frames = []
        self.inventory_clicks = []
        self.enterContext(patch('module.base.timer.time', side_effect=lambda: self.elapsed))
        self.dorm._dorm_feed_click = MethodType(RewardDorm._dorm_feed_click, self.dorm)
        del self.dorm.loop
        self.dorm.appear = Mock(return_value=True)
        self.dorm.popup_interval_clear = Mock()
        self.dorm.handle_popup_cancel = Mock(return_value=False)
        self.dorm._dorm_feed_long_tap = Mock()
        device = self.dorm.device
        device.click_record = deque(maxlen=50)
        device.click_record_remove.side_effect = lambda button: Device.click_record_remove(device, button)

        def control_check(button):
            Device.click_record_add(device, button)
            Device.click_record_check(device)

        def click(button, control_check=True):
            if control_check:
                device.handle_control_check(button)
            self.click_stock.append(tuple(self.amounts))
            self.click_times.append(self.elapsed)
            self.click_frames.append(self.frame)
            self.elapsed += click_latency
            if dropped is not None and len(self.click_stock) not in dropped:
                index = self.dorm._dorm_food.buttons.index(button)
                delay = delay_frames(len(self.click_stock)) if callable(delay_frames) else delay_frames
                self.pending.append((self.elapsed + delay * 0.5, index))

        def sleep(seconds):
            self.elapsed += sum(seconds) / len(seconds) if isinstance(seconds, tuple) else seconds

        def screenshot():
            self.frame += 1
            self.elapsed += 0.5
            for due, index in self.pending.copy():
                if due <= self.elapsed + 1e-6 and self.amounts[index] > 0:
                    self.amounts[index] -= 1
                    self.fill -= FOOD_FEED_AMOUNT[index]
                    self.pending.remove((due, index))

        device.click.side_effect = click
        device.handle_control_check.side_effect = control_check
        device.multi_click.side_effect = lambda button, n: Control.multi_click(device, button, n)
        device.sleep.side_effect = sleep
        device.screenshot.side_effect = screenshot

        read = self.dorm.dorm_food_get.side_effect

        def inventory():
            self.inventory_clicks.append(len(self.click_stock))
            return read()

        self.dorm.dorm_food_get.side_effect = inventory

        def long_tap(button, count):
            index = self.dorm._dorm_food.buttons.index(button)
            used = min(self.amounts[index], self.fill // FOOD_FEED_AMOUNT[index])
            self.amounts[index] -= used
            self.fill -= FOOD_FEED_AMOUNT[index] * used

        self.dorm._dorm_feed_long_tap.side_effect = long_tap

    def test_first_enabled_day_keeps_one_from_single_food_type(self):
        for amount in (1, 2, 10):
            with self.subTest(amount=amount):
                self.config.Dorm_FeedReserveState = None
                self.amounts = [amount, 0, 0, 0, 0, 0]
                self.fill = 90000
                self.dorm.dorm_feed()
                self.assertEqual([1, 0, 0, 0, 0, 0], self.amounts)
                self.assertEqual({'day': '2026-10-15'}, self.config.Dorm_FeedReserveState)

    def test_only_one_is_reserved_across_food_types_in_filter_order(self):
        self.amounts = [2, 2, 1, 1, 1, 1]
        self.assertEqual(6, self.dorm.dorm_feed())
        self.assertEqual([1, 0, 0, 0, 0, 0], self.amounts)
        buttons = self.dorm._dorm_food.buttons
        self.assertEqual(list(reversed(buttons)), [call.kwargs['button'] for call in self.dorm._dorm_feed_click.call_args_list])

    def test_custom_filter_and_excluded_inventory_still_use_total_stock(self):
        self.config.Dorm_FeedFilter = '1000 > 20000'
        self.amounts = [2, 0, 0, 0, 0, 1]
        self.dorm.dorm_feed()
        self.assertEqual([0, 0, 0, 0, 0, 1], self.amounts)
        self.config.Dorm_FeedFilter = '1000'
        self.amounts = [2, 0, 0, 0, 0, 1]
        self.dorm.dorm_feed()
        self.assertEqual([0, 0, 0, 0, 0, 1], self.amounts)

    def test_next_day_single_food_exemption_is_used_only_once(self):
        self.config.Dorm_FeedReserveState = {'day': '2026-10-14'}
        self.amounts[0] = 1
        self.assertTrue(self.dorm.dorm_feed_once())
        self.assertEqual(0, sum(self.amounts))
        self.amounts[0] = 3
        self.dorm.dorm_feed()
        self.assertEqual(1, sum(self.amounts))
        self.assertFalse(self.dorm.dorm_feed_once())

    def test_next_day_multiple_foods_cancel_exemption_before_last_food(self):
        self.config.Dorm_FeedReserveState = {'day': '2026-10-14'}
        self.amounts = [1, 0, 0, 0, 0, 1]
        self.dorm.dorm_feed()
        self.assertEqual([1, 0, 0, 0, 0, 0], self.amounts)
        self.assertFalse(self.dorm.dorm_feed_once())

    def test_exemption_returns_on_each_following_day(self):
        self.amounts[0] = 1
        self.assertFalse(self.dorm.dorm_feed_once())
        for _ in range(3):
            self.now += timedelta(days=1)
            self.assertTrue(self.dorm.dorm_feed_once())
            self.amounts[0] = 1
            self.assertFalse(self.dorm.dorm_feed_once())

    def test_empty_full_or_filtered_out_checks_do_not_cancel_exemption(self):
        previous = {'day': '2026-10-14'}
        self.config.Dorm_FeedReserveState = previous.copy()
        self.assertFalse(self.dorm.dorm_feed_once())
        self.amounts[0] = 1
        self.fill = 0
        self.assertFalse(self.dorm.dorm_feed_once())
        self.fill = 90000
        self.config.Dorm_FeedFilter = '20000'
        self.assertFalse(self.dorm.dorm_feed_once())
        self.assertEqual(previous, self.config.Dorm_FeedReserveState)
        self.config.Dorm_FeedFilter = GeneratedConfig.Dorm_FeedFilter
        self.assertTrue(self.dorm.dorm_feed_once())

    def test_invalid_ocr_does_not_consume_food_or_exemption(self):
        previous = {'day': '2026-10-14'}
        self.config.Dorm_FeedReserveState = previous.copy()
        self.amounts[0] = 1
        self.fill = -1
        self.assertFalse(self.dorm.dorm_feed_once())
        self.assertEqual(previous, self.config.Dorm_FeedReserveState)
        self.dorm._dorm_feed_click.assert_not_called()

    def test_capacity_limit_keeps_remaining_stock_available(self):
        self.amounts[0] = 10
        self.fill = 2500
        self.assertTrue(self.dorm.dorm_feed_once())
        self.assertEqual(8, self.amounts[0])
        self.assertFalse(self.dorm.dorm_feed_once())

    def test_disabled_option_preserves_original_feeding_and_state(self):
        self.config.Dorm_ReserveFood = False
        self.amounts[0] = 6
        self.dorm.dorm_feed()
        self.assertEqual(0, sum(self.amounts))
        self.assertIsNone(self.config.Dorm_FeedReserveState)

    def test_server_midnight_resets_exemption_for_all_regions(self):
        for server, utc_hour in [('cn', 16), ('tw', 16), ('jp', 15), ('en', 7)]:
            boundary = datetime(2026, 10, 16, utc_hour, tzinfo=timezone.utc)
            with self.subTest(server=server), patch('module.config.server.server', server):
                self.now = boundary - timedelta(seconds=1)
                self.config.Dorm_FeedReserveState = None
                self.amounts = [1, 0, 0, 0, 0, 0]
                self.fill = 90000
                self.assertFalse(self.dorm.dorm_feed_once())
                self.now = boundary
                self.assertTrue(self.dorm.dorm_feed_once())
                self.amounts[0] = 1
                self.assertFalse(self.dorm.dorm_feed_once())

    def test_reserve_mode_clicks_whole_batch_before_confirming_stock(self):
        self.amounts[0] = 14
        self.use_observed_feeding()
        self.assertEqual(1, self.dorm.dorm_feed())
        self.assertEqual(1, self.amounts[0])
        self.assertEqual([14] * 13, [stock[0] for stock in self.click_stock])
        self.assertEqual([0] * 13, self.click_frames)
        self.assertEqual([0, 0, 13, 13], self.inventory_clicks)
        self.dorm.device.click_record_remove.assert_called_once_with(self.dorm._dorm_food.buttons[0])
        self.dorm.device.multi_click.assert_called_once_with(self.dorm._dorm_food.buttons[0], 13)
        self.dorm.device.handle_control_check.assert_called_once_with(self.dorm._dorm_food.buttons[0])
        self.assertEqual(14, self.dorm.device.sleep.call_count)
        self.dorm.device.sleep.assert_called_with(1)
        self.dorm._dorm_feed_long_tap.assert_not_called()
        self.assertTrue(all(0.1 <= end - start <= 0.2 for start, end in zip(self.click_times, self.click_times[1:])))

    def test_long_batch_confirms_progress_before_applying_stuck_timeout(self):
        self.amounts[0] = 40
        self.use_observed_feeding(delay_frames=3, click_latency=0.5)
        self.assertEqual(1, self.dorm.dorm_feed())
        self.assertEqual(1, self.amounts[0])
        self.assertGreater(self.click_times[-1] - self.click_times[0], 15)
        self.assertEqual(39, self.dorm.device.click.call_count)
        self.dorm.device.multi_click.assert_called_once_with(self.dorm._dorm_food.buttons[0], 39)

    def test_excess_food_keeps_original_long_press(self):
        self.amounts[0] = 100
        self.fill = 8000
        self.use_observed_feeding()
        self.dorm._dorm_feed_reserved = Mock(wraps=self.dorm._dorm_feed_reserved)
        self.assertEqual(1, self.dorm.dorm_feed())
        self.assertEqual(92, self.amounts[0])
        self.dorm._dorm_feed_long_tap.assert_called_once_with(self.dorm._dorm_food.buttons[0], 8)
        self.dorm._dorm_feed_reserved.assert_not_called()

    def test_exactly_enough_food_uses_special_mode(self):
        self.amounts[0] = 8
        self.fill = 8000
        self.use_observed_feeding()
        self.dorm.dorm_feed()
        self.assertEqual(1, self.amounts[0])
        self.assertEqual(7, self.dorm.device.click.call_count)
        self.dorm._dorm_feed_long_tap.assert_not_called()

    def test_other_food_stock_allows_long_press_then_switches_to_reserve(self):
        self.amounts = [2, 0, 0, 0, 0, 4]
        self.use_observed_feeding()
        self.dorm._dorm_feed_reserved = Mock(wraps=self.dorm._dorm_feed_reserved)
        self.assertEqual(2, self.dorm.dorm_feed())
        self.assertEqual([1, 0, 0, 0, 0, 0], self.amounts)
        self.dorm._dorm_feed_long_tap.assert_called_once_with(self.dorm._dorm_food.buttons[5], 4)
        self.dorm._dorm_feed_reserved.assert_called_once_with(self.dorm._dorm_food.buttons[0], 1, reserve=1)

    def test_other_food_stock_keeps_original_small_click_delay(self):
        self.amounts = [1, 0, 0, 0, 0, 2]
        self.use_observed_feeding()
        self.dorm._dorm_feed_reserved = Mock(wraps=self.dorm._dorm_feed_reserved)
        self.dorm.dorm_feed()
        self.assertEqual([1, 0, 0, 0, 0, 0], self.amounts)
        self.assertEqual(2, self.dorm.device.sleep.call_count)
        self.dorm.device.sleep.assert_called_with((0.5, 0.8))
        self.dorm._dorm_feed_reserved.assert_not_called()

    def test_disabled_option_keeps_original_long_press(self):
        self.config.Dorm_ReserveFood = False
        self.dorm.appear = Mock(return_value=True)
        self.dorm.popup_interval_clear = Mock()
        self.dorm._dorm_feed_long_tap = Mock()
        button = self.dorm._dorm_food.buttons[0]
        RewardDorm._dorm_feed_click(self.dorm, button, 12)
        self.dorm._dorm_feed_long_tap.assert_called_once_with(button, 12)

    def test_swallowed_clicks_retry_until_actual_stock_reaches_reserve(self):
        self.amounts[0] = 6
        self.use_observed_feeding(dropped={1, 3, 4, 6})
        self.assertEqual(1, self.dorm.dorm_feed())
        self.assertEqual(1, self.amounts[0])
        self.assertEqual(9, self.dorm.device.click.call_count)
        self.assertEqual([5, 3, 1], [call.args[1] for call in self.dorm.device.multi_click.call_args_list])
        self.assertEqual([6] * 5 + [4] * 3 + [2], [stock[0] for stock in self.click_stock])
        self.assertEqual(3, self.dorm.device.click_record_remove.call_count)
        self.assertEqual(3, sum(call.args == (1,) for call in self.dorm.device.sleep.call_args_list))
        self.assertGreaterEqual(self.click_times[5] - self.click_times[4], 1)
        self.assertGreaterEqual(self.click_times[8] - self.click_times[7], 1)
        self.assertEqual(85000, self.fill)

    def test_delayed_inventory_is_confirmed_after_one_second_pause(self):
        self.amounts[0] = 3
        self.use_observed_feeding(delay_frames=3)
        self.dorm.dorm_feed()
        self.assertEqual([3, 3], [stock[0] for stock in self.click_stock])
        self.assertEqual([0, 0], self.click_frames)
        self.dorm.device.multi_click.assert_called_once()
        self.dorm.device.sleep.assert_called_with(1)
        self.assertEqual(1, self.frame)
        self.assertEqual(1, self.amounts[0])

    def test_staggered_inventory_updates_complete_during_batch_pause(self):
        self.amounts[0] = 4
        self.use_observed_feeding(delay_frames=lambda click: click)
        self.dorm.dorm_feed()
        self.assertEqual(3, self.dorm.device.click.call_count)
        self.dorm.device.multi_click.assert_called_once()
        self.dorm.device.sleep.assert_called_with(1)
        self.assertEqual(1, self.frame)
        self.assertEqual(1, self.amounts[0])

    def test_swallowed_exempt_food_click_is_retried_within_same_feeding(self):
        self.config.Dorm_FeedReserveState = {'day': '2026-10-14'}
        self.amounts[0] = 1
        self.use_observed_feeding(dropped={1, 2})
        self.assertTrue(self.dorm.dorm_feed_once())
        self.assertEqual(3, self.dorm.device.click.call_count)
        self.assertEqual(0, self.amounts[0])
        self.amounts[0] = 1
        self.assertFalse(self.dorm.dorm_feed_once())

    def test_partial_feeding_stops_at_observed_satiety(self):
        self.amounts[0] = 10
        self.fill = 2500
        self.use_observed_feeding(dropped={1})
        self.dorm._dorm_feed_reserved = Mock(wraps=self.dorm._dorm_feed_reserved)
        self.dorm.dorm_feed()
        self.assertEqual(3, self.dorm.device.click.call_count)
        self.assertEqual(8, self.amounts[0])
        self.assertEqual(500, self.fill)
        self.dorm._dorm_feed_reserved.assert_not_called()

    def test_unconfirmed_inventory_uses_existing_stuck_recovery(self):
        self.amounts[0] = 5
        self.use_observed_feeding(dropped=None)
        with self.assertRaises(GameStuckError):
            self.dorm.dorm_feed_once()
        self.assertEqual(5, self.amounts[0])
        self.assertGreater(self.dorm.device.click.call_count, 1)
        self.dorm.device.click_record_remove.assert_not_called()

    def test_batch_keeps_existing_click_guard_until_progress_is_confirmed(self):
        self.amounts[0] = 3
        self.use_observed_feeding(dropped=None)
        self.dorm.device.click_record.extend([str(self.dorm._dorm_food.buttons[0])] * 49)
        with self.assertRaises(GameTooManyClickError):
            self.dorm.dorm_feed_once()
        self.assertEqual(3, self.amounts[0])
        self.dorm.device.click.assert_not_called()
        self.dorm.device.click_record_remove.assert_not_called()

    def test_invalid_stock_does_not_confirm_consumption_or_allow_click(self):
        self.amounts[0] = 3
        self.use_observed_feeding(dropped={1})
        read = self.dorm.dorm_food_get.side_effect

        def inventory():
            if 1 <= self.frame <= 6:
                return [Food(feed, 0) for feed in FOOD_FEED_AMOUNT], -1
            return read()

        self.dorm.dorm_food_get.side_effect = inventory
        self.dorm.dorm_feed()
        self.assertEqual(1, self.amounts[0])
        self.assertEqual(3, self.dorm.device.click.call_count)
        self.assertEqual([0, 0], self.click_frames[:2])
        self.assertGreater(self.click_frames[-1], 6)
        self.assertEqual([2, 1], [call.args[1] for call in self.dorm.device.multi_click.call_args_list])
        self.assertEqual(2, self.dorm.device.click_record_remove.call_count)


    def test_zero_stock_is_valid_even_if_dark_pixels_indicate_food(self):
        self.dorm._dorm_has_food = Mock(return_value=True)
        self.dorm._dorm_food_ocr = Mock()
        for amounts in ([0, 4, 0, 0, 0, 0], [0, 0, 0, 0, 0, 0]):
            with self.subTest(amounts=amounts):
                self.dorm._dorm_food_ocr.ocr.return_value = amounts
                with patch('module.dorm.dorm.OCR_FILL.ocr', return_value=(12982, 37018, 50000)):
                    food, fill = RewardDorm.dorm_food_get(self.dorm)
                self.assertEqual(amounts, [f.amount for f in food])
                self.assertEqual(37018, fill)

    def test_invalid_satiety_still_prevents_feeding(self):
        self.amounts = [0, 4, 0, 0, 0, 0]
        self.dorm._dorm_has_food = Mock(return_value=True)
        self.dorm._dorm_food_ocr = Mock()
        self.dorm._dorm_food_ocr.ocr.return_value = self.amounts.copy()
        self.dorm.dorm_food_get = MethodType(RewardDorm.dorm_food_get, self.dorm)
        with patch('module.dorm.dorm.OCR_FILL.ocr', return_value=(0, 0, 0)):
            food, fill = self.dorm.dorm_food_get()
            self.assertEqual(self.amounts, [f.amount for f in food])
            self.assertEqual(-1, fill)
            self.assertFalse(self.dorm.dorm_feed_once())
        self.dorm._dorm_feed_click.assert_not_called()
        self.assertIsNone(self.config.Dorm_FeedReserveState)

    def test_reported_four_food_stock_feeds_three_and_reserves_one(self):
        self.amounts = [0, 4, 0, 0, 0, 0]
        self.fill = 37018
        self.use_observed_feeding()
        self.dorm._dorm_has_food = Mock(return_value=True)
        self.dorm._dorm_food_ocr = Mock()
        self.dorm._dorm_food_ocr.ocr.side_effect = lambda image: self.amounts.copy()
        self.dorm.dorm_food_get = MethodType(RewardDorm.dorm_food_get, self.dorm)
        with patch('module.dorm.dorm.OCR_FILL.ocr', side_effect=lambda image: (
            50000 - self.fill, self.fill, 50000,
        )):
            self.assertEqual(1, self.dorm.dorm_feed())
        self.assertEqual([0, 1, 0, 0, 0, 0], self.amounts)
        self.assertEqual(31018, self.fill)
        self.assertEqual(3, self.dorm.device.click.call_count)
        self.dorm._dorm_feed_long_tap.assert_not_called()

    def test_restart_loads_consumed_exemption_from_temporary_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'dorm_test.json'
            template = Path(__file__).resolve().parents[1] / 'config/template.json'
            data = json.loads(template.read_text(encoding='utf-8'))
            data['Dorm']['Dorm'].update(ReserveFood=True, FeedReserveState={'day': '2026-10-14'})
            path.write_text(json.dumps(data), encoding='utf-8')
            with patch('module.config.config.filepath_config', return_value=str(path)), patch(
                'module.config.config_updater.filepath_config', return_value=str(path)
            ):
                config = AzurLaneConfig('dorm_test', task='Dorm')
                dorm = self.make_dorm(config)
                self.amounts[0] = 1
                self.assertTrue(dorm.dorm_feed_once())
                saved = json.loads(path.read_text(encoding='utf-8'))
                self.assertEqual({'day': '2026-10-15'}, saved['Dorm']['Dorm']['FeedReserveState'])
                self.amounts[0] = 1
                restarted = self.make_dorm(AzurLaneConfig('dorm_test', task='Dorm'))
                self.assertFalse(restarted.dorm_feed_once())
                self.now += timedelta(days=1)
                self.assertTrue(restarted.dorm_feed_once())

    def test_ocr_dorm_food_rejects_current_above_total_or_invalid_capacity(self):
        for raw, expected in [
            ('12084/50000', (12084, 37916, 50000)),
            ('1208450000', (12084, 37916, 50000)),
            ('40000/40000', (40000, 0, 40000)),
            ('102000/102000', (102000, 0, 102000)),
            ('13650/5210', (0, 0, 0)),
            ('60000/50000', (0, 0, 0)),
            ('1000/5210', (0, 0, 0)),
            ('1000/41000', (0, 0, 0)),
            ('9000050000', (0, 0, 0)),
        ]:
            with self.subTest(raw=raw), patch(
                'module.dorm.dorm.Ocr.ocr',
                side_effect=lambda reader, image, direct_ocr=False, text=raw: reader.after_process(text),
            ):
                self.assertEqual(expected, OCR_FILL.ocr(object()))

    def test_transient_truncated_total_ocr_does_not_stop_feeding_early(self):
        self.amounts = [0, 4, 0, 0, 0, 0]
        self.fill = 38350
        self.use_observed_feeding()
        self.dorm._dorm_has_food = Mock(return_value=True)
        self.dorm._dorm_food_ocr = Mock()
        self.dorm._dorm_food_ocr.ocr.side_effect = lambda image: self.amounts.copy()
        self.dorm.dorm_food_get = MethodType(RewardDorm.dorm_food_get, self.dorm)

        def raw_ocr(reader, image, direct_ocr=False):
            if self.frame in {1, 2}:
                return reader.after_process('13650/5210')
            return reader.after_process(f'{50000 - self.fill}/50000')

        with patch('module.dorm.dorm.Ocr.ocr', side_effect=raw_ocr):
            self.assertEqual(1, self.dorm.dorm_feed())
        self.assertEqual([0, 1, 0, 0, 0, 0], self.amounts)
        self.assertEqual(32350, self.fill)
        self.assertEqual(3, self.dorm.device.click.call_count)


if __name__ == '__main__':
    unittest.main()

