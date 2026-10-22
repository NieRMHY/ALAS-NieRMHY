"""跨任务的公共战役续接：每日进度、紧急委托和策略隔离。"""

import copy
import unittest
from datetime import datetime
from unittest.mock import Mock, patch

from alas import AzurLaneAutoScript
from module.campaign.campaign_base import CampaignBase
from module.campaign.gems_farming import GemsEmotion, GemsFarming
from module.campaign.recovery import CampaignRecovery, campaign_recovery_scope
from module.combat.result import CombatResult
from module.config.config import TaskEnd
from module.config.deep import deep_set
from module.event.campaign_abcd import CampaignABCD
from module.event.campaign_sp import CampaignSP
from module.exception import GameNotRunningError, GameStuckError, ScriptEnd, ScriptError
from tests.test_campaign_restart_recovery import make_saved_runner
from tests.test_farming_combat_config import make_config


class CampaignTaskRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch('module.campaign.recovery.logger'))
        self.enterContext(patch('module.statistics.resource_tracking.observe_campaign_end'))
        self.enterContext(patch('module.config.config.current_time', return_value=datetime(2026, 10, 21, 12)))
        self.enterContext(patch('module.runtime.preview.set_task'))

    def owner(self, runner):
        script = object.__new__(AzurLaneAutoScript)
        script.config = runner.config
        script.device = runner.device
        script._channel_float_done = True
        return script

    def checkpoint(self, runner, name, folder):
        runner.name, runner.folder = name, folder
        runner.run_count = 0
        runner.run_limit = 0
        runner.config.override(Campaign_Name=name, Campaign_Event=folder)
        campaign = object.__new__(CampaignBase)
        campaign.config = copy.deepcopy(runner.config)
        campaign.map_is_auto_search = campaign.map_is_clear_mode = True
        campaign._recovery_map_active = True
        campaign.combat_result = CombatResult()
        runner.campaign = campaign

    def test_new_campaign_task_uses_public_entry_without_scheduler_task_list(self):
        runner = make_saved_runner()
        for config in (runner.config, runner.campaign.config):
            config.data['CustomMapTask'] = config.data.pop('Main')
            config.task.command = 'CustomMapTask'
        script = self.owner(runner)
        runner._run = Mock(side_effect=GameNotRunningError('offline'))
        with campaign_recovery_scope(script), self.assertRaises(GameNotRunningError):
            runner.run('16-4')
        self.assertIs(runner, script._campaign_recovery.runner)
        self.assertEqual('CustomMapTask', script._campaign_recovery.settings[1])

    def test_non_map_folders_and_non_device_errors_do_not_capture(self):
        for folder in ('campaign_sos', 'war_archives_20240912_cn', 'raid_20240912_cn'):
            runner = make_saved_runner()
            runner.folder = folder
            self.assertIsNone(CampaignRecovery.capture(runner))
        runner = make_saved_runner()
        script = self.owner(runner)
        runner._run = Mock(side_effect=ScriptError('script defect'))
        with campaign_recovery_scope(script), self.assertRaises(ScriptError):
            runner.run('16-4')
        self.assertNotIn('_campaign_recovery', script.__dict__)

    def test_daily_recovery_finishes_original_stage_then_records_remaining_stages(self):
        for task in ('EventA', 'EventB', 'EventC', 'EventD'):
            with self.subTest(task=task):
                config = make_config(task, Campaign={'Event': 'event_20240912_cn', 'ContinueAfterRestart': True})
                config.override(EventDaily_StageFilter='B1 > B2 > B3', EventDaily_LastStage=0,
                                Scheduler_NextRun=datetime(2026, 10, 21, 12))
                # LastStage 必须允许正常赋值，不用 override 固定住进度。
                config.overridden.pop('EventDaily_LastStage')
                def save_progress():
                    for path, value in config.modified.items():
                        deep_set(config.data, path, value)
                    config.modified.clear()
                    config.bind(task)

                config.update = Mock(side_effect=save_progress)
                config.auto_update = True
                config.task_delay = Mock()
                config.task_switched = Mock(return_value=False)
                runner = CampaignABCD(config, Mock())
                trace = []
                failed = False

                def execute(name, folder, mode, total, resume):
                    nonlocal failed
                    trace.append((name, resume, total))
                    if not resume:
                        self.checkpoint(runner, name, folder)
                    if name == 'b2' and not failed:
                        failed = True
                        raise GameNotRunningError('offline')
                    runner.run_count += 1

                runner._run = Mock(side_effect=execute)
                script = self.owner(runner)
                script.__dict__[task.lower().replace('event', 'event_')] = Mock()
                with patch('module.event.campaign_abcd.os.listdir', return_value=['b1.py', 'b2.py', 'b3.py']), \
                        patch('module.event.campaign_abcd.get_server_last_update',
                              return_value=datetime(2026, 10, 21)) as refresh, campaign_recovery_scope(script):
                    with self.assertRaises(GameNotRunningError):
                        runner.run()
                    self.assertEqual('b1', config.EventDaily_LastStage)
                    recovery = script._campaign_recovery
                    self.assertEqual('b2', recovery.run_kwargs['name'])
                    # 模拟重启跨过日更，仍应先完成保留图，不从第一关重复进入。
                    refresh.return_value = datetime(2026, 10, 22)
                    recovery.ready = True
                    recovery.prepare = Mock(return_value=True)
                    self.assertTrue(script._run(task.lower().replace('event', 'event_')))
                self.assertEqual([('b1', False, 1), ('b2', False, 1),
                                  ('b2', True, 1), ('b3', False, 1)], trace)
                self.assertEqual('b3', config.EventDaily_LastStage)
                config.task_delay.assert_called_with(server_update=True)

    def test_sp_recovery_keeps_once_per_day_scheduling(self):
        config = make_config('EventSp', Campaign={'Event': 'event_20240912_cn', 'ContinueAfterRestart': True})
        config.task_delay = Mock()
        runner = CampaignSP(config, Mock())
        trace = []

        def execute(name, folder, mode, total, resume):
            trace.append((name, resume, total))
            if not resume:
                self.checkpoint(runner, name, folder)
                raise GameNotRunningError('offline')
            runner.run_count += 1

        runner._run = Mock(side_effect=execute)
        script = self.owner(runner)
        with campaign_recovery_scope(script):
            with self.assertRaises(GameNotRunningError):
                runner.run()
            config.task_delay.assert_not_called()
            script._campaign_recovery.ready = True
            script._campaign_recovery.prepare = Mock(return_value=True)
            self.assertTrue(script._run('event_sp'))
        self.assertEqual([('sp', False, 1), ('sp', True, 1)], trace)
        config.task_delay.assert_called_once_with(server_update=True)

    def gems_runner(self, task='GemsFarming'):
        config = make_config(task, Campaign={'Name': '2-4', 'ContinueAfterRestart': True})
        config.task_switched = Mock(return_value=False)
        config.task_delay = Mock()
        runner = GemsFarming(config, Mock())
        runner.load_campaign('campaign_2_4')
        runner.config.override(Campaign_Name='campaign_2_4', Campaign_Event='campaign_main')
        campaign = runner.campaign
        campaign.map_is_clear_mode = campaign.map_is_auto_search = True
        campaign.map_is_2x_book = False
        campaign._recovery_map_active = True
        campaign.combat_result = CombatResult()
        runner.run_count, runner.run_limit = 0, 0
        return runner

    def test_gems_recovery_preserves_special_emotion_type(self):
        for task in ('GemsFarming', 'ThreeOilLowCost'):
            with self.subTest(task=task):
                runner = self.gems_runner(task)
                recovery = CampaignRecovery.capture(runner)
                runner.config.update = Mock()
                runner.campaign.config.update = Mock()
                runner.campaign.is_auto_search_running = Mock(return_value=False)
                recovery.find_state = Mock(return_value='map')
                self.assertIsInstance(runner.campaign.emotion, GemsEmotion)
                self.assertTrue(recovery.prepare(runner.config, runner.device))
                self.assertIsInstance(runner.campaign.emotion, GemsEmotion)

    def test_gems_resume_does_not_trigger_startup_flagship_rotation(self):
        runner = self.gems_runner()
        runner.config.override(GemsFarming_ChangeFlagship='ship', GemsFarming_AllowHighFlagshipLevel=False)
        runner.campaign.config.GEMS_EMOTION_TRIGGERED = False
        runner._run = Mock()
        runner.flagship_change = Mock(return_value=True)
        runner.vanguard_change = Mock(return_value=True)
        runner.run_count = 2
        runner._resume_map = True
        runner._resume_campaign_run = True
        with patch.object(GemsFarming, '_initial_flagship_check_done', False):
            runner.run('campaign_2_4')
        self.assertTrue(runner._run.call_args.kwargs['resume'])
        runner.flagship_change.assert_not_called()
        runner.vanguard_change.assert_not_called()

    def test_gems_low_emotion_uses_swap_policy_instead_of_normal_delay(self):
        runner = self.gems_runner()
        emotion = runner.campaign.emotion
        emotion.config.override(Emotion_Mode='calculate')
        emotion._check_fleet = Mock(return_value=datetime(2026, 10, 21, 13))
        emotion.config.task_delay = Mock()
        with patch('module.campaign.gems_farming.current_time', return_value=datetime(2026, 10, 21, 12)), \
                self.assertRaises(ScriptEnd):
            emotion.check_fleet(2, after_restart=True)
        emotion._check_fleet.assert_called_once_with(2)
        emotion.config.task_delay.assert_not_called()
        self.assertTrue(emotion.config.GEMS_EMOTION_TRIGGERED)

        runner.config.override(GemsFarming_ChangeFlagship='ship', GemsFarming_ChangeVanguard='ship')
        runner._run = Mock()
        runner._resume_campaign_run = True
        runner.hard_mode_override = Mock()
        runner.get_emotion = Mock(return_value=30)
        runner.flagship_change = Mock(return_value=True)
        runner.vanguard_change = Mock(return_value=True)
        runner.campaign.ensure_auto_search_exit = Mock()
        runner.config.task_switched.return_value = True
        with self.assertRaises(TaskEnd):
            runner.run('campaign_2_4')
        runner.flagship_change.assert_called_once_with()
        runner.vanguard_change.assert_called_once_with()

    def test_gems_normal_fleet_check_keeps_existing_delay_behavior(self):
        runner = self.gems_runner()
        emotion = runner.campaign.emotion
        emotion.config.override(Emotion_Mode='calculate')
        recovered = datetime(2026, 10, 21, 13)
        emotion._check_fleet = Mock(return_value=recovered)
        emotion.config.task_delay = Mock()
        with patch('module.combat.emotion.current_time', return_value=datetime(2026, 10, 21, 12)), \
                self.assertRaises(ScriptEnd):
            emotion.check_fleet(2)
        emotion.config.task_delay.assert_called_once_with(target=recovered)
        self.assertFalse(emotion.config.GEMS_EMOTION_TRIGGERED)

    def test_daily_filter_or_gems_settings_change_invalidates_credential(self):
        for group in ('EventDaily', 'GemsFarming'):
            runner = make_saved_runner()
            runner.campaign.config.data['Main'][group] = {'selection': 'before'}
            recovery = CampaignRecovery.capture(runner)
            runner.config.data['Main'][group] = {'selection': 'after'}
            self.assertFalse(recovery.matches(runner.config))

    def test_prepare_fault_keeps_existing_recovery_budget(self):
        runner = make_saved_runner()
        script = self.owner(runner)
        recovery = CampaignRecovery.capture(runner)
        recovery.attempts = 2
        recovery.run_kwargs = dict(name='16-4', folder='campaign_main', mode='normal', total=0)
        script._resuming_campaign_recovery = recovery
        recovery.prepare = Mock(side_effect=GameStuckError('navigation failed'))
        with campaign_recovery_scope(script), self.assertRaises(GameStuckError):
            recovery.resume(script.config, script.device)
        self.assertEqual(2, script._campaign_recovery.attempts)
        self.assertEqual(recovery.run_kwargs, script._campaign_recovery.run_kwargs)

    def test_new_campaign_instance_gets_new_budget_even_with_same_generation(self):
        runner = make_saved_runner()
        recovery = CampaignRecovery.capture(runner)
        recovery.attempts = 2
        recovery.restart_attempts = 2
        runner.campaign = copy.copy(runner.campaign)
        replacement = CampaignRecovery.capture(runner, recovery)
        self.assertEqual(0, replacement.attempts)
        self.assertEqual(0, replacement.restart_attempts)

    def test_scope_is_released_and_changed_inner_entry_cannot_consume_resume(self):
        runner = make_saved_runner()
        script = self.owner(runner)
        runner._run = Mock(side_effect=GameNotRunningError('offline'))
        with campaign_recovery_scope(script), self.assertRaises(GameNotRunningError):
            runner.run('16-4')
        saved = script._campaign_recovery
        with self.assertRaises(GameNotRunningError):
            runner.run('16-4')
        self.assertIs(saved, script._campaign_recovery)
        runner._resume_campaign_run = True
        runner._resume_campaign_kwargs = dict(name='16-4', folder='campaign_main', mode='normal', total=0)
        runner.config.task_stop = Mock(side_effect=TaskEnd)
        runner._run.reset_mock()
        with self.assertRaises(TaskEnd):
            runner.run('15-4')
        runner._run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
