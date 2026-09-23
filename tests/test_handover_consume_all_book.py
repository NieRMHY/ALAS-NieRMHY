"""作战委托：一键消耗委托书的本周记录与放弃逻辑。

记录现在存的是「上一次执行的时刻」（可见、可手改的 datetime），判断「是不是
本周」时还原成 ISO 周 key。历史上它存过 `2026W37` 这种字符串，而配置系统会把它
按 ISO 周日期解析成该周周一的 datetime（`datetime.fromisoformat('2026W37')`），
两种形态都要能正确还原，否则同一周会被反复当成「还没触发过」。
"""

import json
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from module.config.deep import deep_get
from module.config.utils import filepath_args, parse_value
from module.handover.handover import HANDOVER_MAINTAIN_CHECK_MINUTES, OperationHandover

# 2026-09-12 是周六，ISO 第 37 周的第一天（周一）是 2026-09-07
NOW = datetime(2026, 9, 12, 11, 30)
NOW_WEEK = '2026W37'
# 旧版本存 `2026W37` 时，配置系统写盘再读回来的实际形态
LEGACY_RECORD = datetime(2026, 9, 7)
# 现在存的是执行时刻
RUN_RECORD = datetime(2026, 9, 10, 11, 13)


class FakeHandover:
    """只挂纯逻辑方法的桩，避免构造需要 config/device 的 ModuleBase。"""

    handover_week_key = staticmethod(OperationHandover.handover_week_key)
    handover_consume_all_book_record_key = OperationHandover.handover_consume_all_book_record_key
    handover_consume_all_book_state = OperationHandover.handover_consume_all_book_state
    handover_consume_all_book_waiting = OperationHandover.handover_consume_all_book_waiting
    handover_consume_all_book_trigger = OperationHandover.handover_consume_all_book_trigger
    handover_consume_all_book_next_time = OperationHandover.handover_consume_all_book_next_time
    handover_consume_all_book = OperationHandover.handover_consume_all_book
    handover_consume_all_book_record = OperationHandover.handover_consume_all_book_record
    handover_consume_all_book_give_up = OperationHandover.handover_consume_all_book_give_up
    handover_idle_time = OperationHandover.handover_idle_time

    def __init__(self, record=None, weekday='sat', time='11:13', maintain=False):
        self.config = SimpleNamespace(
            OperationHandover_ConsumeAllBook=True,
            OperationHandover_ConsumeAllBookWeekday=weekday,
            OperationHandover_ConsumeAllBookTime=time,
            OperationHandover_ConsumeAllBookRecord=record,
            OperationHandover_MaintainOverride=maintain,
        )


class TestConsumeAllBookRecord(unittest.TestCase):
    def patch_now(self):
        return patch('module.handover.handover.current_time', return_value=NOW)

    def test_week_key_of_parsed_record(self):
        # 记录被解析成周一那天，仍要还原成同一周
        self.assertEqual(OperationHandover.handover_week_key(LEGACY_RECORD), NOW_WEEK)

    def test_config_round_trip(self):
        # 走真实配置系统：这个配置项现在是可见的 datetime，写进去读回来必须还是
        # 同一个时刻，并且能还原成本周
        with open(filepath_args(), encoding='utf-8') as f:
            args = json.load(f)
        data = deep_get(args, keys='OperationHandover.OperationHandover.ConsumeAllBookRecord')
        self.assertEqual(data.get('type'), 'datetime')
        self.assertEqual(data.get('display'), None)

        parsed = parse_value(RUN_RECORD, data=data)
        self.assertEqual(parsed, RUN_RECORD)

        fake = FakeHandover(record=parsed)
        self.assertEqual(fake.handover_consume_all_book_record_key(), NOW_WEEK)
        with self.patch_now():
            self.assertEqual(fake.handover_consume_all_book_state(), (False, '本周已处理过'))

    def test_record_key_accepts_both_forms(self):
        for record in [NOW_WEEK, LEGACY_RECORD, RUN_RECORD]:
            with self.subTest(record=record):
                fake = FakeHandover(record=record)
                self.assertEqual(fake.handover_consume_all_book_record_key(), NOW_WEEK)

    def test_used_week_does_not_trigger(self):
        # 关键回归：不论存的是旧版周 key、被解析成日期的旧值，还是执行时刻，
        # 只要落在本周就必须算「本周已处理过」
        for record in [NOW_WEEK, LEGACY_RECORD, RUN_RECORD]:
            with self.subTest(record=record):
                fake = FakeHandover(record=record)
                with self.patch_now():
                    self.assertEqual(fake.handover_consume_all_book_state(), (False, '本周已处理过'))
                    self.assertFalse(fake.handover_consume_all_book_waiting())

    def test_fresh_week_triggers(self):
        fake = FakeHandover(record=None)
        with self.patch_now():
            self.assertEqual(fake.handover_consume_all_book_state(), (True, ''))
            self.assertTrue(fake.handover_consume_all_book_waiting())


class TestConsumeAllBookFailure(unittest.TestCase):
    def test_no_book_returns_zero(self):
        fake = FakeHandover()
        fake.handover_count_max = lambda: 140
        fake.handover_click_until_stable = lambda *args, **kwargs: 0
        fake.handover_input_count = lambda count: self.fail('没有委托书时不该改成这个次数')
        self.assertEqual(OperationHandover.handover_consume_all_book(fake), 0)

    def test_ui_failure_returns_minus_one(self):
        fake = FakeHandover()
        fake.handover_count_max = lambda: -1
        self.assertEqual(OperationHandover.handover_consume_all_book(fake), -1)

    def test_input_failure_returns_minus_one(self):
        fake = FakeHandover()
        fake.handover_count_max = lambda: 140
        fake.handover_click_until_stable = lambda *args, **kwargs: 3
        fake.handover_input_count = lambda count: False
        self.assertEqual(OperationHandover.handover_consume_all_book(fake), -1)

    def test_book_count_returned_on_success(self):
        fake = FakeHandover()
        fake.handover_count_max = lambda: 140
        fake.handover_click_until_stable = lambda *args, **kwargs: 3
        fake.handover_input_count = lambda count: count == 3
        self.assertEqual(OperationHandover.handover_consume_all_book(fake), 3)


class TestConsumeAllBookGiveUp(unittest.TestCase):
    def test_give_up_records_week_and_idles(self):
        fake = FakeHandover(record=None)
        calls = []
        fake.handover_commission_clear = lambda: calls.append('clear')
        fake.handover_idle_delay = lambda maintain, queried=True: calls.append(('idle', maintain, queried))

        with patch('module.handover.handover.current_time', return_value=NOW):
            fake.handover_consume_all_book_give_up('没有可投入的作战全权委托书', None)

        # 记录的是执行时刻，判断本周时再还原成周 key
        record = fake.config.OperationHandover_ConsumeAllBookRecord
        self.assertEqual(record, NOW.replace(microsecond=0))
        self.assertEqual(fake.handover_week_key(record), NOW_WEEK)
        # 放弃本周前要先清掉旧的委托结束时间，否则下一次还会白进一次游戏
        self.assertEqual(calls, ['clear', ('idle', None, True)])

        # 放弃之后本周不再触发，下一次重试要等到下周
        with patch('module.handover.handover.current_time', return_value=NOW):
            self.assertEqual(fake.handover_consume_all_book_state(), (False, '本周已处理过'))
            self.assertFalse(fake.handover_consume_all_book_waiting())


class TestMaintainIdleTime(unittest.TestCase):
    """委托次数为 0、只等维护时的排期。

    查到公告、今天又没有还没开始的维护时，今天就不必再看，排到第二天 0 点；
    没查到公告才隔 HANDOVER_MAINTAIN_CHECK_MINUTES 分钟重试。
    """

    def idle(self, maintain, queried, monkey=None):
        fake = FakeHandover(record=RUN_RECORD, maintain=True)
        if monkey is not None:
            fake.handover_consume_all_book_next_time = lambda: monkey
        with patch('module.handover.handover.current_time', return_value=NOW):
            return fake.handover_idle_time(maintain, queried)

    def test_queried_without_maintenance_waits_until_tomorrow(self):
        self.assertEqual(self.idle(None, True), datetime(2026, 9, 13, 0, 0))

    def test_queried_with_started_maintenance_waits_until_tomorrow(self):
        # 今天的维护已经开始过了，今天同样不用再看
        self.assertEqual(self.idle(datetime(2026, 9, 12, 10, 0), True), datetime(2026, 9, 13, 0, 0))

    def test_failed_query_retries_soon(self):
        self.assertEqual(self.idle(None, False), NOW + timedelta(minutes=HANDOVER_MAINTAIN_CHECK_MINUTES))

    def test_earlier_candidate_wins(self):
        # 下次一键消耗就在两小时后，比明天 0 点早，取它
        soon = NOW + timedelta(hours=2)
        self.assertEqual(self.idle(None, True, monkey=soon), soon)


if __name__ == '__main__':
    unittest.main()
