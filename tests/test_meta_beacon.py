"""META 求援次数、最后一轮等待、断点恢复和信标切换的离线回归。"""

import copy
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from itertools import product
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import module.config.server as server

server.server = 'cn'

from module.base.base import ModuleBase
from module.base.utils import load_image
from module.combat.combat import BATTLE_PREPARATION
from module.config.config import AzurLaneConfig, TaskEnd
from module.config.config_updater import ConfigUpdater
from module.equipment.equipment_config import EquipmentConfigHandler
from module.exception import RequestHumanTakeover
from module.handler.assets import POPUP_CANCEL, POPUP_CONFIRM
from module.os_ash.assets import (
    ASH_QUIT, ASH_SHOWDOWN, ASH_SIMULATE, ASH_START, BEACON_EMPTY, BEACON_LIST, BEACON_MY, BEACON_REWARD,
    DOSSIER_LIST, META_AUTO_ATTACKING, META_BEGIN_ENTRANCE, META_MAIN_BEACON_ENTRANCE,
)
from module.os_ash.meta import AshBeaconAssist, MetaState, OpsiAshBeacon
from module.ui.assets import BACK_ARROW


class MetaBeaconTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 11, 12)
        clock = patch('module.os_ash.meta.current_time', side_effect=lambda: self.now)
        clock.start()
        self.addCleanup(clock.stop)

    def runner(self, limit=2, request_assist=False, damage=0, state=None, dossier=False, config=None):
        """保留真实任务循环与决策，只替换画面、OCR 和战斗操作。"""
        runner = OpsiAshBeacon.__new__(OpsiAshBeacon)
        runner.config = config or SimpleNamespace(
            OpsiAshBeacon_AssistRequestLimit=limit,
            OpsiAshBeacon_AssistRequestState=copy.deepcopy(state),
            OpsiAshBeacon_RequestAssist=request_assist,
            OpsiAshBeacon_AttackMode='current',
            OpsiAshBeacon_DossierAutoAttackMode=False,
            task_delay=Mock(), task_stop=Mock(side_effect=TaskEnd), check_task_switch=Mock(),
        )
        if config is not None:
            runner.config.check_task_switch = Mock()
        runner.device = SimpleNamespace(screenshot=Mock(), click=Mock())
        runner.world = SimpleNamespace(hp=300 - damage, damage=damage, claimed=False)
        runner._meta_receive = []
        runner._meta_category = 'undefined'
        runner.appear = lambda button, **kwargs: button is (DOSSIER_LIST if dossier else BEACON_LIST)
        runner.handle_map_event = Mock(return_value=False)
        runner._get_meta_damage = Mock(side_effect=lambda: runner.world.damage)
        runner._ask_for_help = Mock(return_value=True)
        runner.ui_goto_main = Mock()
        runner._begin_meta = Mock(return_value=False)

        def get_state():
            if runner.world.claimed:
                return MetaState.INIT
            return MetaState.COMPLETE if runner.world.hp <= 0 else MetaState.ATTACKING

        def attack():
            runner.world.hp -= 100
            runner.world.damage += 100

        def reward():
            runner.world.claimed = True

        runner._get_state = get_state
        runner._make_an_attack = Mock(side_effect=attack)
        runner._handle_ash_beacon_reward = Mock(side_effect=reward)
        return runner

    def defer(self, runner):
        runner._meta_waiting = False
        runner._attack_meta()
        self.assertTrue(runner._meta_waiting)

    def test_zero_preserves_unlimited_assist_without_finishing_alone(self):
        runner = self.runner(limit=0)
        self.defer(runner)
        for _ in range(48):
            self.now += timedelta(minutes=30)
            self.defer(runner)
        self.assertEqual(runner._make_an_attack.call_count, 1)
        self.assertEqual(runner._ask_for_help.call_count, 50)
        self.assertEqual(runner.world.hp, 200)
        self.assertIsNone(runner.config.OpsiAshBeacon_AssistRequestState)
        runner.config.task_delay.assert_called_with(minute=30)

    def test_minus_one_repeats_combat_and_keeps_request_assist_independent(self):
        for request_assist in (False, True):
            with self.subTest(request_assist=request_assist):
                runner = self.runner(limit=-1, request_assist=request_assist)
                runner._attack_meta()
                self.assertEqual(runner._make_an_attack.call_count, 3)
                self.assertEqual(runner._ask_for_help.call_count, 3 if request_assist else 0)
                self.assertTrue(runner.world.claimed)
                runner.config.task_delay.assert_not_called()

    def test_positive_limit_waits_after_every_request_then_finishes_alone(self):
        for limit in (1, 2, 3):
            with self.subTest(limit=limit):
                runner = self.runner(limit=limit)
                for count in range(1, limit + 1):
                    self.defer(runner)
                    deadline = self.now + timedelta(minutes=30)
                    self.assertEqual(runner.config.OpsiAshBeacon_AssistRequestState, {
                        'count': count, 'next_request': deadline.isoformat(),
                    })
                    self.assertEqual(runner._make_an_attack.call_count, 1)
                    self.assertEqual(runner._ask_for_help.call_count, count)
                    runner.config.task_delay.assert_called_with(target=deadline)
                    # 强制提前执行不能多叫一次，也不能在最后一轮后立即自己打。
                    self.now += timedelta(minutes=29)
                    self.defer(runner)
                    self.assertEqual(runner._ask_for_help.call_count, count)
                    self.assertEqual(runner._make_an_attack.call_count, 1)
                    self.now = deadline
                runner._attack_meta()
                self.assertEqual(runner._ask_for_help.call_count, limit)
                self.assertEqual(runner._make_an_attack.call_count, 3)
                self.assertTrue(runner.world.claimed)
                self.assertIsNone(runner.config.OpsiAshBeacon_AssistRequestState)

    def test_completion_during_assist_does_not_increment_or_attack(self):
        runner = self.runner()

        def completed():
            runner.world.hp = 0
            return False

        runner._ask_for_help.side_effect = completed
        runner._attack_meta()
        runner._make_an_attack.assert_not_called()
        self.assertIsNone(runner.config.OpsiAshBeacon_AssistRequestState)
        self.assertTrue(runner.world.claimed)

    def test_dossier_ignores_limit_and_leaves_beacon_record_untouched(self):
        state = {'count': 1, 'next_request': self.now.isoformat()}
        runner = self.runner(limit=1, dossier=True, state=state)
        runner._attack_meta()
        self.assertEqual(runner._make_an_attack.call_count, 3)
        runner._ask_for_help.assert_not_called()
        runner.config.task_delay.assert_not_called()
        self.assertEqual(runner.config.OpsiAshBeacon_AssistRequestState, state)

    def test_invalid_records_restart_assist_instead_of_triggering_solo_combat(self):
        for state in ('broken', {}, {'count': 5, 'next_request': 'bad'},
                      {'count': True, 'next_request': self.now.isoformat()},
                      {'count': 5, 'next_request': self.now.isoformat() + '+08:00'}):
            with self.subTest(state=state):
                runner = self.runner(limit=1, damage=100, state=state)
                self.defer(runner)
                runner._make_an_attack.assert_not_called()
                self.assertEqual(runner.config.OpsiAshBeacon_AssistRequestState['count'], 1)

    def test_confirmed_empty_beacon_resets_record_but_main_entrance_does_not(self):
        state = {'count': 99, 'next_request': self.now.isoformat()}
        for main in (False, True):
            with self.subTest(main=main):
                runner = self.runner(state=state)
                runner.appear = lambda button, **kwargs: button is (ASH_SHOWDOWN if main else BEACON_LIST)
                runner._check_beacon_point = Mock(return_value=True)
                self.assertTrue(OpsiAshBeacon._begin_meta(runner))
                self.assertEqual(runner.config.OpsiAshBeacon_AssistRequestState, state if main else None)
                if not main:
                    runner.appear = lambda button, **kwargs: button is BEACON_LIST
                    self.defer(runner)
                    self.assertEqual(runner.config.OpsiAshBeacon_AssistRequestState['count'], 1)
                    self.assertEqual(runner._make_an_attack.call_count, 1)

    def test_real_config_persists_count_and_final_wait_across_restarts(self):
        """使用临时 JSON 验证真实加载、绑定与保存，不访问任何用户实例。"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'meta-test.json'
            template = Path('config/template.json').read_text(encoding='utf-8')
            data = json.loads(template)
            data['OpsiAshBeacon']['OpsiAshBeacon']['AssistRequestLimit'] = 2
            path.write_text(json.dumps(data), encoding='utf-8')
            with patch('module.config.config.filepath_config', return_value=str(path)), \
                    patch('module.config.config_updater.filepath_config', return_value=str(path)):
                first = self.runner(config=AzurLaneConfig('meta-test', task='OpsiAshBeacon'))
                self.defer(first)
                saved = json.loads(path.read_text(encoding='utf-8'))
                self.assertEqual(saved['OpsiAshBeacon']['OpsiAshBeacon']['AssistRequestState']['count'], 1)

                second = self.runner(damage=100, config=AzurLaneConfig('meta-test', task='OpsiAshBeacon'))
                self.defer(second)
                second._ask_for_help.assert_not_called()
                second._make_an_attack.assert_not_called()
                self.now += timedelta(minutes=30)
                self.defer(second)
                self.assertEqual(second.config.OpsiAshBeacon_AssistRequestState['count'], 2)

                final = self.runner(damage=100, config=AzurLaneConfig('meta-test', task='OpsiAshBeacon'))
                self.defer(final)
                final._make_an_attack.assert_not_called()
                self.now += timedelta(minutes=30)
                final._attack_meta()
                final._ask_for_help.assert_not_called()
                self.assertEqual(final._make_an_attack.call_count, 2)
                saved = json.loads(path.read_text(encoding='utf-8'))
                self.assertIsNone(saved['OpsiAshBeacon']['OpsiAshBeacon']['AssistRequestState'])


class MetaBeaconMigrationTests(unittest.TestCase):
    def test_legacy_switch_migrates_without_changing_strategy(self):
        updater = ConfigUpdater()
        for old, expected in ((True, 0), (False, -1), (None, 0)):
            with self.subTest(old=old):
                result = updater.config_update({'OpsiAshBeacon': {'OpsiAshBeacon': {'OneHitMode': old}}})
                fields = result['OpsiAshBeacon']['OpsiAshBeacon']
                self.assertEqual(fields['AssistRequestLimit'], expected)
                self.assertIs(type(fields['AssistRequestLimit']), int)
                self.assertNotIn('OneHitMode', fields)
                self.assertEqual(updater.config_update(result), result)

    def test_explicit_new_value_and_saved_state_take_precedence(self):
        state = {'count': 1, 'next_request': '2026-10-11T12:30:00'}
        old = {'OpsiAshBeacon': {'OpsiAshBeacon': {
            'OneHitMode': False, 'AssistRequestLimit': 3, 'AssistRequestState': state,
        }}}
        fields = ConfigUpdater().config_update(old)['OpsiAshBeacon']['OpsiAshBeacon']
        self.assertEqual(fields['AssistRequestLimit'], 3)
        self.assertEqual(fields['AssistRequestState'], state)


class MetaEquipmentTests(unittest.TestCase):
    EQUIPMENT_YAML = """
flagship:
  before: "MTExLzIyMi8zMzMvMC8wXDA="
  after: "NDQ0LzU1NS82NjYvMC8wXDA="
up:
  before: null
  after: null
down:
  before: null
  after: null
head:
  before: null
  after: null
middle:
  before: null
  after: null
tail:
  before: null
  after: null
"""

    def test_equipment_config_parses_strings_and_applies_after_code(self):
        handler = EquipmentConfigHandler.__new__(EquipmentConfigHandler)
        handler.config = SimpleNamespace(
            Equipment_Enable=True,
            Equipment_ClearBeforeApply=False,
            Equipment_Config=self.EQUIPMENT_YAML,
        )
        handler.ensure_reorganize = Mock()
        handler.ensure_save = Mock()
        handler.equipment_code_supported = Mock(return_value=True)
        handler.equip_enter = Mock()
        handler.ui_back = Mock()
        handler._equipment_config_apply = Mock(return_value=True)
        handler._equipment_config_clear = Mock(return_value=True)

        self.assertEqual(
            handler.equipment_config,
            {'flagship': {'before': 'MTExLzIyMi8zMzMvMC8wXDA=', 'after': 'NDQ0LzU1NS82NjYvMC8wXDA='}},
        )
        handler.equipment_handle_before()
        self.assertTrue(handler.equipment_handle_before_flag)
        handler._equipment_config_apply.assert_called_once_with('MTExLzIyMi8zMzMvMC8wXDA=')

        handler._equipment_config_apply.reset_mock()
        handler.equipment_handle_after()
        self.assertFalse(handler.equipment_handle_before_flag)
        handler._equipment_config_apply.assert_called_once_with('NDQ0LzU1NS82NjYvMC8wXDA=')

    def test_equipment_config_rejects_non_string_code(self):
        handler = EquipmentConfigHandler.__new__(EquipmentConfigHandler)
        handler.config = SimpleNamespace(
            Equipment_Enable=True,
            Equipment_Config=self.EQUIPMENT_YAML.replace('"MTExLzIyMi8zMzMvMC8wXDA="', '12345'),
        )
        with self.assertRaises(RequestHumanTakeover):
            _ = handler.equipment_config

    def test_handle_ash_equipment_after_switches_between_beacon_and_assist_pages(self):
        for start_page in ('beacon_defeated', 'assist_exhausted'):
            with self.subTest(start_page=start_page):
                cls = OpsiAshBeacon if start_page == 'beacon_defeated' else AshBeaconAssist
                runner = cls.__new__(cls)
                runner.config = SimpleNamespace(Equipment_Enable=True)
                runner.device = SimpleNamespace(screenshot=Mock(), click=Mock())
                runner.ash_combat = SimpleNamespace(
                    is_dossier=False,
                    equipment_config_enabled=True,
                    equipment_handle_before_flag=True,
                    equipment_handle_after=Mock(),
                )
                state = {'page': start_page}

                def appear(button, **kwargs):
                    page = state['page']
                    if page == 'beacon_defeated':
                        return button in (BEACON_LIST, META_BEGIN_ENTRANCE)
                    if page == 'assist_ready':
                        return button in (BEACON_MY, ASH_START)
                    if page == 'assist_exhausted':
                        return button in (BEACON_MY, ASH_START)
                    if page == 'beacon_ready':
                        return button in (BEACON_LIST, ASH_START)
                    if page == 'prep':
                        return button is BATTLE_PREPARATION
                    if page == 'done':
                        return button is (BEACON_MY if start_page == 'assist_exhausted' else BEACON_LIST)
                    return False

                def appear_then_click(button, **kwargs):
                    if not appear(button, **kwargs):
                        return False
                    runner.device.click(button)
                    if button is BEACON_LIST and state['page'] == 'beacon_defeated':
                        state['page'] = 'assist_ready'
                    elif button is BEACON_MY and state['page'] == 'assist_exhausted':
                        state['page'] = 'beacon_ready'
                    elif button is ASH_START:
                        state['page'] = 'prep'
                    return True

                def click(button):
                    if button is BACK_ARROW and state['page'] == 'prep':
                        state['page'] = 'done'

                runner.appear = appear
                runner.appear_then_click = appear_then_click
                runner.device.click = Mock(side_effect=click)
                runner.digit_ocr_point_and_check = Mock(
                    side_effect=lambda btn, n: state['page'] == 'assist_ready'
                )

                self.assertTrue(runner.handle_ash_equipment_after())
                runner.ash_combat.equipment_handle_after.assert_called_once()
                self.assertEqual(state['page'], 'done')

    def test_handle_ash_equipment_after_aborts_cleanly_when_neither_page_can_prepare(self):
        runner = AshBeaconAssist.__new__(AshBeaconAssist)
        runner.config = SimpleNamespace(Equipment_Enable=True)
        runner.device = SimpleNamespace(screenshot=Mock(), click=Mock())
        runner.ash_combat = SimpleNamespace(
            is_dossier=False,
            equipment_config_enabled=True,
            equipment_handle_before_flag=True,
            equipment_handle_after=Mock(),
        )
        state = {'page': 'assist_exhausted'}

        def appear(button, **kwargs):
            if state['page'] == 'assist_exhausted':
                return button in (BEACON_MY, ASH_START, BEACON_EMPTY)
            if state['page'] == 'beacon_defeated':
                return button in (BEACON_LIST, META_BEGIN_ENTRANCE)
            return False

        def appear_then_click(button, **kwargs):
            if not appear(button, **kwargs):
                return False
            runner.device.click(button)
            if button is BEACON_MY:
                state['page'] = 'beacon_defeated'
            return True

        runner.appear = appear
        runner.appear_then_click = appear_then_click
        runner.digit_ocr_point_and_check = Mock(return_value=False)

        self.assertFalse(runner.handle_ash_equipment_after())
        runner.ash_combat.equipment_handle_after.assert_not_called()
        runner.device.click.assert_called_once_with(BEACON_MY)

    def test_dossier_attack_disables_equipment_config(self):
        runner = OpsiAshBeacon.__new__(OpsiAshBeacon)
        runner.config = SimpleNamespace(
            Equipment_Enable=True,
            Equipment_ClearBeforeApply=False,
            Equipment_Config=self.EQUIPMENT_YAML,
        )
        runner.device = SimpleNamespace(screenshot=Mock(), click=Mock())
        runner.ash_combat.combat = Mock()

        runner.appear = lambda button, **kwargs: button is DOSSIER_LIST
        runner._make_an_attack()
        self.assertTrue(runner.ash_combat.is_dossier)
        self.assertFalse(runner.ash_combat.equipment_config_enabled)

        runner.appear = lambda button, **kwargs: button is BEACON_LIST
        runner._make_an_attack()
        self.assertFalse(runner.ash_combat.is_dossier)
        self.assertTrue(bool(runner.ash_combat.equipment_config_enabled))


class MetaEquipmentRecoveryTests(unittest.TestCase):
    def runner(self, cls, page, own='own_ready', assist='assist_ready', dossier=False, pixels=False):
        """点击只排队下一帧，页面识别始终读取最近一次截图。"""
        runner = object.__new__(cls)
        runner.config = SimpleNamespace(Equipment_Enable=True)
        runner.ash_combat = SimpleNamespace(
            is_dossier=dossier,
            equipment_config_enabled=not dossier,
            equipment_handle_before_flag=True,
        )
        screens = {
            'main': (ASH_SHOWDOWN,),
            'dossier': (DOSSIER_LIST, ASH_QUIT, ASH_START),
            'own_ready': (BEACON_LIST, ASH_START),
            'own_loading': (BEACON_LIST,),
            'own_defeated': (BEACON_LIST, BEACON_REWARD),
            'own_simulate': (BEACON_LIST, BEACON_EMPTY, ASH_SIMULATE),
            'simulate_confirm': (POPUP_CANCEL, POPUP_CONFIRM),
            'assist_ready': (BEACON_MY, ASH_START),
            'assist_exhausted': (BEACON_MY, ASH_START),
            'prep': (BATTLE_PREPARATION,),
        }
        fixtures = Path(__file__).parent / 'fixtures' / 'meta_equipment'
        pixel_frames = {
            'own_simulate': load_image(str(fixtures / 'simulate.png')),
            'simulate_confirm': load_image(str(fixtures / 'simulate_confirm.png')),
        } if pixels else {}
        state = SimpleNamespace(page=page, pending=None, origin=None, frames=0, loading=0)

        def screenshot():
            state.frames += 1
            self.assertLess(state.frames, 25, '页面恢复循环未收敛')
            if state.pending is not None:
                state.page, state.pending = state.pending, None
            elif state.page == 'own_loading':
                state.loading += 1
                if state.loading == 2:
                    state.page = 'own_ready'

        def appear(button, **kwargs):
            if state.page in pixel_frames:
                runner.device.image = pixel_frames[state.page]
                return ModuleBase.appear(runner, button, **kwargs)
            return button in screens[state.page]

        def click(button):
            if button is ASH_QUIT:
                state.pending = 'main'
            elif button is META_MAIN_BEACON_ENTRANCE or button is BEACON_MY:
                state.pending = own
            elif button is BEACON_LIST:
                state.pending = assist
            elif button is ASH_SIMULATE:
                self.assertEqual(state.page, 'own_simulate')
                state.origin, state.pending = state.page, 'simulate_confirm'
            elif button is POPUP_CONFIRM:
                self.assertEqual(state.page, 'simulate_confirm')
                state.pending = 'prep'
            elif button is ASH_START:
                self.assertNotEqual(state.page, 'dossier', '不能借用档案的独立编队')
                self.assertNotEqual(state.page, 'assist_exhausted', '次数耗尽时不能出击')
                state.origin, state.pending = state.page, 'prep'
            elif button is BACK_ARROW:
                state.pending = state.origin
            else:
                self.fail(f'恢复装备时出现意外点击：{button}')

        def appear_then_click(button, **kwargs):
            if not appear(button, **kwargs):
                return False
            runner.device.click(button)
            return True

        def restore():
            self.assertEqual(state.page, 'prep')
            self.assertFalse(runner.ash_combat.is_dossier)
            runner.ash_combat.equipment_handle_before_flag = False

        runner.device = SimpleNamespace(
            screenshot=Mock(side_effect=screenshot), click=Mock(side_effect=click), stuck_record_add=Mock(),
        )
        runner.interval_timer = {}
        runner.appear = appear
        runner.appear_then_click = appear_then_click
        runner.digit_ocr_point_and_check = Mock(side_effect=lambda *args: state.page == 'assist_ready')
        runner.ash_combat.equipment_handle_after = Mock(side_effect=restore)
        return runner, state

    def test_assist_borrows_own_beacon_and_returns_to_assist(self):
        runner, state = self.runner(AshBeaconAssist, 'assist_exhausted', assist='assist_exhausted')
        self.assertTrue(runner.handle_ash_equipment_after())
        self.assertEqual(state.page, 'assist_exhausted')
        runner.ash_combat.equipment_handle_after.assert_called_once()
        buttons = [call.args[0] for call in runner.device.click.call_args_list]
        self.assertEqual(buttons, [BEACON_MY, ASH_START, BACK_ARROW, BEACON_LIST])

    def test_own_beacon_borrows_assist_and_returns_to_own_beacon(self):
        runner, state = self.runner(OpsiAshBeacon, 'own_defeated', own='own_defeated')
        self.assertTrue(runner.handle_ash_equipment_after())
        self.assertEqual(state.page, 'own_defeated')
        runner.ash_combat.equipment_handle_after.assert_called_once()

    def test_simulation_screenshots_restore_equipment_and_return_to_task_page(self):
        for cls, page in ((OpsiAshBeacon, 'own_simulate'), (AshBeaconAssist, 'assist_exhausted')):
            with self.subTest(task=cls.__name__):
                runner, state = self.runner(
                    cls, page, own='own_simulate', assist='assist_exhausted', pixels=True,
                )
                self.assertTrue(runner.handle_ash_equipment_after())
                self.assertEqual(state.page, page)
                self.assertFalse(runner.ash_combat.equipment_handle_before_flag)
                runner.ash_combat.equipment_handle_after.assert_called_once()
                buttons = [call.args[0] for call in runner.device.click.call_args_list]
                expected = [ASH_SIMULATE, POPUP_CONFIRM, BACK_ARROW]
                if cls is AshBeaconAssist:
                    expected = [BEACON_MY] + expected + [BEACON_LIST]
                self.assertEqual(buttons, expected)

    def test_simulation_click_cooldown_waits_for_new_screenshot(self):
        runner, state = self.runner(OpsiAshBeacon, 'own_simulate')
        click = runner.appear_then_click
        attempts = []

        def appear_then_click(button, **kwargs):
            if button is ASH_SIMULATE:
                attempts.append(state.frames)
                if len(attempts) == 1:
                    return False
            return click(button, **kwargs)

        runner.appear_then_click = appear_then_click
        self.assertTrue(runner.handle_ash_equipment_after())
        self.assertEqual(attempts, [0, 1])
        runner.ash_combat.equipment_handle_after.assert_called_once()

    def test_unrecognized_simulation_confirmation_keeps_equipment_pending(self):
        runner, state = self.runner(OpsiAshBeacon, 'own_simulate')
        runner.handle_popup_confirm = Mock(return_value=False)
        with patch('module.os_ash.meta.Timer') as timer:
            timer.return_value.start.return_value.reached.side_effect = [False, False, True]
            self.assertFalse(runner.handle_ash_equipment_after())
        self.assertEqual(state.page, 'simulate_confirm')
        self.assertTrue(runner.ash_combat.equipment_handle_before_flag)
        runner.ash_combat.equipment_handle_after.assert_not_called()
        runner.device.click.assert_called_once_with(ASH_SIMULATE)

    def test_loading_page_does_not_trigger_fallback_or_skip_restoration(self):
        runner, state = self.runner(
            AshBeaconAssist, 'assist_exhausted', own='own_loading', assist='assist_exhausted',
        )
        self.assertTrue(runner.handle_ash_equipment_after())
        self.assertEqual(state.loading, 2)
        self.assertEqual(state.page, 'assist_exhausted')
        runner.ash_combat.equipment_handle_after.assert_called_once()

    def test_pending_normal_fleet_is_restored_after_last_dossier_battle(self):
        for page, own in product(('dossier', 'prep'), ('own_ready', 'own_simulate')):
            with self.subTest(page=page, own=own):
                runner, state = self.runner(OpsiAshBeacon, page, own=own, dossier=True)
                state.origin = 'dossier'
                self.assertTrue(runner.handle_ash_equipment_after())
                self.assertEqual(state.page, own)
                runner.ash_combat.equipment_handle_after.assert_called_once()
                buttons = [call.args[0] for call in runner.device.click.call_args_list]
                entrance = [ASH_SIMULATE, POPUP_CONFIRM] if own == 'own_simulate' else [ASH_START]
                expected = [ASH_QUIT, META_MAIN_BEACON_ENTRANCE] + entrance + [BACK_ARROW]
                self.assertEqual(buttons, ([BACK_ARROW] if page == 'prep' else []) + expected)

    def test_no_pending_equipment_does_not_navigate(self):
        runner, state = self.runner(OpsiAshBeacon, 'dossier', dossier=True)
        runner.ash_combat.equipment_handle_before_flag = False
        self.assertFalse(runner.handle_ash_equipment_after())
        runner.device.screenshot.assert_not_called()
        runner.device.click.assert_not_called()

    def test_task_switch_restores_equipment_and_preserves_stop_signal(self):
        runner = MetaBeaconTests().runner()
        runner.world.hp = 0
        runner.ash_combat = SimpleNamespace(equipment_handle_before_flag=True)
        # 有剩余数据时原实现会跳过恢复，直接被任务切换打断。
        runner._check_beacon_point = Mock(return_value=True)
        runner.config.check_task_switch.side_effect = TaskEnd
        runner.handle_ash_equipment_after = Mock(return_value=True)
        with self.assertRaises(TaskEnd):
            runner._attack_meta()
        runner.handle_ash_equipment_after.assert_called_once()

    def test_dossier_auto_attack_pause_leaves_cleanup_to_unified_task(self):
        runner = MetaBeaconTests().runner(dossier=True)
        runner.appear = lambda button, **kwargs: button in (DOSSIER_LIST, META_AUTO_ATTACKING)
        runner.handle_ash_equipment_after = Mock(return_value=True)
        self.assertFalse(runner._satisfy_attack_condition())
        self.assertTrue(runner._meta_waiting)
        runner.handle_ash_equipment_after.assert_not_called()
        runner.config.task_delay.assert_called_once_with(minute=15)
        runner.ui_goto_main.assert_not_called()

    def test_prepare_timeout_keeps_pending_state_without_starting_combat(self):
        runner, state = self.runner(OpsiAshBeacon, 'own_loading')
        with patch('module.os_ash.meta.Timer') as timer:
            timer.return_value.start.return_value.reached.return_value = True
            self.assertFalse(runner.handle_ash_equipment_after())
        self.assertTrue(runner.ash_combat.equipment_handle_before_flag)
        runner.ash_combat.equipment_handle_after.assert_not_called()
        runner.device.click.assert_not_called()


if __name__ == '__main__':
    unittest.main()
