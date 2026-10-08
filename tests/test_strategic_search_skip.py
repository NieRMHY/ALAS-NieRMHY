"""计划作战快速模式：跳过选项滑动检查的回归，不连接游戏。"""

import unittest
from unittest.mock import Mock

from module.os_handler.strategic import StrategicSearchHandler


class TestStrategicSearchSkipCheck(unittest.TestCase):
    """用 Mock 替换面板交互，验证 OpsiGeneral.SkipStrategicSearchCheck 对启动流程的分派。"""

    def make_handler(self, skip):
        handler = StrategicSearchHandler.__new__(StrategicSearchHandler)
        handler.config = Mock(OpsiGeneral_SkipStrategicSearchCheck=skip)
        handler.strategy_search_enter = Mock()
        handler.strategic_search_set_tab = Mock()
        handler.strategic_search_set_option = Mock(return_value=True)
        handler.strategic_search_confirm = Mock()
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

    def test_gives_up_after_three_failures(self):
        handler = self.make_handler(skip=False)
        handler.strategic_search_set_option = Mock(return_value=False)
        self.assertFalse(handler.strategic_search_start(skip_first_screenshot=True))
        self.assertEqual(handler.strategic_search_set_option.call_count, 3)
        handler.strategic_search_confirm.assert_not_called()


if __name__ == '__main__':
    unittest.main()
