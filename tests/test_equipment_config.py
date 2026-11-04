"""任务换装的配置预检、接口兼容和状态交接回归。"""

import unittest
from contextlib import nullcontext
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

import yaml

from module.combat.combat import BATTLE_PREPARATION, Combat
from module.equipment.assets import FLEET_REORGANIZE, FLEET_SAVE
from module.equipment.equipment_code import EquipmentCodeHandler
from module.equipment.equipment_config import POSITION_BUTTON, EquipmentConfigHandler
from module.exception import GameStuckError, RequestHumanTakeover
from module.exercise.exercise import Exercise
from module.ui.assets import EXERCISE_CHECK


# 离线流程测试使用的合法格式，不对应真实账号装备。
BEFORE_CODE = 'MTExLzIyMi8zMzMvMC8wXDA='
AFTER_CODE = 'NDQ0LzU1NS82NjYvMC8wXDA='


def make_handler(positions=None, clear=True, cls=EquipmentConfigHandler):
    handler = object.__new__(cls)
    data = {position: {'before': None, 'after': None} for position in POSITION_BUTTON}
    data.update(positions or {'flagship': {'before': BEFORE_CODE, 'after': AFTER_CODE}})
    handler.config = SimpleNamespace(
        Equipment_Enable=True,
        Equipment_ClearBeforeApply=clear,
        Equipment_Config=yaml.safe_dump(data),
        Emulator_ControlMethod='minitouch',
    )
    handler.device = SimpleNamespace(click=Mock())
    handler.ensure_reorganize = Mock()
    handler.ensure_save = Mock()
    handler.equip_enter = Mock()
    handler.ui_back = Mock()
    handler._code_enter = Mock()
    handler._code_apply = Mock(return_value=True)
    return handler


class EquipmentConfigTests(unittest.TestCase):
    def test_combat_keeps_named_equipment_code_interface(self):
        # Combat 的所有子类都必须继续支持按舰船名称备份及恢复装备。
        self.assertIs(Combat.code_clear, EquipmentCodeHandler.code_clear)
        self.assertIs(Combat.code_apply, EquipmentCodeHandler.code_apply)

    def test_combat_named_code_backup_and_transfer_keep_original_behavior(self):
        handler = make_handler(cls=Combat)
        handler.config.EquipmentCode_ExportToConfig = True
        handler.config.EquipmentCode_Config = yaml.safe_dump({'source': None, 'target': None})
        handler._code_export = Mock(return_value=BEFORE_CODE)
        self.assertTrue(handler.code_clear(name='source'))
        self.assertEqual(yaml.safe_load(handler.config.EquipmentCode_Config)['source'], BEFORE_CODE)
        self.assertEqual(handler.last_code, BEFORE_CODE)
        self.assertTrue(handler.code_apply(name='target'))
        handler._code_apply.assert_called_with(code=BEFORE_CODE)
        self.assertIsNone(handler.last_code)

    def test_invalid_codes_are_rejected_before_navigation_or_clearing(self):
        for phase in ('before', 'after'):
            for value in ('invalid', 12345, True, [], {}):
                with self.subTest(phase=phase, value=value):
                    handler = make_handler({'tail': {'before': BEFORE_CODE, 'after': AFTER_CODE}})
                    data = yaml.safe_load(handler.config.Equipment_Config)
                    data['tail'][phase] = value
                    handler.config.Equipment_Config = yaml.safe_dump(data)
                    with self.assertRaises(RequestHumanTakeover):
                        handler.equipment_handle_before()
                    handler.ensure_reorganize.assert_not_called()
                    handler.equip_enter.assert_not_called()
                    handler._code_apply.assert_not_called()

    def test_malformed_config_is_rejected_before_navigation(self):
        for raw in ('flagship: [', '42', '[1, 2]', 'flagship: []', 'flagshpi: null',
                    'flagship:\n  befor: null'):
            with self.subTest(raw=raw):
                handler = make_handler()
                handler.config.Equipment_Config = raw
                with self.assertRaises(RequestHumanTakeover):
                    handler.equipment_handle_before()
                handler.ensure_reorganize.assert_not_called()

    def test_blank_codes_disable_position_and_nonempty_codes_are_trimmed(self):
        handler = make_handler({
            'flagship': {'before': f'  {BEFORE_CODE}  ', 'after': f' {AFTER_CODE}\n'},
            'tail': {'before': '  ', 'after': None},
        })
        self.assertEqual(handler.equipment_config, {
            'flagship': {'before': BEFORE_CODE, 'after': AFTER_CODE},
        })
        self.assertIs(handler.equipment_config_enabled, True)

    def test_empty_or_partial_config_does_not_require_unused_positions(self):
        for raw in ('', '{}', 'flagship:\n  before: null', 'flagship:\n  after: ' + AFTER_CODE):
            with self.subTest(raw=raw):
                handler = make_handler()
                handler.config.Equipment_Config = raw
                handler.equipment_handle_before()
                self.assertIs(handler.equipment_config_enabled, False)
                handler.ensure_reorganize.assert_not_called()
        handler = make_handler()
        handler.config.Equipment_Config = yaml.safe_dump({'head': {'before': BEFORE_CODE}})
        self.assertEqual(handler.equipment_config, {'head': {'before': BEFORE_CODE, 'after': None}})

    def test_disabled_feature_does_not_parse_invalid_config(self):
        handler = make_handler()
        handler.config.Equipment_Enable = False
        handler.config.Equipment_Config = 'broken: ['
        handler.equipment_handle_before()
        handler.equipment_handle_after()
        handler.ensure_reorganize.assert_not_called()

    def test_unsupported_control_is_rejected_before_navigation(self):
        handler = make_handler()
        handler.config.Emulator_ControlMethod = 'adb'
        with self.assertRaises(RequestHumanTakeover):
            handler.equipment_handle_before()
        handler.ensure_reorganize.assert_not_called()
        handler.equip_enter.assert_not_called()

    def test_supported_control_methods_keep_equipment_flow(self):
        for method in ('uiautomator2', 'minitouch', 'MaaTouch'):
            with self.subTest(method=method):
                handler = make_handler(clear=False)
                handler.config.Emulator_ControlMethod = method
                handler.equipment_handle_before()
                handler._code_apply.assert_called_once_with(code=BEFORE_CODE)

    def test_all_selected_ships_are_cleared_before_any_code_is_applied(self):
        handler = make_handler({
            'flagship': {'before': BEFORE_CODE, 'after': AFTER_CODE},
            'head': {'before': AFTER_CODE, 'after': None},
        })
        handler.equipment_handle_before()
        self.assertEqual(handler._code_apply.call_args_list, [
            call(code=None), call(code=None), call(code=BEFORE_CODE), call(code=AFTER_CODE),
        ])
        self.assertTrue(handler.equipment_handle_before_flag)
        handler._code_apply.reset_mock()
        handler.equipment_handle_before()
        handler._code_apply.assert_not_called()

    def test_empty_after_code_clears_once_with_either_clear_setting(self):
        for clear in (False, True):
            with self.subTest(clear=clear):
                handler = make_handler({'flagship': {'before': BEFORE_CODE, 'after': None}}, clear=clear)
                handler._equipment_handle_before_flag = True
                handler.equipment_handle_after()
                handler._code_apply.assert_called_once_with(code=None)
                self.assertFalse(handler.equipment_handle_before_flag)

    def test_apply_and_clear_failure_stop_without_marking_before_complete(self):
        for clear in (False, True):
            with self.subTest(clear=clear):
                handler = make_handler(clear=clear)
                handler._code_apply.return_value = False
                with self.assertRaises(RequestHumanTakeover):
                    handler.equipment_handle_before()
                handler.ensure_save.assert_not_called()
                self.assertFalse(handler.equipment_handle_before_flag)

    def test_restore_failure_keeps_pending_state(self):
        handler = make_handler(clear=False)
        handler._equipment_handle_before_flag = True
        handler._code_apply.return_value = False
        with self.assertRaises(RequestHumanTakeover):
            handler.equipment_handle_after()
        self.assertTrue(handler.equipment_handle_before_flag)
        handler.ensure_save.assert_not_called()

    def test_save_failure_keeps_pending_restore_and_allows_retry(self):
        handler = make_handler(clear=False)
        handler._equipment_handle_before_flag = True
        handler.ensure_save.side_effect = GameStuckError('保存超时')
        with self.assertRaises(GameStuckError):
            handler.equipment_handle_after()
        self.assertTrue(handler.equipment_handle_before_flag)
        handler.ensure_save.side_effect = None
        handler.equipment_handle_after()
        self.assertFalse(handler.equipment_handle_before_flag)
        self.assertEqual(handler._code_apply.call_count, 2)

    def test_navigation_waits_for_slow_transition_and_throttles_clicks(self):
        for method, target in (('ensure_reorganize', FLEET_SAVE), ('ensure_save', FLEET_REORGANIZE)):
            with self.subTest(method=method):
                handler = object.__new__(EquipmentConfigHandler)
                state = {'time': 0, 'last_click': -100, 'clicks': []}

                def loop(timeout):
                    # 模拟三秒页面切换，每半秒提供新截图；不等待真实时间。
                    for frame in range(int(timeout * 2) + 1):
                        state['time'] = frame / 2
                        yield None

                def click(button, interval=0):
                    if state['time'] - state['last_click'] < interval:
                        return False
                    state['last_click'] = state['time']
                    state['clicks'].append(state['time'])
                    return True

                handler.loop = loop
                handler.appear = lambda button: button is target and state['time'] >= 3
                handler.appear_then_click = click
                getattr(handler, method)()
                self.assertEqual(state['clicks'], [0, 2])

    def test_preparation_gets_new_frame_after_equipping_then_starts_once(self):
        handler = make_handler(clear=False, cls=Combat)
        handler.appear = Mock(return_value=True)
        self.assertTrue(handler.handle_battle_preparation())
        handler.device.click.assert_not_called()
        self.assertTrue(handler.handle_battle_preparation())
        handler.device.click.assert_called_once_with(BATTLE_PREPARATION)
        handler._code_apply.assert_called_once_with(code=BEFORE_CODE)

    def test_unconfigured_combat_keeps_original_preparation_click(self):
        handler = make_handler(cls=Combat)
        handler.config.Equipment_Enable = False
        handler.appear = Mock(return_value=True)
        self.assertTrue(handler.handle_battle_preparation())
        handler.device.click.assert_called_once_with(BATTLE_PREPARATION)
        handler.ensure_reorganize.assert_not_called()
        handler.device.click.reset_mock()
        handler.appear.return_value = False
        self.assertFalse(handler.handle_battle_preparation())
        handler.device.click.assert_not_called()


class ExerciseEquipmentFlowTests(unittest.TestCase):
    def test_multiple_exercises_equip_once_restore_once_and_keep_scheduling(self):
        for remains in ([2, 1, 0], [0]):
            with self.subTest(remains=remains):
                runner = make_handler(clear=False, cls=Exercise)
                runner.config.Scheduler_ServerUpdate = '00:00'
                runner.config.Exercise_ExerciseStrategy = 'aggressive'
                runner.config.Exercise_DelayUntilHoursBeforeNextUpdate = 24
                runner.config.Exercise_OpponentChooseMode = 'max_exp'
                runner.config.multi_set = nullcontext
                runner.config.set_record = Mock()
                runner.config.task_delay = Mock()
                runner.device.image = object()
                runner.ui_ensure = Mock()
                runner._get_opponent_change_count = Mock(return_value=0)
                runner._get_exercise_strategy = Mock(return_value=(0, None))
                runner._choose_opponent = Mock()
                runner.appear = Mock(return_value=True)

                def fight():
                    if not runner.equipment_handle_before_flag:
                        runner.handle_battle_preparation()
                    runner.handle_battle_preparation()
                    return True

                runner._exercise_once = Mock(side_effect=fight)
                now = datetime(2026, 10, 22, 12)
                with patch('module.exercise.exercise.OCR_PERIOD_REMAIN.ocr', return_value=timedelta(hours=12)), \
                        patch('module.exercise.exercise.OCR_EXERCISE_REMAIN.ocr', side_effect=remains), \
                        patch('module.exercise.exercise.current_time', return_value=now), \
                        patch('module.exercise.exercise.get_server_next_update', return_value=now + timedelta(hours=12)):
                    runner.run()

                self.assertFalse(runner.equipment_handle_before_flag)
                runner.config.task_delay.assert_called_once_with(server_update=True)
                if remains[0]:
                    self.assertEqual(runner._exercise_once.call_count, 2)
                    self.assertEqual(runner._code_apply.call_args_list, [call(code=BEFORE_CODE), call(code=AFTER_CODE)])
                    runner._choose_opponent.assert_called_once_with(0)
                    self.assertEqual(runner.device.click.call_args_list, [call(BATTLE_PREPARATION)] * 2)
                    runner.ui_back.assert_called_with(EXERCISE_CHECK)
                else:
                    runner._code_apply.assert_not_called()
                    runner._choose_opponent.assert_not_called()


if __name__ == '__main__':
    unittest.main()
