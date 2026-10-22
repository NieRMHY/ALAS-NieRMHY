"""每日建造使用模拟页面验证卡池选择、支付资源和队列返回流程。"""

import unittest
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from module.config.config import TaskEnd
from module.exception import GameStuckError
from module.gacha.assets import BUILD_TICKET_CHECK
from module.gacha.gacha_reward import RewardGacha


class GachaTicketTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch('module.gacha.gacha_reward.LogRes'))
        cube_ocr = self.enterContext(patch('module.gacha.gacha_reward.OCR_BUILD_CUBE_COUNT'))
        cube_ocr.ocr.return_value = 100
        cube_ocr.last_valid = True
        self.ticket_ocr = self.enterContext(patch('module.gacha.gacha_reward.OCR_BUILD_TICKET_COUNT'))
        self.record = self.enterContext(patch('module.gacha.gacha_reward.record'))
        self.enterContext(patch('module.config.server.server', 'cn'))

    def make_gacha(self, pool='light', amount=1, tickets=0, use_ticket=True,
                   use_drill=False, event_available=True, ticket_visible=True, coins=10000,
                   ticket_amount=1, clear_ticket=False, clear_ticket_time='09:30'):
        gacha = RewardGacha.__new__(RewardGacha)
        gacha.config = SimpleNamespace(
            Gacha_Pool=pool, Gacha_Amount=amount, Gacha_UseTicket=use_ticket,
            Gacha_TicketAmount=ticket_amount, Gacha_ClearTicket=clear_ticket,
            Gacha_ClearTicketTime=clear_ticket_time, Gacha_UseDrill=use_drill,
            update=Mock(), task_delay=Mock(), task_stop=Mock(side_effect=TaskEnd))
        gacha.device = SimpleNamespace(image=object())
        state = SimpleNamespace(page='build', pool='light', tickets=tickets, orders=[], visits=[], queued=0)
        self.record.reset_mock()
        self.ticket_ocr.reset_mock()
        self.ticket_ocr.ocr.side_effect = lambda image: state.tickets

        def flush_queue():
            state.page = 'build'
            state.queued = 0

        def goto_pool(target_pool):
            self.assertEqual('build', state.page, '切换卡池前必须返回建造页')
            state.visits.append(target_pool)
            state.pool = 'light' if target_pool == 'event' and not event_available else target_pool
            return state.pool

        def return_to_build(upper):
            self.assertEqual(1, upper)
            state.page = 'build'
            return True

        def prepare(count):
            if not count:
                return False
            self.assertEqual('build', state.page, '提交下一批订单前必须返回建造页')
            self.assertLessEqual(state.queued + count, 10, '提交前必须为下一批释放队列容量')
            payment = 'ticket' if state.pool == 'event' and state.tickets > 0 else 'cube'
            if payment == 'ticket':
                self.assertLessEqual(count, state.tickets, '建造次数不能超出现有建造券')
            state.pending = (state.pool, count, payment)
            state.page = 'confirm'
            return True

        def submit():
            self.assertEqual('confirm', state.page)
            state.orders.append(state.pending)
            state.queued += state.pending[1]
            if state.pending[2] == 'ticket':
                state.tickets -= state.pending[1]
            state.page = 'queue'

        gacha.ui_goto_gacha = Mock()
        gacha.gacha_flush_queue = Mock(side_effect=flush_queue)
        gacha.get_coin = Mock(return_value=coins)
        gacha.gacha_goto_pool = Mock(side_effect=goto_pool)
        gacha.gacha_side_navbar_ensure = Mock(side_effect=return_to_build)
        gacha.appear = Mock(side_effect=lambda button, **kwargs:
                            button is BUILD_TICKET_CHECK and state.pool == 'event' and ticket_visible)
        gacha.gacha_prep = Mock(side_effect=prepare)
        gacha.gacha_submit = Mock(side_effect=submit)
        return gacha, state

    def test_available_tickets_take_priority_over_every_configured_pool(self):
        for pool in ['light', 'heavy', 'special', 'event', 'wishing_well']:
            with self.subTest(pool=pool):
                gacha, state = self.make_gacha(pool=pool, amount=2, tickets=5, ticket_amount=2)
                self.assertTrue(gacha.gacha_run())
                self.assertEqual([('event', 2, 'ticket')], state.orders)
                self.assertEqual({'event'}, set(state.visits))
                self.assertEqual(pool, gacha.config.Gacha_Pool)
                self.assertEqual((10000, 100), (gacha.build_coin_count, gacha.build_cube_count))
                self.record.assert_called_once_with(gacha.config, {'GachaTicket': -2}, '建造 event × 2')

    def test_zero_tickets_use_configured_pool_and_its_cost(self):
        for pool in ['light', 'heavy', 'special', 'event', 'wishing_well']:
            with self.subTest(pool=pool):
                gacha, state = self.make_gacha(pool=pool, amount=2)
                self.assertTrue(gacha.gacha_run())
                self.assertEqual([(pool, 2, 'cube')], state.orders)
                self.assertEqual(['event', pool], state.visits)
                costs = {'Coin': -1200, 'Cube': -2} if pool == 'light' else {'Coin': -3000, 'Cube': -4}
                self.record.assert_called_once_with(gacha.config, costs, f'建造 {pool} × 2')

    def test_unavailable_event_uses_configured_pool_with_existing_light_fallback(self):
        for pool in ['light', 'heavy', 'special', 'event']:
            with self.subTest(pool=pool):
                gacha, state = self.make_gacha(pool=pool, event_available=False)
                self.assertTrue(gacha.gacha_run())
                actual_pool = 'light' if pool == 'event' else pool
                self.assertEqual([(actual_pool, 1, 'cube')], state.orders)
                self.ticket_ocr.ocr.assert_not_called()

    def test_missing_ticket_icon_uses_configured_pool(self):
        gacha, state = self.make_gacha(pool='heavy', ticket_visible=False)
        self.assertTrue(gacha.gacha_run())
        self.assertEqual([('heavy', 1, 'cube')], state.orders)
        self.ticket_ocr.ocr.assert_not_called()

    def test_partial_tickets_return_from_queue_and_finish_in_configured_pool(self):
        for pool in ['light', 'heavy', 'special', 'event', 'wishing_well']:
            with self.subTest(pool=pool):
                gacha, state = self.make_gacha(pool=pool, amount=3, tickets=1)
                self.assertTrue(gacha.gacha_run())
                self.assertEqual([('event', 1, 'ticket'), (pool, 2, 'cube')], state.orders)
                self.assertEqual('event', state.visits[0])
                self.assertEqual(pool, state.visits[-1])
                self.assertEqual(pool, gacha.config.Gacha_Pool)
                self.assertEqual('build', state.page)
                costs = {'Coin': -1200, 'Cube': -2} if pool == 'light' else {'Coin': -3000, 'Cube': -4}
                self.assertEqual([
                    call(gacha.config, {'GachaTicket': -1}, '建造 event × 1'),
                    call(gacha.config, costs, f'建造 {pool} × 2'),
                ], self.record.call_args_list)

    def test_disabled_ticket_priority_does_not_visit_event_pool(self):
        for pool in ['light', 'heavy', 'special', 'wishing_well']:
            with self.subTest(pool=pool):
                gacha, state = self.make_gacha(pool=pool, use_ticket=False, tickets=5)
                self.assertTrue(gacha.gacha_run())
                self.assertEqual([(pool, 1, 'cube')], state.orders)
                self.assertEqual([pool], state.visits)
                self.ticket_ocr.ocr.assert_not_called()
                gacha.appear.assert_not_called()

    def test_no_cubes_or_coins_still_allows_ticket_order(self):
        gacha, state = self.make_gacha(amount=3, tickets=1, coins=0)
        with patch('module.gacha.gacha_reward.OCR_BUILD_CUBE_COUNT') as cube_ocr:
            cube_ocr.ocr.return_value = 0
            self.assertTrue(gacha.gacha_run())
        self.assertEqual([('event', 1, 'ticket')], state.orders)
        self.record.assert_called_once_with(gacha.config, {'GachaTicket': -1}, '建造 event × 1')

    def test_fallback_build_count_is_limited_by_configured_pool_resources(self):
        gacha, state = self.make_gacha(amount=3, tickets=1, coins=600)
        self.assertTrue(gacha.gacha_run())
        self.assertEqual([('event', 1, 'ticket'), ('light', 1, 'cube')], state.orders)
        self.assertEqual(0, gacha.build_coin_count)
        self.assertEqual(99, gacha.build_cube_count)

    def test_no_tickets_and_no_resources_does_not_submit(self):
        gacha, state = self.make_gacha(coins=0)
        self.assertFalse(gacha.gacha_run())
        self.assertEqual([], state.orders)
        self.record.assert_not_called()

    def test_use_drill_flushes_each_batch_and_already_returns_to_build(self):
        gacha, state = self.make_gacha(amount=3, tickets=1, use_drill=True)
        self.assertTrue(gacha.gacha_run())
        self.assertEqual([('event', 1, 'ticket'), ('light', 2, 'cube')], state.orders)
        self.assertEqual(3, gacha.gacha_flush_queue.call_count)
        gacha.gacha_side_navbar_ensure.assert_not_called()

    def test_ticket_preparation_failure_does_not_record_or_start_cube_order(self):
        gacha, state = self.make_gacha(amount=3, tickets=1)
        gacha.gacha_prep.side_effect = None
        gacha.gacha_prep.return_value = False
        self.assertFalse(gacha.gacha_run())
        self.assertEqual([], state.orders)
        self.assertEqual({'event'}, set(state.visits))
        self.record.assert_not_called()

    def test_ticket_submission_failure_does_not_record_or_start_cube_order(self):
        gacha, state = self.make_gacha(amount=3, tickets=1)
        gacha.gacha_submit.side_effect = RuntimeError('模拟提交失败')
        with self.assertRaisesRegex(RuntimeError, '模拟提交失败'):
            gacha.gacha_run()
        self.assertEqual([], state.orders)
        self.assertEqual({'event'}, set(state.visits))
        self.record.assert_not_called()

    def test_return_to_build_failure_stops_before_cube_order(self):
        gacha, state = self.make_gacha(amount=3, tickets=1)
        gacha.gacha_side_navbar_ensure.side_effect = None
        gacha.gacha_side_navbar_ensure.return_value = False
        with self.assertRaises(GameStuckError):
            gacha.gacha_run()
        self.assertEqual([('event', 1, 'ticket')], state.orders)
        self.record.assert_called_once_with(gacha.config, {'GachaTicket': -1}, '建造 event × 1')

    def test_task_still_schedules_next_server_update(self):
        gacha, state = self.make_gacha(tickets=1)
        gacha.run()
        self.assertEqual([('event', 1, 'ticket')], state.orders)
        gacha.config.task_delay.assert_called_once_with(server_update=True)

    def test_ticket_amount_can_exceed_daily_minimum(self):
        gacha, state = self.make_gacha(amount=2, tickets=8, ticket_amount=5)
        self.assertTrue(gacha.gacha_run())
        self.assertEqual([('event', 5, 'ticket')], state.orders)
        self.assertEqual(3, gacha.build_ticket_count)
        self.record.assert_called_once_with(gacha.config, {'GachaTicket': -5}, '建造 event × 5')

    def test_ticket_amount_is_limited_by_available_tickets(self):
        gacha, state = self.make_gacha(tickets=2, ticket_amount=5)
        self.assertTrue(gacha.gacha_run())
        self.assertEqual([('event', 2, 'ticket')], state.orders)
        self.assertEqual(0, gacha.build_ticket_count)

    def test_ticket_amount_below_minimum_keeps_unused_tickets_for_other_pool(self):
        gacha, state = self.make_gacha(amount=4, tickets=8, ticket_amount=2)
        self.assertTrue(gacha.gacha_run())
        self.assertEqual([('event', 2, 'ticket'), ('light', 2, 'cube')], state.orders)
        self.assertEqual(6, gacha.build_ticket_count)
        self.assertEqual([
            call(gacha.config, {'GachaTicket': -2}, '建造 event × 2'),
            call(gacha.config, {'Coin': -1200, 'Cube': -2}, '建造 light × 2'),
        ], self.record.call_args_list)

    def test_event_pool_minimum_uses_its_remaining_tickets_before_cubes(self):
        for tickets, orders in [
            (8, [('event', 4, 'ticket')]),
            (2, [('event', 2, 'ticket'), ('event', 2, 'cube')]),
        ]:
            with self.subTest(tickets=tickets):
                gacha, state = self.make_gacha(pool='event', amount=4, tickets=tickets)
                self.assertTrue(gacha.gacha_run())
                self.assertEqual(orders, state.orders)
                self.assertEqual({'GachaTicket': -min(4, tickets)}, self.record.call_args_list[0].args[1])
                self.assertEqual(max(0, tickets - 4), gacha.build_ticket_count)

    def test_zero_batch_does_not_navigate_prepare_or_record(self):
        gacha, state = self.make_gacha()
        self.assertFalse(gacha.gacha_run_once('event', 0, True, forced_use_drill=True))
        self.assertEqual([], state.visits)
        gacha.gacha_prep.assert_not_called()
        gacha.gacha_flush_queue.assert_not_called()
        self.record.assert_not_called()

    def test_event_disappearing_before_ticket_submit_never_falls_back_to_cubes(self):
        gacha, state = self.make_gacha(tickets=2)
        goto_pool = gacha.gacha_goto_pool.side_effect

        def disappear_after_first_visit(pool):
            actual_pool = goto_pool(pool)
            return actual_pool if len(state.visits) == 1 else 'light'

        gacha.gacha_goto_pool.side_effect = disappear_after_first_visit
        with self.assertRaises(GameStuckError):
            gacha.gacha_run()
        self.assertEqual([], state.orders)
        self.assertEqual(2, gacha.build_ticket_count)
        gacha.gacha_prep.assert_not_called()
        self.record.assert_not_called()

    def test_missing_ticket_icon_before_submit_stops_without_spending(self):
        gacha, state = self.make_gacha(tickets=2)
        gacha.appear.side_effect = [True, False]
        with self.assertRaises(GameStuckError):
            gacha.gacha_run()
        self.assertEqual([], state.orders)
        self.assertEqual(2, gacha.build_ticket_count)
        self.record.assert_not_called()

    def mock_deadline(self, gacha, deadline=date(2026, 6, 12), server_now=None):
        if server_now is None:
            server_now = datetime(2026, 6, 12, 1, 30, tzinfo=timezone.utc)
        self.enterContext(patch('module.gacha.gacha_reward.current_time', side_effect=lambda tz: server_now.astimezone(tz)))
        return self.enterContext(patch.object(gacha, '_get_event_deadline', return_value=deadline))

    def test_clear_ticket_requires_both_switches_and_available_tickets(self):
        for use_ticket, clear_ticket, tickets in [(False, True, 5), (True, False, 5), (True, True, 0)]:
            with self.subTest(use_ticket=use_ticket, clear_ticket=clear_ticket, tickets=tickets):
                gacha, state = self.make_gacha(
                    use_ticket=use_ticket, clear_ticket=clear_ticket, tickets=tickets)
                deadline = self.mock_deadline(gacha, server_now=datetime(2026, 6, 12, 1, tzinfo=timezone.utc))
                self.assertTrue(gacha.gacha_run())
                deadline.assert_not_called()
                self.assertEqual(1, len(state.orders))
                gacha.config.task_stop.assert_not_called()
                gacha.config.task_delay.assert_not_called()

    def test_unknown_future_or_past_deadline_only_uses_normal_daily_ticket_amount(self):
        for deadline in [None, date(2026, 6, 11), date(2026, 6, 13)]:
            with self.subTest(deadline=deadline):
                gacha, state = self.make_gacha(tickets=25, ticket_amount=2, clear_ticket=True)
                self.mock_deadline(gacha, deadline, server_now=datetime(2026, 6, 12, 1, tzinfo=timezone.utc))
                self.assertTrue(gacha.gacha_run())
                self.assertEqual([('event', 2, 'ticket')], state.orders)
                self.assertEqual(23, gacha.build_ticket_count)
                self.assertEqual(1, gacha.gacha_flush_queue.call_count)
                gacha.config.task_stop.assert_not_called()
                gacha.config.task_delay.assert_not_called()

    def test_last_day_waits_until_configured_time_without_submitting_or_overwriting_schedule(self):
        for hour, minute, second, clear_time in [(0, 0, 0, '09:30'), (1, 29, 59, '9:30'), (2, 0, 0, '11:45')]:
            with self.subTest(hour=hour, minute=minute, second=second, clear_time=clear_time):
                gacha, state = self.make_gacha(tickets=25, clear_ticket=True, clear_ticket_time=clear_time)
                utc_now = datetime(2026, 6, 12, hour, minute, second, tzinfo=timezone.utc)
                self.mock_deadline(gacha, server_now=utc_now)
                with self.assertRaises(TaskEnd):
                    gacha.run()

                target = datetime.combine(date(2026, 6, 12), datetime.strptime(clear_time, '%H:%M').time(),
                                          tzinfo=timezone(timedelta(hours=8)))
                gacha.config.task_delay.assert_called_once_with(target=target.astimezone().replace(tzinfo=None))
                gacha.config.task_stop.assert_called_once_with()
                self.assertEqual([], state.orders)
                self.assertEqual(25, state.tickets)
                self.assertEqual(25, gacha.build_ticket_count)
                gacha.gacha_prep.assert_not_called()
                gacha.gacha_submit.assert_not_called()
                self.record.assert_not_called()

    def test_clear_ticket_delay_converts_server_time_to_local_scheduler_time(self):
        gacha, state = self.make_gacha(tickets=25, clear_ticket=True)
        self.mock_deadline(gacha, server_now=datetime(2026, 6, 12, 16, tzinfo=timezone.utc))
        with patch('module.gacha.gacha_reward.server_timezone', return_value=timedelta(hours=-7)):
            with self.assertRaises(TaskEnd):
                gacha.run()
        target = datetime(2026, 6, 12, 16, 30, tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
        gacha.config.task_delay.assert_called_once_with(target=target)
        self.assertEqual([], state.orders)

    def test_last_day_at_or_after_configured_time_clears_and_schedules_next_day(self):
        for hour, minute, clear_time in [(1, 30, '09:30'), (1, 31, '9:30'), (3, 45, '11:45'), (15, 59, '11:45')]:
            with self.subTest(hour=hour, minute=minute, clear_time=clear_time):
                gacha, state = self.make_gacha(tickets=25, clear_ticket=True, clear_ticket_time=clear_time)
                self.mock_deadline(gacha, server_now=datetime(2026, 6, 12, hour, minute, tzinfo=timezone.utc))
                gacha.run()
                self.assertEqual([('event', 10, 'ticket'), ('event', 10, 'ticket'), ('event', 5, 'ticket')], state.orders)
                self.assertEqual(0, state.tickets)
                gacha.config.task_delay.assert_called_once_with(server_update=True)
                gacha.config.task_stop.assert_not_called()

    def test_last_day_clears_all_tickets_in_batches_and_only_forces_intermediate_drills(self):
        for tickets, counts, flushes in [(1, [1], 1), (10, [10], 1), (20, [10, 10], 2), (25, [10, 10, 5], 3)]:
            with self.subTest(tickets=tickets):
                gacha, state = self.make_gacha(tickets=tickets, clear_ticket=True)
                self.mock_deadline(gacha)
                self.assertTrue(gacha.gacha_run())
                self.assertEqual([('event', count, 'ticket') for count in counts], state.orders)
                self.assertEqual(0, gacha.build_ticket_count)
                self.assertEqual(0, state.tickets)
                self.assertEqual('build', state.page)
                self.assertEqual(counts[-1], state.queued)
                self.assertEqual(flushes, gacha.gacha_flush_queue.call_count)
                self.assertEqual([
                    call(gacha.config, {'GachaTicket': -count}, f'建造 event × {count}') for count in counts
                ], self.record.call_args_list)
                self.assertEqual((10000, 100), (gacha.build_coin_count, gacha.build_cube_count))
                gacha.config.update.assert_called_once_with()

    def test_enabled_drill_also_flushes_the_last_clear_ticket_batch(self):
        gacha, state = self.make_gacha(tickets=25, clear_ticket=True, use_drill=True)
        self.mock_deadline(gacha)
        self.assertTrue(gacha.gacha_run())
        self.assertEqual(3, len(state.orders))
        self.assertEqual(4, gacha.gacha_flush_queue.call_count)
        self.assertEqual(0, state.queued)
        gacha.gacha_side_navbar_ensure.assert_not_called()

    def test_clear_ticket_still_fills_daily_minimum_in_configured_pool(self):
        gacha, state = self.make_gacha(pool='heavy', amount=5, tickets=2, clear_ticket=True)
        self.mock_deadline(gacha)
        self.assertTrue(gacha.gacha_run())
        self.assertEqual([('event', 2, 'ticket'), ('heavy', 3, 'cube')], state.orders)
        self.assertEqual([
            call(gacha.config, {'GachaTicket': -2}, '建造 event × 2'),
            call(gacha.config, {'Coin': -4500, 'Cube': -6}, '建造 heavy × 3'),
        ], self.record.call_args_list)

    def test_failed_clear_ticket_preparation_keeps_inventory_and_stops(self):
        for fail_batch in [1, 2]:
            with self.subTest(fail_batch=fail_batch):
                gacha, state = self.make_gacha(tickets=25, clear_ticket=True)
                self.mock_deadline(gacha)
                prepare = gacha.gacha_prep.side_effect
                attempts = 0

                def prepare_or_fail(count):
                    nonlocal attempts
                    attempts += 1
                    return prepare(count) if attempts < fail_batch else False

                gacha.gacha_prep.side_effect = prepare_or_fail
                with self.assertRaises(GameStuckError):
                    gacha.gacha_run()
                self.assertEqual(fail_batch, attempts)
                self.assertEqual(25 - 10 * (fail_batch - 1), gacha.build_ticket_count)
                self.assertEqual(gacha.build_ticket_count, state.tickets)
                self.assertEqual(fail_batch - 1, len(state.orders))
                self.assertEqual(fail_batch - 1, self.record.call_count)

    def test_failed_clear_ticket_submission_only_records_completed_batches(self):
        gacha, state = self.make_gacha(tickets=25, clear_ticket=True)
        self.mock_deadline(gacha)
        submit = gacha.gacha_submit.side_effect

        def submit_or_fail():
            if state.orders:
                raise GameStuckError('模拟第二批提交失败')
            submit()

        gacha.gacha_submit.side_effect = submit_or_fail
        with self.assertRaisesRegex(GameStuckError, '模拟第二批提交失败'):
            gacha.gacha_run()
        self.assertEqual([('event', 10, 'ticket')], state.orders)
        self.assertEqual(15, gacha.build_ticket_count)
        self.assertEqual(15, state.tickets)
        self.record.assert_called_once_with(gacha.config, {'GachaTicket': -10}, '建造 event × 10')

    def test_successful_ticket_batch_stays_successful_when_cube_preparation_fails(self):
        gacha, state = self.make_gacha(amount=3, tickets=1)
        prepare = gacha.gacha_prep.side_effect
        gacha.gacha_prep.side_effect = lambda count: prepare(count) if state.pool == 'event' else False
        self.assertTrue(gacha.gacha_run())
        self.assertEqual([('event', 1, 'ticket')], state.orders)
        self.record.assert_called_once_with(gacha.config, {'GachaTicket': -1}, '建造 event × 1')


if __name__ == '__main__':
    unittest.main()
