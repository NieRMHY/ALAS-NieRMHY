"""低耗任务使用真实活动地图和难度判断，设备画面由内存状态模拟。"""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.campaign.gems_farming import GemsFarming
from module.campaign.run import CampaignRun
from module.map.assets import (
    FLEET_PREPARATION, MAP_MODE_SWITCH_HARD, MAP_MODE_SWITCH_NORMAL,
    MAP_PREPARATION, MAP_PREPARATION_HARD,
)
from tests.test_farming_combat_config import make_config


class FarmingStageNavigationTests(unittest.TestCase):
    def prepare_runner(self, task='ThreeOilLowCost', stage='C2', current_mode='normal', retirement=False):
        config = make_config(task, Campaign={'Name': stage, 'Event': 'event_20260908_cn'})
        runner = GemsFarming(config=config, device=Mock())
        name, folder = runner.handle_stage_name(stage, config.Campaign_Event)
        config.override(Campaign_Name=name, Campaign_Event=folder)
        runner.load_campaign(name, folder)
        campaign = runner.campaign
        normal_name = campaign.campaign_get_mode_names(name)[0]
        campaign.stage_entrance = {normal_name: SimpleNamespace(name=normal_name)}
        campaign.ui_goto_event = Mock()
        campaign.campaign_ensure_mode_20241219 = Mock()
        campaign.campaign_ensure_aside_20241219 = Mock()
        campaign.campaign_ensure_chapter = Mock()
        # 新活动共用 A/C 入口，导航只确定目标难度，需在准备页真正切换。
        campaign.ensure_campaign_ui(name)
        runner.hard_mode_override()
        state = dict(page='stage', mode=current_mode, pending=None, shots=0, retired=False)
        trace = []

        def screenshot():
            state['shots'] += 1
            if state['shots'] > 12:
                raise RuntimeError('模拟设备截图超时')
            if state['pending']:
                state['mode'], state['pending'] = state['pending'], None

        def appear(button, **kwargs):
            if button is FLEET_PREPARATION:
                return state['page'] == 'fleet'
            if button is MAP_PREPARATION:
                return state['page'] == 'preparation' and state['mode'] == 'normal'
            if button is MAP_PREPARATION_HARD:
                return state['page'] == 'preparation' and state['mode'] == 'hard'
            return button is campaign.ENTRANCE and state['page'] == 'stage'

        def click(button):
            if button is MAP_MODE_SWITCH_HARD:
                trace.append('switch_hard')
                state['pending'] = 'hard'

        def appear_then_click(button, **kwargs):
            if not appear(button, **kwargs):
                return False
            if button is campaign.ENTRANCE:
                state['page'] = 'preparation'
            else:
                trace.append('prepare_' + state['mode'])
                self.assertEqual(state['mode'], 'hard', '换船前必须先把 A/B 准备页切到 C/D')
                state['page'] = 'retirement' if retirement and not state['retired'] else 'fleet'
            return True

        def handle_retirement():
            if state['page'] != 'retirement':
                return False
            state.update(page='stage', mode='normal', retired=True)
            return True

        def ui_click(**kwargs):
            state['page'] = 'preparation'
            self.assertTrue(kwargs['check_button']())

        runner.device.screenshot.side_effect = screenshot
        runner.device.click.side_effect = click
        runner.appear = Mock(side_effect=appear)
        runner.appear_then_click = Mock(side_effect=appear_then_click)
        runner.handle_retirement = Mock(side_effect=handle_retirement)
        runner.ui_click = Mock(side_effect=ui_click)
        campaign.match_template_color = Mock(side_effect=lambda button, **kwargs: (
            button is MAP_MODE_SWITCH_NORMAL and state['page'] == 'preparation' and state['mode'] == 'normal'))
        campaign._is_mod_switch_hard_appear = Mock(side_effect=lambda **kwargs: (
            state['page'] == 'preparation' and state['mode'] == 'hard'))
        return runner, state, trace

    def test_first_ship_change_switches_c2_and_d3_before_fleet_preparation(self):
        for task in ('ThreeOilLowCost', 'GemsFarming'):
            for stage in ('C2', 'D3'):
                with self.subTest(task=task, stage=stage):
                    runner, state, trace = self.prepare_runner(task, stage)
                    self.assertTrue(runner.hard_mode)
                    # 运行器原配置仍为 normal；地图合并后的配置才包含开关能力和目标难度。
                    self.assertEqual(runner.config.Campaign_Mode, 'normal')
                    self.assertFalse(runner.config.MAP_HAS_MODE_SWITCH)
                    self.assertTrue(runner.campaign.config.MAP_HAS_MODE_SWITCH)
                    runner._fleet_detail_enter_hard(1)
                    self.assertEqual(trace, ['switch_hard', 'prepare_hard'])
                    self.assertEqual(state['page'], 'fleet')

    def test_already_hard_and_legacy_maps_do_not_toggle_again(self):
        for has_switch in (True, False):
            with self.subTest(has_switch=has_switch):
                runner, state, trace = self.prepare_runner(current_mode='hard')
                runner.campaign.config.override(MAP_HAS_MODE_SWITCH=has_switch)
                runner.campaign.stage_entrance['c2'] = runner.campaign.ENTRANCE
                runner._fleet_detail_enter_hard(1)
                self.assertEqual(trace, ['prepare_hard'])
                self.assertEqual(state['page'], 'fleet')

    def test_retirement_return_checks_difficulty_again(self):
        runner, state, trace = self.prepare_runner(retirement=True)
        runner._fleet_detail_enter_hard(1)
        self.assertEqual(trace, ['switch_hard', 'prepare_hard', 'switch_hard', 'prepare_hard'])
        self.assertTrue(state['retired'])
        self.assertEqual(state['page'], 'fleet')

    def test_unconfirmed_mode_does_not_enter_normal_fleet(self):
        runner, _, trace = self.prepare_runner()
        runner.campaign.match_template_color.return_value = False
        runner.campaign.match_template_color.side_effect = None
        runner.campaign._is_mod_switch_hard_appear.return_value = False
        runner.campaign._is_mod_switch_hard_appear.side_effect = None
        with self.assertRaisesRegex(RuntimeError, '模拟设备截图超时'):
            runner._fleet_detail_enter_hard(1)
        self.assertEqual(trace, [])

    def test_farming_wrapper_preserves_requested_campaign_mode(self):
        for mode in ('normal', 'hard'):
            with self.subTest(mode=mode):
                config = make_config('ThreeOilLowCost', GemsFarming={'ChangeFlagship': 'disabled'})
                config.override(GemsFarming_ChangeFlagship='disabled')
                runner = GemsFarming(config=config, device=Mock())
                with patch.object(CampaignRun, 'run') as run, \
                        patch.object(GemsFarming, '_initial_flagship_check_done', False):
                    runner.run('C2', folder='event_20260908_cn', mode=mode, total=1)
                run.assert_called_once_with(name='C2', folder='event_20260908_cn', mode=mode, total=1)


if __name__ == '__main__':
    unittest.main()
