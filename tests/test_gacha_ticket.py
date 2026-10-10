"""每日建造使用模拟页面验证卡池选择、支付资源和队列返回流程。"""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

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
        self.record = self.enterContext(patch('module.statistics.resource_flow.record'))

    def make_gacha(self, pool='light', amount=1, tickets=0, use_ticket=True,
                   use_drill=False, event_available=True, ticket_visible=True, coins=10000):
        gacha = RewardGacha.__new__(RewardGacha)
        gacha.config = SimpleNamespace(
            Gacha_Pool=pool, Gacha_Amount=amount, Gacha_UseTicket=use_ticket,
            Gacha_UseDrill=use_drill, update=Mock(), task_delay=Mock())
        gacha.device = SimpleNamespace(image=object())
        state = SimpleNamespace(page='build', pool='light', tickets=tickets, orders=[], visits=[])
        self.record.reset_mock()
        self.ticket_ocr.reset_mock()
        self.ticket_ocr.ocr.side_effect = lambda image: state.tickets

        def flush_queue():
            state.page = 'build'

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
            payment = 'ticket' if state.pool == 'event' and state.tickets > 0 else 'cube'
            if payment == 'ticket':
                self.assertLessEqual(count, state.tickets, '建造次数不能超出现有建造券')
            state.pending = (state.pool, count, payment)
            state.page = 'confirm'
            return True

        def submit():
            self.assertEqual('confirm', state.page)
            state.orders.append(state.pending)
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
                gacha, state = self.make_gacha(pool=pool, amount=2, tickets=5)
                self.assertTrue(gacha.gacha_run())
                self.assertEqual([('event', 2, 'ticket')], state.orders)
                self.assertEqual(['event'], state.visits)
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
                self.assertEqual(['event', pool], state.visits)
                self.assertEqual(pool, gacha.config.Gacha_Pool)
                gacha.gacha_side_navbar_ensure.assert_called_once_with(upper=1)
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
        self.assertEqual(['event'], state.visits)
        self.record.assert_not_called()

    def test_ticket_submission_failure_does_not_record_or_start_cube_order(self):
        gacha, state = self.make_gacha(amount=3, tickets=1)
        gacha.gacha_submit.side_effect = RuntimeError('模拟提交失败')
        with self.assertRaisesRegex(RuntimeError, '模拟提交失败'):
            gacha.gacha_run()
        self.assertEqual([], state.orders)
        self.assertEqual(['event'], state.visits)
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


if __name__ == '__main__':
    unittest.main()
