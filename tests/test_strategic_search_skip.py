"""计划作战启动和确认弹窗的离线回归，不连接游戏。"""

import unittest
from unittest.mock import Mock, call

from module.os_handler.strategic import StrategicSearchHandler


class TestStrategicSearchSkipCheck(unittest.TestCase):
    """用 Mock 替换面板交互，验证侵蚀一配置对启动流程的分派。"""

    def make_handler(self, skip):
        handler = StrategicSearchHandler.__new__(StrategicSearchHandler)
        handler.config = Mock()
        handler.config.cross_get.return_value = skip
        handler.strategy_search_enter = Mock()
        handler.strategic_search_set_tab = Mock()
        handler.strategic_search_set_option = Mock(return_value=True)
        handler.strategic_search_confirm = Mock(return_value=True)
        return handler

    def test_default_still_checks_options(self):
        handler = self.make_handler(skip=False)
        self.assertTrue(handler.strategic_search_start(skip_first_screenshot=True))
        handler.strategy_search_enter.assert_called_once_with()
        handler.strategic_search_set_tab.assert_called_once_with()
        handler.strategic_search_set_option.assert_called_once_with()
        handler.strategic_search_confirm.assert_called_once_with()

    def test_skip_check_confirms_directly(self):
        handler = self.make_handler(skip=True)
        self.assertTrue(handler.strategic_search_start(skip_first_screenshot=True))
        handler.strategy_search_enter.assert_called_once_with()
        handler.strategic_search_set_tab.assert_called_once_with()
        handler.strategic_search_set_option.assert_not_called()
        handler.strategic_search_confirm.assert_called_once_with()

    def test_failed_option_check_retries(self):
        handler = self.make_handler(skip=False)
        handler.strategic_search_set_option = Mock(side_effect=[False, True])
        self.assertTrue(handler.strategic_search_start(skip_first_screenshot=True))
        self.assertEqual(handler.strategic_search_set_option.call_count, 2)
        handler.strategic_search_confirm.assert_called_once_with()

    def test_confirmation_failure_is_not_reported_as_success(self):
        handler = self.make_handler(skip=True)
        handler.strategic_search_confirm = Mock(return_value=False)
        self.assertFalse(handler.strategic_search_start())
        self.assertEqual(handler.strategic_search_confirm.call_count, 3)

    def test_gives_up_after_three_failures(self):
        handler = self.make_handler(skip=False)
        handler.strategic_search_set_option = Mock(return_value=False)
        self.assertFalse(handler.strategic_search_start(skip_first_screenshot=True))
        self.assertEqual(handler.strategic_search_set_option.call_count, 3)
        handler.strategic_search_confirm.assert_not_called()


class TestStrategicSearchConfirm(unittest.TestCase):
    """确认计划作战后，继续处理可能出现的指挥喵召回弹窗。"""

    def test_confirms_secondary_popup_and_waits_for_map(self):
        handler = StrategicSearchHandler.__new__(StrategicSearchHandler)
        handler.loop = Mock(return_value=range(3))
        handler.appear = Mock(side_effect=[True, False, False])
        handler.handle_popup_confirm = Mock(side_effect=[True, True, False])
        handler.is_in_map = Mock(return_value=True)

        self.assertTrue(handler.strategic_search_confirm())
        self.assertEqual(handler.handle_popup_confirm.call_args_list, [
            call(offset=(30, 30), name='STRATEGIC_SEARCH'),
            call(offset=(30, 30), name='STRATEGIC_SEARCH_MEOWFFICER'),
            call(offset=(30, 30), name='STRATEGIC_SEARCH_MEOWFFICER'),
        ])
        handler.is_in_map.assert_called_once_with()

    def test_handles_multiple_secondary_popups_until_map(self):
        handler = StrategicSearchHandler.__new__(StrategicSearchHandler)
        handler.loop = Mock(return_value=range(4))
        handler.appear = Mock(side_effect=[True, False, False, False])
        handler.handle_popup_confirm = Mock(side_effect=[True, True, True, False])
        handler.is_in_map = Mock(return_value=True)

        self.assertTrue(handler.strategic_search_confirm())
        self.assertEqual(handler.handle_popup_confirm.call_count, 4)
        handler.is_in_map.assert_called_once_with()

    def test_waits_for_map_while_confirmation_is_on_cooldown(self):
        handler = StrategicSearchHandler.__new__(StrategicSearchHandler)
        handler.loop = Mock(return_value=range(4))
        handler.appear = Mock(side_effect=[True, False, False, False])
        handler.handle_popup_confirm = Mock(side_effect=[True, False, True, False])
        handler.is_in_map = Mock(side_effect=[False, True])

        self.assertTrue(handler.strategic_search_confirm())
        self.assertEqual(handler.handle_popup_confirm.call_count, 4)
        self.assertEqual(handler.is_in_map.call_count, 2)

    def test_does_not_confirm_unknown_popup_before_search_panel(self):
        handler = StrategicSearchHandler.__new__(StrategicSearchHandler)
        handler.loop = Mock(return_value=range(1))
        handler.appear = Mock(return_value=False)
        handler.handle_popup_confirm = Mock()
        handler.is_in_map = Mock(return_value=True)

        self.assertTrue(handler.strategic_search_confirm())
        handler.handle_popup_confirm.assert_not_called()

    def test_returns_to_map_without_second_popup(self):
        handler = StrategicSearchHandler.__new__(StrategicSearchHandler)
        handler.loop = Mock(return_value=range(2))
        handler.appear = Mock(side_effect=[True, False])
        handler.handle_popup_confirm = Mock(side_effect=[True, False])
        handler.is_in_map = Mock(return_value=True)

        self.assertTrue(handler.strategic_search_confirm())
        self.assertEqual(handler.handle_popup_confirm.call_args_list, [
            call(offset=(30, 30), name='STRATEGIC_SEARCH'),
            call(offset=(30, 30), name='STRATEGIC_SEARCH_MEOWFFICER'),
        ])
        handler.is_in_map.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
