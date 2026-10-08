"""隔离验证原调度清油、委托恢复和后宅有界购粮。"""
import unittest
from collections import deque
from datetime import timedelta
from unittest.mock import Mock, patch

from module.campaign.run import CampaignRun
from module.commission.commission import RewardCommission
from module.config.config import TaskEnd
from module.dorm.dorm import RewardDorm, TEMPLATE_DORM_OIL_COST, FOOD_PLUS
from module.exception import OilMaxed
from tests import test_scheduler_live_loop as live


class OilControlTests(unittest.TestCase):
    setUp = live.LiveLoopTests.setUp
    virtual_wait = live.LiveLoopTests.virtual_wait
    apply = live.LiveLoopTests.apply

    def enable(self, *tasks, target=24000):
        config = self.script.config
        config.cross_set_many({
            'General.OilControl.Enable': True,
            'General.OilControl.Target': target,
            'General.YukikazeTaskManager.TaskPriorityAdjustment': 'Restart > Commission > Research > Event > Main > Main2',
            'Restart.Scheduler.Enable': False,
            'Restart.Scheduler.NextRun': self.time + timedelta(days=1),
            **{f'{task}.Scheduler.Enable': True for task in tasks},
        })
        self.enterContext(patch('module.scheduler.oil_control.now', side_effect=lambda: self.time))
        self.oil = self.runtime.oil_control
        self.script.config.stop_event = self.script.stop_event

    def readings(self, *values):
        values = deque(values)
        def read(config, device, publish=True):
            value = values.popleft()
            if value is not None:
                self.runtime.store.observe('testpilot', 'Oil', value, self.time.isoformat(), 'fixture')
            return value
        return self.enterContext(patch('module.scheduler.resources.observe_oil', side_effect=read))

    def test_farm_preempts_commission_and_restores_stop_line(self):
        self.enable('Commission', 'Main')
        original = self.script.config.cross_get('Main.StopCondition.OilLimit')
        self.readings(25000, 23900)
        self.assertEqual('Main', self.script.get_next_task())
        self.assertEqual(24000, self.script.config.StopCondition_OilLimit)
        self.assertFalse(self.script.config.task_switched())
        campaign = CampaignRun(self.script.config, self.script.device)
        campaign.campaign = Mock()
        campaign.handle_commission_notice()
        campaign.campaign.commission_notice_show_at_campaign.assert_not_called()
        self.runtime.task_finished('Main', True)
        self.assertEqual({}, self.runtime.overlay)
        self.assertEqual(original, self.script.config.StopCondition_OilLimit)
        self.assertEqual('Commission', self.script.get_next_task())
        self.assertEqual(original, self.script.config.cross_get('Main.StopCondition.OilLimit'))

    def test_real_loop_cleans_before_commission_without_extra_timer(self):
        self.enable('Commission', 'Main')
        self.readings(25000, 23900)
        def main():
            self.calls.append('Main')
            self.assertFalse(self.script.config.task_switched())
            self.script.config.Scheduler_NextRun = self.time + timedelta(hours=1)
        def commission():
            self.calls.append('Commission')
            self.script.stop_event.set()
        self.script.main, self.script.commission = main, commission
        self.script.loop()
        self.assertEqual(['Main', 'Commission'], self.calls)
        self.assertEqual({}, self.runtime.overlay)

    def test_storage_scan_skips_oil_navigation_and_preserves_next_task_check(self):
        self.enable('StorageStatistics', 'Commission', 'Main')
        self.script.config.cross_set_many({
            'Commission.Scheduler.NextRun': self.time + timedelta(hours=1),
            'Main.Scheduler.NextRun': self.time + timedelta(hours=1),
        })
        read = self.readings(25000)
        self.assertEqual('StorageStatistics', self.script.get_next_task())
        read.assert_not_called()
        self.assertTrue(self.oil.check_pending)
        self.script.config.task_delay(minute=10080)
        self.runtime.task_finished('StorageStatistics', True)
        self.script.config.cross_set_many({
            'Commission.Scheduler.NextRun': self.time,
            'Main.Scheduler.NextRun': self.time,
        })
        self.assertEqual('Main', self.script.get_next_task())
        read.assert_called_once()

    def test_cooling_farm_uses_dorm_without_resetting_next_run(self):
        self.enable('Commission', 'Main')
        deadline = self.time + timedelta(hours=2)
        self.script.config.cross_set('Main.Scheduler.NextRun', deadline)
        self.readings(25000, 23950)
        with patch.object(RewardDorm, 'dorm_buy_oil_food', return_value=True) as buy:
            self.assertEqual('Commission', self.script.get_next_task())
        buy.assert_called_once_with(25000, 24000)
        self.assertEqual(deadline, self.script.config.cross_get('Main.Scheduler.NextRun'))

    def test_new_emotion_cooldown_is_saved_then_dorm_runs(self):
        self.enable('Commission', 'Main')
        self.readings(25000, 25000, 23950)
        self.assertEqual('Main', self.script.get_next_task())
        deadline = self.time + timedelta(minutes=40)
        self.script.config.task_delay(target=deadline)
        self.assertTrue(self.script.config.task_switched())
        self.runtime.task_finished('Main', True)
        with patch.object(RewardDorm, 'dorm_buy_oil_food', return_value=True):
            self.assertEqual('Commission', self.script.get_next_task())
        self.assertEqual(deadline, self.script.config.cross_get('Main.Scheduler.NextRun'))

    def test_fault_cooldown_and_disabled_tasks_are_not_started(self):
        self.enable('Commission', 'Main')
        self.script.task_restart_delays['Main'] = self.time + timedelta(hours=1)
        self.readings(25000, 23950)
        with patch.object(RewardDorm, 'dorm_buy_oil_food', return_value=True):
            self.assertEqual('Commission', self.script.get_next_task())
        self.assertFalse(self.script.config.is_task_enabled('Main2'))

    def test_next_available_farm_is_used_before_dorm(self):
        self.enable('Commission', 'Event', 'Main')
        self.script.config.cross_set('Event.Scheduler.NextRun', self.time + timedelta(hours=1))
        self.readings(25000)
        with patch.object(RewardDorm, 'dorm_buy_oil_food') as buy:
            self.assertEqual('Main', self.script.get_next_task())
        buy.assert_not_called()

    def test_target_stop_does_not_add_low_oil_cooldown(self):
        self.enable('Commission', 'Main')
        self.readings(25000)
        self.assertEqual('Main', self.script.get_next_task())
        campaign = CampaignRun(self.script.config, self.script.device)
        campaign.run_limit = 0
        campaign.status_get_gems = Mock()
        campaign.get_coin = Mock()
        campaign.get_oil = Mock(return_value=23950)
        deadline = self.script.config.cross_get('Main.Scheduler.NextRun')
        self.assertTrue(campaign.triggered_stop_condition())
        self.assertEqual(deadline, self.script.config.cross_get('Main.Scheduler.NextRun'))

    def test_actual_run_count_limit_still_disables_farm(self):
        self.enable('Commission', 'Main')
        self.readings(25000)
        self.assertEqual('Main', self.script.get_next_task())
        campaign = CampaignRun(self.script.config, self.script.device)
        campaign.run_limit = 1
        campaign.name = '12-4'
        self.script.config.StopCondition_RunCount = 0
        with patch('module.campaign.run.handle_notify'):
            self.assertTrue(campaign.triggered_stop_condition(oil_check=False))
        self.assertFalse(self.script.config.is_task_enabled('Main'))

    def test_boundaries_and_custom_target(self):
        self.enable('Commission', 'Main', target=23000)
        read = self.readings(23000, 23001)
        self.assertEqual('Commission', self.script.get_next_task())
        self.runtime.task_finished('Commission', True)
        self.assertEqual('Main', self.script.get_next_task())
        self.assertEqual(23000, self.script.config.StopCondition_OilLimit)
        self.assertEqual(2, read.call_count)

    def test_missing_oil_and_ineffective_purchase_back_off(self):
        self.enable('Commission')
        self.readings(None)
        self.assertEqual('Commission', self.script.get_next_task())
        self.assertEqual(self.time + timedelta(minutes=5), self.oil.retry_at)
        self.time += timedelta(minutes=6)
        self.readings(25000, 25000)
        with patch.object(RewardDorm, 'dorm_buy_oil_food', return_value=True) as buy:
            self.assertEqual('Commission', self.script.get_next_task())
        buy.assert_called_once()
        self.assertFalse(self.oil.active)

    def test_user_stop_and_restart_preempt_cleanup(self):
        self.enable('Commission', 'Main')
        self.readings(25000)
        self.assertEqual('Main', self.script.get_next_task())
        self.script.stop_event.set()
        self.assertTrue(self.script.config.task_switched())
        self.script.stop_event.clear()
        self.script.config.task_call('Restart')
        self.assertTrue(self.script.config.task_switched())
        self.runtime.task_finished('Main', 'recoverable')
        self.assertEqual('Restart', self.script.get_next_task())
        self.assertEqual({}, self.runtime.overlay)

    def test_disabled_and_custom_modes_do_not_observe_or_buy(self):
        self.enable('Commission')
        self.script.config.cross_set('General.OilControl.Enable', False)
        with patch('module.scheduler.resources.observe_oil') as read:
            self.assertEqual('Commission', self.script.get_next_task())
            self.script.config.cross_set('General.OilControl.Enable', True)
            for mode in ('enhance', 'takeover'):
                self.runtime.mode = mode
                self.assertEqual('Commission', self.oil.select('Commission'))
        read.assert_not_called()

    def test_disabling_during_cleanup_yields_and_clears_overlay(self):
        self.enable('Commission', 'Main')
        self.readings(25000)
        self.assertEqual('Main', self.script.get_next_task())
        self.script.config.cross_set('General.OilControl.Enable', False)
        self.assertTrue(self.script.config.task_switched())
        self.runtime.task_finished('Main', True)
        self.assertEqual({}, self.runtime.overlay)

    def test_overflow_requests_cleanup_instead_of_fixed_food_purchase(self):
        self.enable('Commission')
        self.readings(23950)
        self.assertEqual('Commission', self.script.get_next_task())
        commission = RewardCommission(self.script.config, self.script.device)
        commission._commission_receive = Mock(side_effect=OilMaxed)
        commission.loop = Mock(return_value=range(3))
        commission.handle_popup_confirm = Mock(side_effect=[True, False])
        commission.ui_page_appear = Mock(return_value=True)
        with patch.object(RewardDorm, 'dorm_food_run') as legacy, self.assertRaises(TaskEnd):
            commission.commission_receive()
        legacy.assert_not_called()
        self.assertTrue(self.oil.active)
        self.assertEqual(1, self.oil.blocked_attempts)

    def test_overflow_can_safely_leave_the_commission_page(self):
        from module.ui.page import page_commission
        self.enable('Commission')
        self.readings(23950)
        self.assertEqual('Commission', self.script.get_next_task())
        commission = RewardCommission(self.script.config, self.script.device)
        commission._commission_receive = Mock(side_effect=OilMaxed)
        commission.loop = Mock(return_value=range(3))
        commission.handle_popup_confirm = Mock(return_value=False)
        commission.ui_page_appear = Mock(side_effect=lambda page: page is page_commission)
        commission.ui_additional = Mock()
        with self.assertRaises(TaskEnd):
            commission.commission_receive()
        commission.ui_additional.assert_not_called()
        self.assertEqual(1, self.oil.blocked_attempts)

    def test_changed_target_yields_then_rebuilds_temporary_stop_line(self):
        self.enable('Commission', 'Main')
        self.readings(25000, 25000)
        self.assertEqual('Main', self.script.get_next_task())
        self.script.config.cross_set('General.OilControl.Target', 23000)
        self.assertTrue(self.script.config.task_switched())
        self.runtime.task_finished('Main', True)
        self.assertEqual({}, self.runtime.overlay)
        self.assertEqual('Main', self.script.get_next_task())
        self.assertEqual(23000, self.oil.goal)
        self.assertEqual(23000, self.runtime.overlay['StopCondition_OilLimit'])

    def test_three_overflow_clearings_then_defer_commission(self):
        self.enable('Commission', 'Research')
        for index in range(3):
            self.readings(23950 - index * 500, 23450 - index * 500)
            self.assertTrue(self.oil.request_blocked('Commission'))
            self.runtime.task_finished('Commission', True)
            with patch.object(RewardDorm, 'dorm_buy_oil_food', return_value=True):
                self.assertEqual('Commission', self.script.get_next_task())
            self.assertEqual(index + 1, self.oil.blocked_attempts)
        self.assertTrue(self.oil.request_blocked('Commission'))
        self.assertEqual(self.time + timedelta(minutes=5), self.script.config.cross_get('Commission.Scheduler.NextRun'))
        self.assertEqual('Research', self.script.get_next_task())
        self.assertFalse(self.oil.active)

    def test_failed_cleanup_defers_blocked_task_without_retrying_receive(self):
        self.enable('Commission', 'Research')
        self.oil.request_blocked('Commission')
        self.readings(25000)
        with patch.object(RewardDorm, 'dorm_buy_oil_food', return_value=False) as buy:
            self.assertEqual('Research', self.script.get_next_task())
        buy.assert_called_once()
        self.assertEqual(self.time + timedelta(minutes=5), self.script.config.cross_get('Commission.Scheduler.NextRun'))

    def test_completed_commission_resets_overflow_attempts(self):
        self.enable('Commission')
        self.oil.request_blocked('Commission')
        self.readings(23950, 23450)
        with patch.object(RewardDorm, 'dorm_buy_oil_food', return_value=True):
            self.assertEqual('Commission', self.script.get_next_task())
        self.runtime.task_finished('Commission', True)
        self.assertIsNone(self.oil.blocked_task)
        self.assertEqual(0, self.oil.blocked_attempts)

    def test_program_change_clears_native_cleanup_state(self):
        from module.scheduler.templates import default_program
        self.enable('Commission', 'Main')
        self.readings(25000)
        self.assertEqual('Main', self.script.get_next_task())
        self.apply(default_program())
        self.assertTrue(self.script.config.task_switched())
        self.runtime.task_finished('Main', True)
        self.runtime.load_program()
        self.assertEqual({}, self.runtime.overlay)
        self.assertFalse(self.runtime.oil_control.active)

    def test_only_existing_tasks_wake_instance(self):
        self.enable('Commission')
        with patch('module.scheduler.resources.observe_oil') as read:
            self.assertIsNone(self.runtime.next_task())
        read.assert_not_called()


class DormOilPurchaseTests(unittest.TestCase):
    def dorm(self):
        dorm = RewardDorm.__new__(RewardDorm)
        dorm.device = Mock()
        dorm.ui_ensure = Mock()
        dorm.handle_info_bar = Mock(return_value=False)
        dorm.ui_goto = Mock()
        dorm.dorm_feed_enter = Mock()
        dorm.dorm_feed_quit = Mock()
        dorm.appear = Mock(return_value=True)
        dorm.match_template_color = Mock(return_value=True)
        dorm.appear_then_click = Mock(return_value=True)
        dorm.match_template_color.side_effect = lambda *args, **kwargs: dorm.appear_then_click.called
        dorm.loop = Mock(side_effect=lambda **kwargs: range(8))
        dorm.dorm_oil_price = Mock(return_value=(1, 50))
        return dorm

    def test_minimum_purchase_is_based_on_verified_unit_price(self):
        dorm = self.dorm()
        dorm.dorm_oil_quantity = Mock(return_value=(21, 1050))
        self.assertTrue(dorm.dorm_buy_oil_food(25000, 24000))
        dorm.dorm_oil_quantity.assert_called_once_with(21, 50)
        dorm.dorm_feed_quit.assert_called_once()

    def test_unreadable_or_non_oil_price_cancels_without_confirmation(self):
        dorm = self.dorm()
        dorm.dorm_oil_price.return_value = None
        dorm.appear_then_click = Mock()
        self.assertFalse(dorm.dorm_buy_oil_food(25000, 24000))
        dorm.appear_then_click.assert_not_called()
        dorm.dorm_feed_quit.assert_called_once()

    def test_inventory_quantity_limit_accepts_verified_smaller_batch(self):
        dorm = self.dorm()
        amount = 1
        def click(button, n, interval):
            nonlocal amount
            self.assertIs(button, FOOD_PLUS)
            amount = min(4, amount + n)
        dorm.device.multi_click.side_effect = click
        dorm.dorm_oil_price.side_effect = lambda: (amount, amount * 50)
        self.assertEqual((4, 200), dorm.dorm_oil_quantity(21, 50))
        self.assertEqual(2, dorm.device.multi_click.call_count)

    def test_price_change_rejects_confirmation(self):
        dorm = self.dorm()
        dorm.dorm_oil_price.return_value = (1, 100)
        self.assertIsNone(dorm.dorm_oil_quantity(21, 50))
        dorm.device.multi_click.assert_not_called()

    def test_oil_icon_is_required_before_reading_numbers(self):
        from module.dorm import dorm as implementation
        dorm = self.dorm()
        dorm.appear.return_value = False
        with patch.object(implementation.OCR_BUY_FOOD_AMOUNT, 'ocr') as read:
            self.assertIsNone(RewardDorm.dorm_oil_price(dorm))
        dorm.appear.assert_called_once_with(TEMPLATE_DORM_OIL_COST, offset=(20, 20))
        read.assert_not_called()

    def test_outside_budget_or_safety_floor_does_not_purchase(self):
        dorm = self.dorm()
        self.assertFalse(dorm.dorm_buy_oil_food(500, 1000))
        dorm.ui_ensure.assert_not_called()
        dorm.dorm_oil_quantity = Mock(return_value=(999, 49950))
        self.assertFalse(dorm.dorm_buy_oil_food(25000, 24000))


if __name__ == '__main__':
    unittest.main()
