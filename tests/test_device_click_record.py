"""离线验证真实设备的重复操作阈值与模式识别，不连接设备。"""

import collections
import unittest
from unittest.mock import Mock, patch

from module.device.device import Device
from module.exception import GameTooManyClickError


class ClickRecordTests(unittest.TestCase):
    def setUp(self):
        self.device = Device.__new__(Device)
        self.device.click_record = collections.deque(maxlen=Device.click_record.maxlen)
        self.device.stuck_record_clear = Mock()
        self.enterContext(patch('module.device.device.show_function_call'))
        self.enterContext(patch('module.device.device.logger'))

    def repeat(self, names):
        for name in names:
            self.device.handle_control_check(name)

    def test_same_button_and_experience_page_trigger_at_fifty(self):
        for name in ('TEST_BUTTON', 'EXP_INFO_S'):
            with self.subTest(name=name):
                self.repeat([name] * 49)
                with self.assertRaisesRegex(GameTooManyClickError, '按钮点击次数过多'):
                    self.repeat([name])
                self.assertEqual(list(self.device.click_record), [])

    def test_alternating_pair_triggers_at_fifty_total_operations(self):
        self.repeat(['A', 'B'] * 24 + ['A'])
        with self.assertRaisesRegex(GameTooManyClickError, '两个按钮交替点击次数过多'):
            self.repeat(['B'])

    def test_two_frequent_buttons_without_an_alternating_pattern_are_allowed(self):
        self.repeat(['A'] * 25 + ['B'] * 25)
        self.assertEqual(len(self.device.click_record), 50)

    def test_another_operation_breaks_the_previous_repeat(self):
        self.repeat(['A'] * 49 + ['PROGRESS'] + ['A'] * 49)
        with self.assertRaises(GameTooManyClickError):
            self.repeat(['A'])

    def test_confirmed_state_progress_clears_both_repeat_patterns(self):
        for sequence in (['A'] * 49, ['A', 'B'] * 24 + ['A']):
            with self.subTest(sequence=sequence[:2]):
                self.repeat(sequence)
                self.device.click_record_clear()
                self.repeat(sequence)
                self.device.click_record_clear()

    def test_map_swipes_are_left_to_camera_progress_detection(self):
        self.repeat(['MAP_SWIPE_6_5'] * 60)
        self.repeat(['MAP_SWIPE_6_5', 'MAP_SWIPE_-6_-5'] * 30)
        self.repeat(['A'] * 49)
        with self.assertRaises(GameTooManyClickError):
            self.repeat(['A'])

    def test_empty_and_removed_records_are_safe(self):
        self.device.click_record_check()
        self.repeat(['A'] * 49)
        self.assertEqual(self.device.click_record_remove('A'), 49)
        self.device.click_record_check()
        self.repeat(['A'] * 49)


if __name__ == '__main__':
    unittest.main()
