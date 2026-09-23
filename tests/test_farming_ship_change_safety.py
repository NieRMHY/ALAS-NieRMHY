"""换船失败必须停止当前任务，模式切换和船坞提示不能伪造成功。"""

import unittest
from unittest.mock import Mock, patch

from module.campaign.gems_farming import GemsFarming
from module.campaign.run import CampaignRun
from module.config.config import TaskEnd
from module.exception import (
    EmulatorNotRunningError, GameStuckError, GameTooManyClickError, HardNotSatisfied, RequestHumanTakeover,
)
from tests.test_fleet_selection import TASKS, runner


class ShipChangeSafetyTests(unittest.TestCase):
    def test_hard_normal_hard_roundtrip_restores_all_navigation_methods(self):
        for task in TASKS:
            instance = runner(task)
            methods = ('_fleet_detail_enter', '_ship_detail_enter', '_fleet_back')
            normal = {method: getattr(instance, method).__func__ for method in methods}
            for mode in ('hard', 'normal', 'hard', 'normal'):
                instance.campaign.config.Campaign_Mode = mode
                instance.hard_mode_override()
                self.assertEqual(instance.hard_mode, mode == 'hard')
                for method in methods:
                    if mode == 'normal':
                        self.assertIs(getattr(instance, method).__func__, normal[method])
                    else:
                        self.assertIs(getattr(instance, method).__func__, getattr(instance, method + '_hard').__func__)

    def test_dock_tip_is_handled_before_waiting_for_confirmed_dock(self):
        for task in TASKS:
            instance = runner(task)
            instance.page_fleet_check_button = object()
            instance.loop = Mock(return_value=iter(range(3)))
            instance.appear = Mock(side_effect=[False, False, True])
            instance.handle_game_tips = Mock(return_value=True)
            self.assertTrue(instance.dock_enter('slot'))
            instance.handle_game_tips.assert_called_once_with()

    def test_dock_timeout_is_not_success(self):
        for task in TASKS:
            instance = runner(task)
            instance.page_fleet_check_button = object()
            instance.loop = Mock(return_value=iter(range(2)))
            instance.appear = Mock(return_value=False)
            instance.handle_game_tips = Mock(return_value=False)
            self.assertFalse(instance.dock_enter('slot'))

    def test_failed_entry_cannot_claim_ship_was_changed(self):
        for task in TASKS:
            for position in ('flagship', 'vanguard'):
                for hard, entry_results in ((False, [False]), (True, [False]), (True, [True, False])):
                    with self.subTest(task=task.__name__, position=position, hard=hard, entries=entry_results):
                        instance = runner(task)
                        instance.campaign.config.Campaign_Mode = 'hard' if hard else 'normal'
                        instance.hard_mode_override()
                        instance.dock_enter = Mock(side_effect=entry_results)
                        instance.ship_down_hard = Mock()
                        with self.assertRaises(RequestHumanTakeover):
                            getattr(instance, position + '_change_execute')()

    def test_equipment_or_selection_failure_disables_task_without_retry(self):
        for task in TASKS:
            for position in ('flagship', 'vanguard'):
                for failed_step in ('clear_all_equip', position + '_change_execute', 'apply_equip_code'):
                    with self.subTest(task=task.__name__, position=position, failed=failed_step):
                        instance = runner(task, GemsFarming_ChangeFlagship='ship_equip', GemsFarming_ChangeVanguard='ship_equip')
                        instance.hard_mode_override()
                        instance.config.Scheduler_Enable = True
                        instance.config.task_stop = Mock(side_effect=TaskEnd)
                        events = Mock()
                        methods = ('_fleet_detail_enter', '_ship_detail_enter', 'clear_all_equip',
                                   '_fleet_back', position + '_change_execute', 'apply_equip_code')
                        for method in methods:
                            setattr(instance, method, getattr(events, method))
                        getattr(events, failed_step).side_effect = RequestHumanTakeover('测试失败')
                        instance.last_code = '旧缓存'
                        with self.assertRaises(TaskEnd):
                            getattr(instance, position + '_change')()
                        self.assertFalse(instance.config.Scheduler_Enable)
                        instance.config.task_stop.assert_called_once_with()
                        self.assertIsNone(instance.last_code)
                        if failed_step == 'clear_all_equip':
                            getattr(events, position + '_change_execute').assert_not_called()
                        if failed_step != 'apply_equip_code':
                            events.apply_equip_code.assert_not_called()

    def test_no_low_level_replacement_delays_instead_of_starting_another_battle(self):
        instance = runner(GemsFarming, StopCondition_RunCount=0, GemsFarming_DelayTaskIFNoFlagship=False)
        instance.config.task_switched = Mock(return_value=False)
        instance.config.task_delay = Mock()
        instance.config.task_stop = Mock(side_effect=TaskEnd)
        instance.get_emotion = Mock(return_value=100)
        instance.vanguard_change = Mock(return_value=True)
        instance.flagship_change = Mock(return_value=False)
        instance.campaign.ensure_auto_search_exit = Mock()
        with patch.object(GemsFarming, '_initial_flagship_check_done', False), \
                patch.object(CampaignRun, 'run') as campaign_run:
            with self.assertRaises(TaskEnd):
                instance.run('C2', folder='event_test')
            self.assertFalse(GemsFarming._initial_flagship_check_done)
        campaign_run.assert_called_once()
        instance.config.task_delay.assert_called_once_with(minute=60)
        instance.campaign.ensure_auto_search_exit.assert_called_once_with()

    def test_hard_fleet_recovery_preserves_stop_and_does_not_ignore_failed_selection(self):
        for error in (HardNotSatisfied(), RequestHumanTakeover('Hard not satisfied')):
            for stops in (True, False):
                with self.subTest(error=type(error).__name__, stops=stops):
                    instance = runner(GemsFarming, StopCondition_RunCount=0)
                    instance.config.task_delay = Mock()
                    instance.config.task_stop = Mock(side_effect=TaskEnd)
                    instance.campaign.ensure_auto_search_exit = Mock()
                    instance.vanguard_change = Mock(side_effect=TaskEnd) if stops else Mock(return_value=False)
                    instance.flagship_change = Mock(return_value=True)
                    with patch.object(GemsFarming, '_initial_flagship_check_done', False), \
                            patch.object(CampaignRun, 'run', side_effect=error):
                        with self.assertRaises(TaskEnd):
                            instance.run('C2', folder='event_test')
                    if stops:
                        instance.flagship_change.assert_not_called()
                    else:
                        instance.config.task_delay.assert_called_once_with(minute=60)

    def test_interrupted_equipment_transfer_is_not_automatically_restarted(self):
        for error in (GameStuckError, GameTooManyClickError, EmulatorNotRunningError):
            instance = runner(GemsFarming, GemsFarming_ChangeFlagship='ship_equip')
            instance.hard_mode_override()
            instance.config.task_stop = Mock(side_effect=TaskEnd)
            instance._fleet_detail_enter = Mock()
            instance._ship_detail_enter = Mock()
            instance.clear_all_equip = Mock(side_effect=error)
            instance.flagship_change_execute = Mock()
            with self.assertRaises(TaskEnd):
                instance.flagship_change()
            self.assertFalse(instance.config.Scheduler_Enable)
            instance.flagship_change_execute.assert_not_called()
            self.assertIsNone(instance.last_code)

    def test_disabled_flagship_change_does_not_consume_initial_check(self):
        instance = runner(GemsFarming, GemsFarming_ChangeFlagship='disabled', StopCondition_RunCount=0)
        with patch.object(GemsFarming, '_initial_flagship_check_done', False), \
                patch.object(CampaignRun, 'run'):
            instance.run('C2', folder='event_test')
            self.assertFalse(GemsFarming._initial_flagship_check_done)


if __name__ == '__main__':
    unittest.main()
