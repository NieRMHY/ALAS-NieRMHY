"""活动连刷在下一轮出击前回选图页检查 PT，设备交互由内存状态模拟。"""

import unittest
from unittest.mock import Mock, patch

from module.campaign.campaign_event import CampaignEvent
from module.campaign.gems_farming import GemsFarming
from module.campaign.run import CampaignRun
from module.config.utils import DEFAULT_TIME
from tests.test_farming_combat_config import make_config


class CampaignPtContinueTests(unittest.TestCase):
    def make_runner(self, task='ThreeOilLowCost', limit=93100, stage='C2', gain=100, achievement='non_stop',
                    fallback=0):
        config = make_config(task, Campaign={'Name': stage, 'Event': 'event_20260908_cn'},
                             GemsFarming={'EventFallbackStage': fallback})
        config.override(EventGeneral_PtLimit=limit, EventGeneral_TimeLimit=DEFAULT_TIME,
                        StopCondition_MapAchievement=achievement, TaskBalancer_Enable=False)
        config.task_switched = Mock(return_value=False)
        config.modified.clear()
        runner_type = GemsFarming if task in ('ThreeOilLowCost', 'GemsFarming') else CampaignRun
        runner = runner_type(config=config, device=Mock())
        campaign = CampaignEvent(config=config, device=runner.device)
        runner.campaign = campaign
        runner.stage = stage.lower()
        runner.load_campaign = Mock()
        runner.ui_page_appear = Mock(return_value=False)
        runner.disable_raid_on_event = Mock()
        runner.handle_commission_notice = Mock()
        runner.status_get_gems = Mock()
        runner.get_coin = Mock(return_value=10000)
        runner.get_oil = Mock(return_value=10000)
        campaign.auto_search_oil_limit_triggered = False
        campaign.map_is_auto_search = True
        campaign.is_in_map = Mock(return_value=False)
        state = dict(page='stage', pt=93060, runs=0)
        trace = []

        def navigate(**kwargs):
            state['page'] = 'stage'
            trace.append('navigate')

        def read_pt():
            self.assertEqual(state['page'], 'stage', '必须返回可读取 PT 的选图页')
            trace.append(('pt', state['pt']))
            return state['pt']

        def battle():
            state['runs'] += 1
            self.assertLessEqual(state['runs'], 2, '测试最多允许两轮出击')
            state['pt'] += gain
            state['page'] = 'menu'
            trace.append('battle')

        campaign.is_in_auto_search_menu = Mock(side_effect=lambda: state['page'] == 'menu')
        campaign.ensure_campaign_ui = Mock(side_effect=navigate)
        campaign.get_event_pt = Mock(side_effect=read_pt)
        campaign.run = Mock(side_effect=battle)
        campaign.ensure_auto_search_exit = Mock()
        return runner, state, trace

    def run_twice(self, runner, stage='C2'):
        with patch.object(GemsFarming, '_initial_flagship_check_done', True):
            runner.run(stage, folder='event_20260908_cn', total=2)

    def test_pt_reaching_limit_prevents_next_run(self):
        for task, achievement in (
            ('ThreeOilLowCost', 'non_stop'), ('GemsFarming', 'non_stop'),
            ('Event', 'non_stop'), ('Event', 'map_3_stars'),
        ):
            with self.subTest(task=task, achievement=achievement):
                runner, state, trace = self.make_runner(task=task, achievement=achievement)
                self.run_twice(runner)
                self.assertEqual(state['runs'], 1)
                self.assertEqual(trace, ['navigate', ('pt', 93060), 'battle', 'navigate', ('pt', 93160)])
                self.assertIs(runner.config.modified.get(f'{task}.Scheduler.Enable'), False)
                self.assertNotIn(f'{task}.Campaign.Name', runner.config.modified)
                runner.campaign.ensure_auto_search_exit.assert_called_once_with()

    def test_below_limit_rechecks_before_continuing(self):
        runner, state, trace = self.make_runner(gain=10)
        self.run_twice(runner)
        self.assertEqual(state['runs'], 2)
        self.assertEqual(trace, ['navigate', ('pt', 93060), 'battle', 'navigate', ('pt', 93070), 'battle'])
        self.assertNotIn('ThreeOilLowCost.Scheduler.Enable', runner.config.modified)

    def test_pt_fallback_ends_event_run_before_next_dispatch(self):
        for task in ('ThreeOilLowCost', 'GemsFarming'):
            with self.subTest(task=task):
                runner, state, trace = self.make_runner(task=task, fallback='7-2')
                self.run_twice(runner)
                self.assertEqual(state['runs'], 1)
                self.assertEqual(trace, ['navigate', ('pt', 93060), 'battle', 'navigate', ('pt', 93160)])
                self.assertEqual(runner.config.modified[f'{task}.Campaign.Name'], '7-2')
                self.assertEqual(runner.config.modified[f'{task}.Campaign.Event'], 'campaign_main')
                self.assertNotIn(f'{task}.Scheduler.Enable', runner.config.modified)
                runner.campaign.ensure_auto_search_exit.assert_called_once_with()

    def test_no_pt_limit_retains_direct_continue(self):
        for limit in (0, -1):
            with self.subTest(limit=limit):
                runner, state, trace = self.make_runner(limit=limit)
                self.run_twice(runner)
                self.assertEqual(state['runs'], 2)
                self.assertEqual(trace, ['navigate', ('pt', 93060), 'battle', 'battle'])

    def test_main_farming_retains_direct_continue_and_does_not_read_pt(self):
        for task in ('ThreeOilLowCost', 'GemsFarming', 'Main'):
            with self.subTest(task=task):
                runner, state, trace = self.make_runner(task=task, stage='2-4')
                self.run_twice(runner, stage='2-4')
                self.assertEqual(state['runs'], 2)
                self.assertEqual(trace.count('navigate'), 1)
                if task != 'Main':
                    runner.campaign.get_event_pt.assert_not_called()

    def test_continue_uses_existing_pt_limit_formats_and_task_scope(self):
        for task in ('ThreeOilLowCost', 'GemsFarming', 'Event', 'WarArchives'):
            for limit in ('93,100', '93，100', '93.100', '"93100"'):
                with self.subTest(task=task, limit=limit):
                    runner, _, _ = self.make_runner(task=task, limit=limit)
                    runner.run_count = 1
                    self.assertEqual(runner.can_use_auto_search_continue(), task == 'WarArchives')


if __name__ == '__main__':
    unittest.main()
