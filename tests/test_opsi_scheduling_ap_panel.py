"""用虚拟行动力面板验证首读与开箱合并，不连接游戏或真实配置。"""

import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.config.config import TaskEnd
from module.exception import GameStuckError
from module.os.operation_siren import OperationSiren
from module.os_handler.action_point import ACTION_POINT_BOX, ActionPointLimit
from module.os_handler.assets import ACTION_POINT_USE


class TestSchedulingActionPointPanel(unittest.TestCase):
    def setUp(self):
        self.actions = []
        self.game = SimpleNamespace(current=90, boxes=[10000, 0, 1, 33], open=False, selected=None)
        self.runner = OperationSiren.__new__(OperationSiren)
        self.runner.config = SimpleNamespace(
            task=SimpleNamespace(command='OpsiScheduling'),
            OS_ACTION_POINT_BOX_USE=True, OS_ACTION_POINT_PRESERVE=200,
            OpsiGeneral_BuyActionPointLimit=0, OpsiGeneral_OilLimit=0,
            OpsiMeowfficerFarming_StayInZone=True,
            is_task_enabled=Mock(return_value=False),
        )
        self.runner.device = Mock()
        self.runner.action_point_enter = Mock(side_effect=self.enter)
        self.runner.action_point_quit = Mock(side_effect=self.quit)
        self.runner.action_point_safe_get = Mock(side_effect=self.read)
        self.runner._is_in_action_point = Mock(side_effect=lambda: self.game.open)
        self.runner.action_point_set_button = Mock(side_effect=self.select)
        self.runner.appear_then_click = Mock(side_effect=self.use)
        self.runner.handle_popup_confirm = Mock(return_value=False)
        self.runner.interval_clear = Mock()
        self.runner.loop = lambda **kwargs: iter(range(5))
        self.runner.check_and_notify_action_point_threshold = Mock()
        self.runner.is_running_prevent_action_point_overflow_task = Mock(return_value=False)
        self.runner.get_yellow_coins = Mock(return_value=145321)
        self.now = datetime(2026, 10, 3, 23)
        for name, value in (
            ('current_time', self.now), ('get_server_next_update', self.now + timedelta(hours=1)),
        ):
            clock_patch = patch(f'module.os_handler.action_point.{name}', return_value=value)
            clock_patch.start()
            self.addCleanup(clock_patch.stop)

    def enter(self):
        self.assertFalse(self.game.open)
        self.game.open = True
        self.actions.append('enter')

    def quit(self):
        self.assertTrue(self.game.open)
        self.game.open = False
        self.actions.append('quit')

    def read(self):
        self.assertTrue(self.game.open)
        current = self.game.current
        self.runner._action_point_current = current
        self.runner._action_point_box = list(self.game.boxes)
        self.runner._action_point_total = current
        if self.runner.config.OS_ACTION_POINT_BOX_USE:
            self.runner._action_point_total += sum(self.game.boxes[i] * ACTION_POINT_BOX[i] for i in (1, 2, 3))
        self.actions.append(f'read:{current}')

    def select(self, index):
        self.game.selected = index
        self.actions.append(f'select:{index}')

    def use(self, button, **kwargs):
        if button is ACTION_POINT_USE and self.game.selected is not None:
            index = self.game.selected
            self.game.selected = None
            self.game.boxes[index] -= 1
            self.game.current += ACTION_POINT_BOX[index]
            self.actions.append('use')
            return True
        return False

    def prepare(self, avoid_ap_overflow=True):
        fresh_ap = self.runner._get_scheduling_action_point(keep_open=True)
        self.assertEqual(self.actions, ['enter', f'read:{self.game.current}'])
        result = self.runner._prepare_scheduling_action_point(
            fresh_ap, cost=120, avoid_ap_overflow=avoid_ap_overflow,
        )
        self.runner._close_scheduling_action_point()
        return result

    def test_cl1_90_to_140_uses_one_panel_and_reads_only_before_and_after_box(self):
        self.assertEqual(self.prepare(), (3440, 140))
        self.assertEqual(self.actions, ['enter', 'read:90', 'select:2', 'use', 'read:140', 'quit'])
        self.runner.action_point_enter.assert_called_once()
        self.runner.action_point_quit.assert_called_once()

    def test_cl1_100_to_119_does_not_open_any_box(self):
        for current in (100, 119):
            with self.subTest(current=current):
                self.actions.clear()
                self.game.current = current
                result = self.prepare()
                self.assertEqual(result[1], current)
                self.assertEqual(self.actions, ['enter', f'read:{current}', 'quit'])

    def test_meow_119_still_replenishes_to_its_120_start_line(self):
        self.game.current = 119
        self.assertEqual(self.prepare(avoid_ap_overflow=False), (3469, 169))
        self.assertEqual(self.actions, ['enter', 'read:119', 'select:2', 'use', 'read:169', 'quit'])

    def test_cl1_entry_reuses_replenished_read_without_reopening_panel(self):
        fresh_ap = self.runner._get_scheduling_action_point(keep_open=True)
        self.runner.config.OpsiHazard1Leveling_TargetZone = 0
        self.runner.config.OpsiHazard1Leveling_RecordSeaMiles = False
        self.runner.config.OpsiFleet_Fleet = 1
        self.runner.config.override = Mock()
        self.runner.zone = SimpleNamespace(zone_id=22, hazard_level=1)
        self.runner.is_zone_name_hidden = True
        with (
            patch.object(self.runner, 'get_current_zone'),
            patch.object(self.runner, 'fleet_set'),
            patch.object(self.runner, 'is_running_smart_scheduling_task', return_value=True),
            patch.object(self.runner, '_record_ap_and_coins'),
            patch.object(self.runner, '_cl1_run_battle'),
            patch.object(self.runner, 'action_point_set') as reopen,
        ):
            self.runner.run_hazard1_leveling_once(ap_preserve=200, fresh_ap=fresh_ap)
        reopen.assert_not_called()
        self.assertEqual(self.actions, ['enter', 'read:90', 'select:2', 'use', 'read:140', 'quit'])

    def test_preserve_limit_closes_without_using_resources(self):
        self.runner.config.OS_ACTION_POINT_PRESERVE = 3440
        with self.assertRaises(ActionPointLimit):
            self.prepare()
        self.assertEqual(self.actions, ['enter', 'read:90', 'quit'])
        self.assertFalse(self.runner._scheduling_ap_panel_open)

    def test_changed_box_policy_requires_new_read_in_same_panel(self):
        fresh_ap = self.runner._get_scheduling_action_point(keep_open=True)
        self.runner.config.OS_ACTION_POINT_BOX_USE = False
        self.runner.config.OS_ACTION_POINT_PRESERVE = 0
        with self.assertRaises(ActionPointLimit):
            self.runner._prepare_scheduling_action_point(fresh_ap, cost=120, avoid_ap_overflow=True)
        self.assertEqual(self.actions, ['enter', 'read:90', 'read:90', 'quit'])
        self.assertEqual(self.game.current, 90)

    def test_closed_panel_keeps_independent_task_path(self):
        self.assertEqual(self.runner._prepare_scheduling_action_point((3440, 90), cost=120), (3440, 90))
        self.assertEqual(self.actions, [])

    def test_normal_decision_return_closes_unused_first_panel(self):
        self.runner._run_smart_scheduling_decision = Mock(return_value=None)
        self.runner.run_smart_scheduling_once()
        self.assertEqual(self.actions, ['enter', 'read:90', 'quit'])
        self.runner._run_smart_scheduling_decision.assert_called_once_with(145321, 3440, 90)

    def test_task_end_closes_unused_first_panel(self):
        self.runner._run_smart_scheduling_decision = Mock(side_effect=TaskEnd)
        with self.assertRaises(TaskEnd):
            self.runner.run_smart_scheduling_once()
        self.assertEqual(self.actions, ['enter', 'read:90', 'quit'])

    def test_game_stuck_preserves_original_recovery_without_extra_clicks(self):
        self.runner._run_smart_scheduling_decision = Mock(side_effect=GameStuckError('测试卡死'))
        with self.assertRaisesRegex(GameStuckError, '测试卡死'):
            self.runner.run_smart_scheduling_once()
        self.assertEqual(self.actions, ['enter', 'read:90'])
        self.assertFalse(self.runner._scheduling_ap_panel_open)

    def test_smart_explore_closes_panel_before_globe_navigation(self):
        self.runner._get_scheduling_action_point(keep_open=True)
        self.runner.config.temporary = lambda **kwargs: patch.object(self.runner.config, 'OS_ACTION_POINT_PRESERVE', 0)
        self.runner._save_smart_explore_state = Mock()
        self.runner.handle_first_auto_search = Mock()
        self.runner.globe_goto = Mock(side_effect=lambda zone: self.assertFalse(self.game.open))
        self.runner.port_enter = Mock()
        self.runner.port_quit = Mock()
        state = dict(next=[0, 0, 0], attempts=0)
        self.runner._run_smart_explore_node(state, 0)
        self.assertEqual(self.actions, ['enter', 'read:90', 'quit'])
        self.runner.globe_goto.assert_called_once_with(0)

    def run_meow_entry(self, *, zone_id=22, target_ids=(22,)):
        fresh_ap = self.runner._get_scheduling_action_point(keep_open=True)
        self.runner.zone = SimpleNamespace(zone_id=zone_id)
        self.runner.is_zone_name_hidden = True
        self.runner._meow_target_zone_list = [SimpleNamespace(zone_id=target_id) for target_id in target_ids]
        with (
            patch('module.base.debug_clip.cleanup_clips_if_due'),
            patch.object(self.runner, '_meow_handle_stay_in_zone') as stay,
            patch.object(self.runner, '_meow_handle_target_zone_search') as target,
        ):
            self.runner.run_meowfficer_farming_once(
                ap_preserve=200, ap_checked=True, prepared=True, fresh_ap=fresh_ap,
            )
        return stay, target

    def test_meow_same_single_zone_replenishes_in_first_panel_and_forwards_new_read(self):
        stay, target = self.run_meow_entry()
        self.assertEqual(self.actions, ['enter', 'read:90', 'select:2', 'use', 'read:140', 'quit'])
        self.assertEqual(stay.call_args.kwargs['fresh_ap'], (3440, 140))
        target.assert_not_called()

    def test_meow_different_zone_closes_first_panel_without_premature_box_use(self):
        stay, target = self.run_meow_entry(zone_id=23)
        self.assertEqual(self.actions, ['enter', 'read:90', 'quit'])
        target.assert_not_called()
        stay.assert_called_once()

    def test_meow_multi_zone_closes_first_panel_before_zone_search(self):
        stay, target = self.run_meow_entry(target_ids=(22, 23))
        self.assertEqual(self.actions, ['enter', 'read:90', 'quit'])
        stay.assert_not_called()
        target.assert_called_once()


if __name__ == '__main__':
    unittest.main()
