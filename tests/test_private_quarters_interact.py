"""宿舍房间就绪、每日互动及失败退出的状态循环回归。"""

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call, patch

from module.exception import GameStuckError
from module.private_quarters.assets import (
    PRIVATE_QUARTERS_INTERACT,
    PRIVATE_QUARTERS_INTERACT_CHECK,
    PRIVATE_QUARTERS_ROOM_BACK,
    PRIVATE_QUARTERS_ROOM_CHECK,
    PRIVATE_QUARTERS_ROOM_TARGET_CHECK_1,
    PRIVATE_QUARTERS_ROOM_TARGET_CHECK_2,
    PRIVATE_QUARTERS_ROOM_TARGET_CHECK_3,
    PRIVATE_QUARTERS_ROOM_TARGET_CLICK_AREA,
)
from module.private_quarters.private_quarters import PrivateQuarters


class PrivateQuartersInteractTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.
        self.frames = 0
        self.visible = set()
        self.enterContext(patch('module.base.timer.time', lambda: self.now))
        self.enterContext(patch('module.private_quarters.interact.logger'))
        self.enterContext(patch('module.private_quarters.private_quarters.logger'))
        self.task = object.__new__(PrivateQuarters)
        self.task.config = SimpleNamespace()
        self.task.device = SimpleNamespace(
            image=None, screenshot=Mock(side_effect=self.screenshot),
            click=Mock(), drag=Mock())
        self.task.appear = Mock(side_effect=lambda button, **kwargs: button in self.visible)
        self.task.interval_clear = Mock()
        self.task._pq_goto_room_seek = Mock(return_value=True)
        self.task._pq_goto_room_enter = Mock(return_value=True)
        self.task._pq_goto_room_exit = Mock()

    def screenshot(self):
        self.now += .5
        self.frames += 1
        if self.frames > 160:
            raise AssertionError('宿舍状态循环必须有限退出')

    def test_bubble_variants_allow_interaction_without_camera_drag(self):
        self.task.pq_interact = Mock()
        for bubble in (PRIVATE_QUARTERS_ROOM_TARGET_CHECK_1,
                       PRIVATE_QUARTERS_ROOM_TARGET_CHECK_2,
                       PRIVATE_QUARTERS_ROOM_TARGET_CHECK_3):
            with self.subTest(bubble=bubble.name):
                self.visible = {PRIVATE_QUARTERS_ROOM_CHECK, bubble}
                self.task.pq_interact.reset_mock()
                self.task.pq_execute_interact('taihou')
                self.task.pq_interact.assert_called_once_with()
                self.task.device.drag.assert_not_called()
                self.task.device.screenshot.assert_not_called()
                self.task._pq_goto_room_exit.assert_not_called()

    def test_camera_adjustment_checks_new_frame_before_interaction(self):
        self.visible = {PRIVATE_QUARTERS_ROOM_CHECK}
        self.task.pq_interact = Mock()

        def screenshot():
            self.screenshot()
            self.visible.add(PRIVATE_QUARTERS_ROOM_TARGET_CHECK_2)

        self.task.device.screenshot.side_effect = screenshot
        self.task.pq_execute_interact('taihou')
        self.task.device.drag.assert_called_once()
        self.task.device.screenshot.assert_called_once()
        self.task.pq_interact.assert_called_once_with()
        self.task._pq_goto_room_exit.assert_not_called()

    def test_missing_target_exhausts_room_retries_without_interaction(self):
        self.visible = {PRIVATE_QUARTERS_ROOM_CHECK}
        self.task.pq_interact = Mock()
        self.task.pq_execute_interact('taihou')
        self.assertEqual(self.task._pq_goto_room_enter.call_args_list, [call('taihou')] * 3)
        self.assertEqual(self.task._pq_goto_room_exit.call_count, 3)
        self.assertEqual(self.task.device.drag.call_count, 3)
        self.assertLess(self.now, 110.)
        self.task.pq_interact.assert_not_called()
        self.task.device.click.assert_not_called()

    def test_unknown_room_state_times_out_without_camera_drag(self):
        self.assertFalse(self.task._pq_target_appear())
        self.assertGreater(self.task.device.screenshot.call_count, 0)
        self.task.device.drag.assert_not_called()
        self.task.device.click.assert_not_called()

    def test_room_retry_recovers_when_target_becomes_ready(self):
        self.visible = {PRIVATE_QUARTERS_ROOM_CHECK}
        self.task.pq_interact = Mock()
        self.task._pq_goto_room_exit.side_effect = lambda: self.visible.add(
            PRIVATE_QUARTERS_ROOM_TARGET_CHECK_1)
        self.task.pq_execute_interact('taihou')
        self.assertEqual(self.task._pq_goto_room_enter.call_count, 2)
        self.task._pq_goto_room_exit.assert_called_once_with()
        self.task.pq_interact.assert_called_once_with()

    def test_rejected_room_entry_never_attempts_interaction(self):
        self.task._pq_goto_room_enter.return_value = False
        self.task.pq_interact = Mock()
        self.task.pq_execute_interact('taihou')
        self.task._pq_goto_room_enter.assert_called_once_with('taihou')
        self.task.appear.assert_not_called()
        self.task.pq_interact.assert_not_called()

    def test_watchdog_error_is_propagated(self):
        self.task.device.screenshot.side_effect = GameStuckError('测试截图看门狗')
        self.task.pq_interact = Mock()
        with self.assertRaises(GameStuckError):
            self.task.pq_execute_interact('taihou')
        self.task.pq_interact.assert_not_called()

    def test_ready_room_completes_three_interactions_and_exits(self):
        self.visible = {PRIVATE_QUARTERS_ROOM_CHECK, PRIVATE_QUARTERS_ROOM_TARGET_CHECK_1}

        def click(button):
            if button is PRIVATE_QUARTERS_ROOM_TARGET_CLICK_AREA:
                self.visible = {PRIVATE_QUARTERS_INTERACT}
            elif button is PRIVATE_QUARTERS_INTERACT:
                self.visible = {PRIVATE_QUARTERS_INTERACT_CHECK}
            elif button is PRIVATE_QUARTERS_ROOM_BACK:
                self.visible = {PRIVATE_QUARTERS_INTERACT}
            else:
                raise AssertionError(f'意外点击 {button.name}')

        self.task.device.click.side_effect = click
        self.task.pq_execute_interact('taihou')
        clicks = [args[0] for args, _ in self.task.device.click.call_args_list]
        self.assertEqual(clicks.count(PRIVATE_QUARTERS_INTERACT), 3)
        self.assertEqual(clicks.count(PRIVATE_QUARTERS_ROOM_BACK), 3)
        self.task._pq_goto_room_exit.assert_called_once_with()
        self.task.device.drag.assert_not_called()

    def test_exhausted_energy_exits_without_clicking_interact(self):
        self.visible = {PRIVATE_QUARTERS_ROOM_CHECK}
        self.task.pq_interact()
        self.task._pq_goto_room_exit.assert_called_once_with()
        self.task.device.click.assert_called()
        for args, _ in self.task.device.click.call_args_list:
            self.assertIs(args[0], PRIVATE_QUARTERS_ROOM_TARGET_CLICK_AREA)


if __name__ == '__main__':
    unittest.main()
