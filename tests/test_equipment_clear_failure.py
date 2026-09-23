"""清空失败不能进入装备码输入或确认，也不能绕过人工接管。"""

import unittest
from unittest.mock import Mock, PropertyMock, call, patch

from module.campaign.ambush_1_1 import Ambush11
from module.campaign.gems_farming import GemsEquipmentHandler
from module.equipment.equipment_code import EMPTY_CODE, EquipmentCodeHandler
from module.exception import RequestHumanTakeover


class EquipmentClearFailureTests(unittest.TestCase):
    def make_handler(self, empty_states):
        handler = object.__new__(EquipmentCodeHandler)
        # 每次清空重试提供两帧，真实清空状态循环仍负责检查和点击。
        handler.loop = Mock(side_effect=lambda **kwargs: iter((None, None)))
        handler.is_code_preview_empty = Mock(side_effect=empty_states)
        handler.appear_then_click = Mock(return_value=True)
        events = Mock()
        for name in ('_code_input', '_code_confirm', 'handle_storage_full'):
            setattr(handler, name, getattr(events, name))
        handler._code_input.return_value = True
        handler._code_confirm.return_value = True
        return handler, events

    def test_clear_timeout_exhausts_retries_without_input_or_confirm(self):
        for code in (None, EMPTY_CODE, '有效装备码'):
            with self.subTest(code=code):
                handler, events = self.make_handler([False] * 10)
                self.assertFalse(handler._code_apply(code))
                self.assertEqual(handler.loop.call_count, 5)
                self.assertEqual(events.mock_calls, [])

    def test_clear_retry_then_empty_preview_allows_confirmation(self):
        for code in (None, EMPTY_CODE, '有效装备码'):
            with self.subTest(code=code):
                handler, events = self.make_handler([False, False, False, True])
                self.assertTrue(handler._code_apply(code))
                expected = [] if code in (None, EMPTY_CODE) else [call._code_input(code)]
                self.assertEqual(events.mock_calls, expected + [call._code_confirm()])
                self.assertEqual(handler.loop.call_count, 2)

    def test_confirmation_failure_still_handles_storage_and_retries(self):
        handler, events = self.make_handler([True, True])
        handler._code_confirm.side_effect = [False, True]
        self.assertTrue(handler._code_apply())
        self.assertEqual(events.mock_calls, [call._code_confirm(), call.handle_storage_full(),
                                            call._code_confirm()])

    def test_input_failure_retries_without_confirmation(self):
        handler, events = self.make_handler([True, True])
        handler._code_input.side_effect = [False, True]
        self.assertTrue(handler._code_apply('有效装备码'))
        self.assertEqual(events.mock_calls, [call._code_input('有效装备码'),
                                            call._code_input('有效装备码'), call._code_confirm()])

    def test_clear_failure_reaches_campaign_human_takeover(self):
        for campaign in (GemsEquipmentHandler, Ambush11):
            with self.subTest(campaign=campaign.__name__):
                handler, events = self.make_handler([False] * 10)
                handler.equipment_code_supported = Mock(return_value=True)
                handler._code_enter = Mock()
                handler.current_ship = Mock(return_value='测试舰船')
                with patch.object(EquipmentCodeHandler, 'equipment_code_export_to_config',
                                  new_callable=PropertyMock, return_value=False):
                    with self.assertRaises(RequestHumanTakeover):
                        campaign.clear_all_equip(handler)
                self.assertEqual(events.mock_calls, [])


if __name__ == '__main__':
    unittest.main()
