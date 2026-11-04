"""META 统一任务的阶段交接、档案期间暂停支援及配置保存回归。"""

import json
import tempfile
import unittest
from contextlib import nullcontext
from datetime import datetime
from itertools import product
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import module.config.server as server

server.server = 'cn'

from module.api.config_service import ConfigService
from module.api.protocol import ConfigChange
from module.config.config import TaskEnd
from module.config.config_updater import ConfigUpdater
from module.exception import GameStuckError
from module.os_ash.assets import (
    ASH_QUIT, ASH_SHOWDOWN, ASH_START, BEACON_LIST, BEACON_MY, BEACON_REWARD,
    DOSSIER_LIST, HELP_ENTER, META_AUTO_ATTACKING, META_BEGIN_ENTRANCE, META_MAIN_DOSSIER_ENTRANCE,
)
from module.os_ash.meta import AshBeaconAssist, OpsiAshBeacon
from tests.test_api import fixture
from tests import test_meta_beacon as beacon_tests


class MetaTaskMergeTests(unittest.TestCase):
    def runner(self, assist=True, complete=True, skip_assist=False):
        runner = object.__new__(OpsiAshBeacon)
        runner.config = SimpleNamespace(
            OpsiAshAssist_Enable=assist, OpsiAshBeacon_AttackMode='current',
            OpsiAshBeacon_DossierSkipAssist=skip_assist, OpsiAshBeacon_AssistRequestLimit=0,
            OpsiAshBeacon_AssistRequestState=None,
            task_delay=Mock(), multi_set=nullcontext,
        )
        runner.device = SimpleNamespace()
        runner.ash_combat = SimpleNamespace(equipment_handle_before_flag=False)
        runner.ui_ensure = Mock()
        runner.ui_goto_main = Mock()
        runner._begin_beacon = Mock()
        runner.handle_ash_equipment_after = Mock()
        self.enterContext(patch.object(AshBeaconAssist, '_begin_meta_assist', return_value=complete))
        self.reward = self.enterContext(patch('module.os_ash.meta.MetaReward'))
        return runner

    def test_stages_share_config_and_combat_then_restore_once(self):
        runner = self.runner()
        events = []

        def assist():
            events.append('assist')
            self.assertTrue(runner.ash_assist.ash_combat.equipment_handle_before_flag)
            return True

        def beacon():
            events.append('beacon')
            runner.ash_combat.equipment_handle_before_flag = True
            runner._meta_receive.extend(['beacon', 'dossier'])

        runner.ash_assist._begin_meta_assist.side_effect = assist
        runner._begin_beacon.side_effect = beacon
        runner.handle_ash_equipment_after.side_effect = lambda: events.append('restore')
        runner.run()
        self.assertIs(runner.ash_assist.config, runner.config)
        self.assertIs(runner.ash_assist.ash_combat, runner.ash_combat)
        self.assertEqual(events, ['beacon', 'assist', 'restore'])
        runner.handle_ash_equipment_after.assert_called_once()
        self.assertEqual([call.kwargs['category'] for call in self.reward.return_value.run.call_args_list],
                         ['beacon', 'dossier'])
        runner.config.task_delay.assert_called_once_with(server_update=True)
        self.assertEqual(runner.ui_goto_main.call_count, 2)

    def test_incomplete_assist_still_runs_beacon_and_retries(self):
        runner = self.runner(complete=False)
        runner.run()
        runner._begin_beacon.assert_called_once()
        self.assertTrue(runner._assist_pending)
        runner.config.task_delay.assert_called_once_with(server_update=True, minute=10)
        self.reward.return_value.run.assert_called_once_with(category='beacon')

    def test_disabled_assist_does_not_inspect_or_block_dossier(self):
        runner = self.runner(assist=False, skip_assist=True)
        runner._is_dossier_active = Mock()
        runner.run()
        self.assertNotIn('ash_assist', runner.__dict__)
        runner._is_dossier_active.assert_not_called()
        runner._begin_beacon.assert_called_once()
        runner.config.task_delay.assert_called_once_with(server_update=True)

    def test_active_dossier_skips_assists_until_a_later_run_confirms_completion(self):
        for mode in ('current', 'current_dossier', 'current_dossier_only'):
            with self.subTest(mode=mode):
                runner = self.runner(skip_assist=True)
                runner.config.OpsiAshBeacon_AttackMode = mode
                runner._is_dossier_active = Mock(side_effect=[True, False])
                runner.run()
                self.assertNotIn('ash_assist', runner.__dict__)
                self.assertFalse(runner._assist_pending)
                runner.config.task_delay.assert_called_once_with(minute=15)
                self.reward.return_value.run.assert_not_called()

                runner.config.task_delay.reset_mock()
                runner.run()
                runner.ash_assist._begin_meta_assist.assert_called_once()
                runner.config.task_delay.assert_called_once_with(server_update=True)
                self.reward.return_value.run.assert_called_once_with(category='beacon')

    def test_real_dossier_combat_and_auto_attack_pause_resume_assists_after_completion(self):
        for automatic in (False, True):
            with self.subTest(automatic=automatic):
                runner = beacon_tests.MetaBeaconTests().runner(dossier=True)
                runner.config.OpsiAshAssist_Enable = True
                runner.config.OpsiAshBeacon_DossierSkipAssist = True
                runner.config.multi_set = nullcontext
                runner.ash_combat = SimpleNamespace(equipment_handle_before_flag=False)
                runner.ui_ensure = Mock()
                runner.ensure_dossier_page = Mock()
                runner.handle_ash_equipment_after = Mock()

                def appear(button, **kwargs):
                    if button is DOSSIER_LIST:
                        return True
                    if runner.world.claimed:
                        return button is META_BEGIN_ENTRANCE
                    return button is (META_AUTO_ATTACKING if automatic else HELP_ENTER)

                runner.appear = appear
                assist = self.enterContext(patch.object(AshBeaconAssist, '_begin_meta_assist', return_value=True))
                reward = self.enterContext(patch('module.os_ash.meta.MetaReward'))
                runner.run()
                if automatic:
                    assist.assert_not_called()
                    runner._make_an_attack.assert_not_called()
                    runner.config.task_delay.assert_called_once_with(minute=15)
                    reward.return_value.run.assert_not_called()
                    # 下一次实际截图确认自动攻击已击破，可在本轮领奖后立即恢复支援。
                    runner.world.hp = 0
                    runner.config.task_delay.reset_mock()
                    runner.run()
                else:
                    self.assertEqual(runner._make_an_attack.call_count, 3)
                self.assertTrue(runner.world.claimed)
                assist.assert_called_once()
                runner.config.task_delay.assert_called_once_with(server_update=True)
                self.assertEqual([call.kwargs['category'] for call in reward.return_value.run.call_args_list],
                                 ['dossier', 'beacon'])

    def test_skip_switch_off_does_not_inspect_dossier(self):
        runner = self.runner()
        runner._is_dossier_active = Mock(return_value=True)
        runner.run()
        runner._is_dossier_active.assert_not_called()
        runner.ash_assist._begin_meta_assist.assert_called_once()

    def test_assists_wait_for_reward_collection_and_positive_idle_frame(self):
        for mode, final in product(('current', 'current_dossier', 'current_dossier_only'),
                                   ('idle', 'attacking', 'auto_attacking')):
            with self.subTest(mode=mode, final=final):
                runner = self.runner(skip_assist=True)
                runner.config.OpsiAshBeacon_AttackMode = mode
                runner.ensure_dossier_page = Mock()
                state = SimpleNamespace(frame=0)
                frames = ['reward', 'reward', 'reward', 'popup', 'loading', final]
                screens = {
                    'reward': (DOSSIER_LIST, BEACON_REWARD, HELP_ENTER, META_BEGIN_ENTRANCE),
                    'popup': (DOSSIER_LIST, META_BEGIN_ENTRANCE),
                    'loading': (DOSSIER_LIST,),
                    'idle': (DOSSIER_LIST, META_BEGIN_ENTRANCE),
                    'attacking': (DOSSIER_LIST, HELP_ENTER, META_BEGIN_ENTRANCE),
                    'auto_attacking': (DOSSIER_LIST, META_AUTO_ATTACKING, META_BEGIN_ENTRANCE),
                }
                runner.appear = lambda button, **kwargs: button in screens[frames[state.frame]]
                runner.handle_map_event = Mock(side_effect=lambda: frames[state.frame] == 'popup')

                def click(button, **kwargs):
                    self.assertIs(button, BEACON_REWARD, '支援前检查只能领奖，不能开启新档案')
                    self.assertEqual(frames[state.frame], 'reward')
                    return state.frame > 0

                def screenshot():
                    state.frame += 1
                    self.assertLess(state.frame, len(frames), '档案状态检查未收敛')

                def assist():
                    self.assertEqual(frames[state.frame], 'idle', '只有领奖后确认档案未开启才允许支援')
                    self.assertEqual(runner._meta_receive.count('dossier'), 1)
                    return True

                runner.appear_then_click = Mock(side_effect=click)
                runner.device = SimpleNamespace(screenshot=Mock(side_effect=screenshot))
                daily_assist = self.enterContext(patch.object(AshBeaconAssist, '_begin_meta_assist',
                                                             side_effect=assist))
                runner.run()
                self.assertEqual(state.frame, len(frames) - 1)
                self.assertEqual(runner.appear_then_click.call_count, 3)
                categories = [call.kwargs['category'] for call in self.reward.return_value.run.call_args_list]
                if final == 'idle':
                    daily_assist.assert_called_once()
                    self.assertEqual(categories, ['dossier', 'beacon'])
                    runner.config.task_delay.assert_called_once_with(server_update=True)
                else:
                    daily_assist.assert_not_called()
                    self.assertNotIn('ash_assist', runner.__dict__)
                    self.assertEqual(categories, ['dossier'])
                    runner.config.task_delay.assert_called_once_with(minute=15)

    def test_unfinished_dossier_reward_never_allows_assists_or_swallows_recovery(self):
        runner = self.runner(skip_assist=True)
        runner.ensure_dossier_page = Mock()
        runner.handle_map_event = Mock(return_value=False)
        runner.appear = lambda button, **kwargs: button in (DOSSIER_LIST, BEACON_REWARD)
        runner.appear_then_click = Mock(return_value=True)
        runner.device = SimpleNamespace(screenshot=Mock(side_effect=GameStuckError))
        with self.assertRaises(GameStuckError):
            runner.run()
        self.assertNotIn('ash_assist', runner.__dict__)
        runner.config.task_delay.assert_not_called()
        self.reward.return_value.run.assert_not_called()

    def test_dossier_pause_merges_with_beacon_wait_without_extending_earlier_deadline(self):
        for minute in (5, 30):
            with self.subTest(minute=minute):
                runner = self.runner(skip_assist=True)
                runner._is_dossier_active = Mock(return_value=True)
                runner._begin_beacon.side_effect = lambda: runner._delay_meta(minute=minute)
                runner.run()
                runner.config.task_delay.assert_called_once_with(minute=min(minute, 15))

    def test_finite_help_deadline_survives_dossier_pause(self):
        runner = self.runner(skip_assist=True)
        deadline = datetime(2026, 10, 24, 12)
        runner._is_dossier_active = Mock(return_value=True)
        runner._begin_beacon.side_effect = lambda: runner._delay_meta(target=deadline)
        runner.run()
        runner.config.task_delay.assert_called_once_with(target=deadline, minute=15)

    def test_own_beacon_wait_keeps_support_rewards_and_next_run(self):
        for complete in (False, True):
            with self.subTest(complete=complete):
                runner = self.runner(complete=complete)
                runner.appear = lambda button, **kwargs: button is BEACON_LIST
                runner._get_meta_damage = Mock(return_value=100)
                runner._begin_beacon.side_effect = runner._satisfy_attack_condition
                runner.run()
                runner.config.task_delay.assert_called_once_with(minute=30 if complete else 10)
                runner.handle_ash_equipment_after.assert_called_once()
                self.reward.return_value.run.assert_called_once_with(category='beacon')
                runner.ui_goto_main.assert_called()

    def test_dossier_auto_attack_wait_restores_shared_equipment_at_task_end(self):
        runner = self.runner()
        runner.appear = lambda button, **kwargs: button in (DOSSIER_LIST, META_AUTO_ATTACKING)
        runner._begin_beacon.side_effect = runner._satisfy_attack_condition
        runner.run()
        runner.handle_ash_equipment_after.assert_called_once()
        runner.config.task_delay.assert_called_once_with(minute=15)

    def test_task_switch_restores_and_propagates_stop_signal(self):
        runner = self.runner()
        runner._begin_beacon.side_effect = TaskEnd
        with self.assertRaises(TaskEnd):
            runner.run()
        runner.handle_ash_equipment_after.assert_called_once()
        runner.config.task_delay.assert_not_called()

    def test_finite_help_deadline_is_combined_with_support_retry(self):
        runner = self.runner()
        runner._assist_pending = True
        deadline = datetime(2026, 10, 24, 12)
        runner._delay_meta(target=deadline)
        runner.config.task_delay.assert_called_once_with(target=deadline, minute=10)


class MetaDossierStateTests(unittest.TestCase):
    def test_new_dossier_never_waits_for_assist_completion(self):
        for main, assist_enabled in product((False, True), repeat=2):
            with self.subTest(main=main, assist=assist_enabled):
                runner = object.__new__(OpsiAshBeacon)
                runner.config = SimpleNamespace(
                    OpsiAshBeacon_AttackMode='current_dossier',
                    OpsiAshAssist_Enable=assist_enabled,
                )
                runner.appear = lambda button, **kwargs: button is (ASH_SHOWDOWN if main else DOSSIER_LIST)
                runner.appear_then_click = Mock(return_value=True)
                runner.device = SimpleNamespace(click=Mock())
                runner._check_beacon_point = Mock(return_value=False)
                runner._check_dossier_point = Mock(return_value=True)
                runner._begin_meta()
                button = META_MAIN_DOSSIER_ENTRANCE if main else META_BEGIN_ENTRANCE
                clicked = [call.args[0] for call in runner.appear_then_click.call_args_list]
                self.assertIn(button, clicked)

    def test_already_open_dossier_can_finish_before_assists(self):
        runner = beacon_tests.MetaBeaconTests().runner(dossier=True)
        runner.config.OpsiAshAssist_Enable = True
        runner._attack_meta()
        self.assertEqual(runner._make_an_attack.call_count, 3)
        self.assertTrue(runner.world.claimed)

    def test_active_auto_attacking_and_idle_dossier_states(self):
        for button, active in ((HELP_ENTER, True), (META_AUTO_ATTACKING, True),
                               (META_BEGIN_ENTRANCE, False)):
            with self.subTest(button=button):
                runner = object.__new__(OpsiAshBeacon)
                runner.ensure_dossier_page = Mock()
                runner.handle_map_event = Mock(return_value=False)
                runner.appear = lambda item, **kwargs: item in (DOSSIER_LIST, button)
                runner.device = SimpleNamespace(screenshot=Mock())
                self.assertEqual(runner._is_dossier_active(), active)
                runner.device.screenshot.assert_not_called()

    def test_loading_dossier_waits_for_positive_state_on_new_screenshot(self):
        runner = object.__new__(OpsiAshBeacon)
        state = SimpleNamespace(ready=False)
        runner.ensure_dossier_page = Mock()
        runner.handle_map_event = Mock(return_value=False)
        runner.appear = lambda button, **kwargs: button is DOSSIER_LIST or (state.ready and button is HELP_ENTER)
        runner.device = SimpleNamespace(screenshot=Mock(side_effect=lambda: setattr(state, 'ready', True)))
        self.assertTrue(runner._is_dossier_active())
        runner.device.screenshot.assert_called_once()

    def test_dossier_inspection_leaves_own_beacon_and_waits_for_each_page(self):
        runner = object.__new__(OpsiAshBeacon)
        state = SimpleNamespace(page='beacon', pending=None, frames=0)
        screens = {
            'beacon': (BEACON_LIST, ASH_QUIT),
            'main': (ASH_SHOWDOWN, META_MAIN_DOSSIER_ENTRANCE),
            'dossier': (DOSSIER_LIST, META_AUTO_ATTACKING),
        }
        runner.ui_ensure = Mock()
        runner.handle_map_event = Mock(return_value=False)
        runner.appear = lambda button, **kwargs: button in screens[state.page]

        def click(button, **kwargs):
            if button is ASH_QUIT:
                state.pending = 'main'
            elif button is META_MAIN_DOSSIER_ENTRANCE:
                state.pending = 'dossier'
            else:
                self.fail(f'档案检查出现意外点击：{button}')
            return True

        def screenshot():
            state.frames += 1
            self.assertLess(state.frames, 5, '档案检查未正确切换页面')
            state.page, state.pending = state.pending, None

        runner.appear_then_click = Mock(side_effect=click)
        runner.device = SimpleNamespace(screenshot=Mock(side_effect=screenshot))
        self.assertTrue(runner._is_dossier_active())
        self.assertEqual(state.page, 'dossier')
        self.assertEqual(state.frames, 2)

    def test_empty_current_beacon_returns_to_main_for_next_stage(self):
        runner = object.__new__(OpsiAshBeacon)
        runner.config = SimpleNamespace(OpsiAshBeacon_AttackMode='current',
                                        OpsiAshBeacon_AssistRequestState=None)
        runner.appear = lambda button, **kwargs: button is BEACON_LIST
        runner._check_beacon_point = Mock(return_value=False)
        runner.appear_then_click = Mock(return_value=True)
        self.assertTrue(runner._begin_meta())
        runner.appear_then_click.assert_called_once_with(ASH_QUIT, offset=(10, 10), interval=2)

    def test_assist_page_handover_waits_for_own_beacon_screenshot(self):
        runner = object.__new__(OpsiAshBeacon)
        state = SimpleNamespace(page='assist', pending=None)
        runner.appear = lambda button, **kwargs: button is (BEACON_MY if state.page == 'assist' else BEACON_LIST)
        runner.handle_map_event = Mock(return_value=False)

        def click(button, **kwargs):
            if button is BEACON_MY:
                state.pending = 'own'
                return True
            return False

        def screenshot():
            state.page = state.pending

        runner.device = SimpleNamespace(screenshot=Mock(side_effect=screenshot))
        runner.appear_then_click = Mock(side_effect=click)
        self.assertTrue(runner._ensure_meta_page())
        self.assertEqual(state.page, 'own')
        runner.device.screenshot.assert_called_once()


class MetaAssistCompletionTests(unittest.TestCase):
    def runner(self, remain=3, available=True, valid=True, vanish=False):
        runner = object.__new__(AshBeaconAssist)
        state = SimpleNamespace(remain=remain, available=available, frames=0)

        def screenshot():
            state.frames += 1
            self.assertLess(state.frames, 15, '支援列表消失后未退出')

        def attack():
            state.remain -= 1
            if vanish:
                state.available = False

        runner.device = SimpleNamespace(image=object(), screenshot=Mock(side_effect=screenshot))
        runner._in_meta_assist_page = Mock(return_value=True)
        runner.appear = lambda button, **kwargs: button is ASH_START and state.available
        runner.handle_map_event = Mock(return_value=False)
        runner._ensure_meta_level = Mock()
        runner._make_an_attack = Mock(side_effect=attack)
        ocr = self.enterContext(patch('module.os_ash.meta.OCR_BEACON_REMAIN.ocr'))
        ocr.side_effect = lambda image: (state.remain, 3 - state.remain, 3) if valid else (0, 0, 0)
        timer = self.enterContext(patch('module.os_ash.meta.Timer'))
        timer.return_value.start.return_value.reached.side_effect = lambda: state.frames >= 5
        return runner

    def test_all_three_assists_must_complete(self):
        runner = self.runner()
        self.assertTrue(runner._attack_meta())
        self.assertEqual(runner._make_an_attack.call_count, 3)

    def test_zero_is_complete_even_if_list_is_empty(self):
        runner = self.runner(remain=0, available=False)
        self.assertTrue(runner._attack_meta())
        runner._make_an_attack.assert_not_called()

    def test_empty_list_or_invalid_counter_does_not_complete(self):
        for available, valid in ((False, True), (True, False)):
            with self.subTest(available=available, valid=valid):
                runner = self.runner(available=available, valid=valid)
                self.assertFalse(runner._attack_meta())
                runner._make_an_attack.assert_not_called()

    def test_list_disappearing_after_one_battle_is_not_daily_completion(self):
        runner = self.runner(vanish=True)
        self.assertFalse(runner._attack_meta())
        runner._make_an_attack.assert_called_once()

    def test_support_resets_dossier_fleet_flag(self):
        runner = object.__new__(AshBeaconAssist)
        runner.ash_combat = SimpleNamespace(is_dossier=True, combat=Mock())
        runner._make_an_attack()
        self.assertFalse(runner.ash_combat.is_dossier)


class MetaConfigurationTests(unittest.TestCase):
    def test_webui_reads_and_saves_unified_task_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            service = ConfigService(fixture(directory))
            path = service.path('testpilot')
            original = path.read_bytes()
            values = service.get('testpilot')['values']
            meta = values['OpsiAshBeacon']
            self.assertNotIn('OpsiAshAssist', values)
            self.assertEqual(meta['OpsiAshAssist'], {'Enable': True, 'Tier': 15})
            self.assertNotIn('DossierAfterAssist', meta['OpsiAshBeacon'])
            self.assertFalse(meta['OpsiAshBeacon']['DossierSkipAssist'])
            self.assertEqual(path.read_bytes(), original)
            for enabled in (True, False):
                service.patch('testpilot', None, [ConfigChange(
                    path='OpsiAshBeacon.OpsiAshBeacon.DossierSkipAssist', value=enabled),
                    ConfigChange(path='OpsiAshBeacon.OpsiAshAssist.Enable', value=enabled)])
                saved = service.read_json(path)
                self.assertNotIn('OpsiAshAssist', saved)
                self.assertEqual(saved['OpsiAshBeacon']['OpsiAshBeacon']['DossierSkipAssist'], enabled)
                self.assertEqual(saved['OpsiAshBeacon']['OpsiAshAssist']['Enable'], enabled)
                self.assertEqual(saved['OpsiAshBeacon']['Equipment'], meta['Equipment'])

    def test_generated_menu_has_one_task_and_all_new_labels_are_translated(self):
        args = json.loads(Path('module/config/argument/args.json').read_text(encoding='utf-8'))
        menu = json.loads(Path('module/config/argument/menu.json').read_text(encoding='utf-8'))
        self.assertNotIn('OpsiAshAssist', args)
        self.assertNotIn('OpsiAshAssist', menu['Opsi']['tasks'])
        self.assertIn('Equipment', args['OpsiAshBeacon'])
        self.assertNotIn('DossierAfterAssist', args['OpsiAshBeacon']['OpsiAshBeacon'])
        for language in ('zh-CN', 'zh-TW', 'en-US', 'ja-JP'):
            data = json.loads(Path(f'module/config/i18n/{language}.json').read_text(encoding='utf-8'))
            self.assertNotIn('DossierAfterAssist', data['OpsiAshBeacon'])
            for group, field in (('OpsiAshAssist', 'Enable'), ('OpsiAshBeacon', 'DossierSkipAssist')):
                for key in ('name', 'help'):
                    self.assertTrue(data[group][field][key])
                    self.assertNotIn(f'{group}.{field}.', data[group][field][key])

    def test_removed_setting_is_dropped_without_changing_new_setting(self):
        for old, enabled in product((False, True), repeat=2):
            with self.subTest(old=old, enabled=enabled):
                data = {'OpsiAshBeacon': {'OpsiAshBeacon': {
                    'DossierAfterAssist': old, 'DossierSkipAssist': enabled,
                }}}
                fields = ConfigUpdater().config_update(data)['OpsiAshBeacon']['OpsiAshBeacon']
                self.assertNotIn('DossierAfterAssist', fields)
                self.assertEqual(fields['DossierSkipAssist'], enabled)


if __name__ == '__main__':
    unittest.main()
