"""公共结算、各任务心情策略与真实失败截图的离线回归。"""

import unittest
from itertools import product
from pathlib import Path
from unittest.mock import MagicMock, Mock, call, patch

import numpy as np

import module.combat.emotion as emotion_source
from dev_tools.emotion_simulate import Clock, LuaOracle, MemoryConfig, QuietLogger, ShipSpec
from module.base.base import ModuleBase
from module.base.utils import load_image
from module.campaign.gems_farming import GemsCampaignOverride
from module.coalition.coalition_scuttle import CoalitionScuttleCombat, CoalitionScuttleRun
from module.coalition.combat import CoalitionCombat
from module.coalition.assets import COALITION_REWARD_CONFIRM, SCUTTLE_CONFIRM
from module.combat.assets import (
    BATTLE_STATUS_S, BATTLE_STATUS_A, BATTLE_STATUS_B, BATTLE_STATUS_C, BATTLE_STATUS_D,
    EXP_INFO_S, EXP_INFO_A, EXP_INFO_B, EXP_INFO_C, EXP_INFO_D, OPTS_INFO_D,
)
from module.combat.auto_search_combat import AutoSearchCombat
from module.exception import CampaignEnd
from module.handler.assets import AUTO_SEARCH_MAP_OPTION_ON, AUTO_SEARCH_MAP_OPTION_OFF, FLEET_UNAVAILABLE, GET_MISSION
from module.map.assets import FLEET_NUM_1, FLEET_NUM_2, SWITCH_OVER, WITHDRAW
from module.guild.assets import BATTLE_STATUS_CF
from module.raid.combat import RaidCombat
from module.raid.scuttle import RaidScuttleCombat, RaidScuttleRun
from module.raid.affection import RaidAffectionRun
from tests.test_auto_search_defeat import ScreenReplay, retreat_frames, screen


FIXTURES = Path(__file__).parent / 'fixtures' / 'combat_defeat'


class PixelReplay(ScreenReplay):
    """图片帧调用正式识别器，符号帧仅模拟战斗与退出页。"""

    def appear(self, button, **kwargs):
        if isinstance(self.device.image, np.ndarray):
            return ModuleBase.appear(self.campaign, button, **kwargs)
        return super().appear(button, **kwargs)

    def make_campaign(self, *args, **kwargs):
        campaign = super().make_campaign(*args, **kwargs)
        campaign.is_combat_executing.side_effect = lambda: (
            isinstance(self.device.image, frozenset) and 'COMBAT' in self.device.image)
        campaign.is_combat_loading.side_effect = lambda: (
            AutoSearchCombat.is_combat_loading(campaign) if isinstance(self.device.image, np.ndarray)
            else 'LOADING' in self.device.image)
        campaign.is_in_stage.side_effect = lambda: (
            isinstance(self.device.image, frozenset) and 'STAGE' in self.device.image)
        campaign.is_in_auto_search_menu.side_effect = lambda: False
        return campaign


class CombatScreenshotTests(unittest.TestCase):
    def test_unavailable_body_prevents_real_commission_false_positive(self):
        replay = PixelReplay([load_image(str(FIXTURES / 'unavailable.png'))])
        campaign = replay.make_campaign()
        with patch('module.base.timer.time', side_effect=lambda: replay.time):
            # 原委托素材确实命中同一个「确定」，正文检测应阻止它抢走弹窗。
            self.assertTrue(campaign.appear(GET_MISSION, offset=(30, 30)))
            self.assertTrue(campaign.appear(FLEET_UNAVAILABLE, offset=(30, 30)))
            self.assertFalse(campaign.handle_urgent_commission())
        self.assertEqual(replay.clicks, [])

    def test_defeat_and_unavailable_are_different_positive_signals(self):
        for name, defeat, unavailable in (('defeat.png', True, False), ('unavailable.png', False, True)):
            with self.subTest(frame=name):
                replay = PixelReplay([load_image(str(FIXTURES / name))])
                campaign = replay.make_campaign()
                self.assertEqual(campaign.appear(OPTS_INFO_D, offset=(30, 30)), defeat)
                self.assertEqual(campaign.appear(FLEET_UNAVAILABLE, offset=(30, 30)), unavailable)

    def test_raw_failure_sequence_retires_without_restarting_or_commission(self):
        for cls, policy in product((AutoSearchCombat, GemsCampaignOverride), ('withdraw_stop', 'withdraw_continue')):
            with self.subTest(cls=cls.__name__, policy=policy):
                frames = retreat_frames(
                    screen('COMBAT'), load_image(str(FIXTURES / 'defeat.png')),
                    screen(EXP_INFO_C), load_image(str(FIXTURES / 'unavailable.png')),
                    load_image(str(FIXTURES / 'map_fleet2.png')))
                replay = PixelReplay(frames)
                campaign = replay.make_campaign(cls, policy)
                with self.assertRaises(CampaignEnd):
                    replay.run()
                self.assertEqual(campaign.emotion.reduce.call_args_list, [call(1), call(1, shipwreck=True)])
                self.assertIn(FLEET_UNAVAILABLE.name, replay.clicks)
                self.assertIn(WITHDRAW.name, replay.clicks)
                self.assertNotIn(GET_MISSION.name, replay.clicks)
                self.assertNotIn(AUTO_SEARCH_MAP_OPTION_ON.name, replay.clicks)
                self.assertNotIn(AUTO_SEARCH_MAP_OPTION_OFF.name, replay.clicks)

    def test_stopped_auto_search_matches_on_template_but_not_running_state(self):
        replay = PixelReplay([load_image(str(FIXTURES / 'map_fleet2.png'))])
        campaign = replay.make_campaign()
        # 开关文字相同，模板会同时命中两态；颜色才区分开关状态。
        self.assertTrue(campaign.appear(AUTO_SEARCH_MAP_OPTION_ON, offset=campaign._auto_search_offset))
        self.assertTrue(campaign.appear(AUTO_SEARCH_MAP_OPTION_OFF, offset=campaign._auto_search_offset))
        self.assertFalse(campaign.appear(AUTO_SEARCH_MAP_OPTION_ON))
        self.assertTrue(campaign.appear(AUTO_SEARCH_MAP_OPTION_OFF))
        self.assertFalse(campaign.is_auto_search_running())
        self.assertEqual(replay.clicks, [])

    def test_logged_four_toggle_sequence_retires_with_zero_auto_search_clicks(self):
        stopped_map = load_image(str(FIXTURES / 'map_fleet2.png'))
        for cls, policy in product((AutoSearchCombat, GemsCampaignOverride),
                                   ('withdraw_stop', 'withdraw_continue')):
            with self.subTest(cls=cls.__name__, policy=policy):
                # 实机日志顺序：经验页、地图过渡、无可用舰队、自动换二队后的地图。
                replay = PixelReplay([
                    screen('COMBAT'), load_image(str(FIXTURES / 'defeat.png')),
                    screen(EXP_INFO_D), stopped_map,
                    load_image(str(FIXTURES / 'unavailable.png')),
                    *[stopped_map] * 8, screen('STAGE')])
                campaign = replay.make_campaign(cls, policy)
                with self.assertRaises(CampaignEnd):
                    replay.run()
                self.assertIn(FLEET_UNAVAILABLE.name, replay.clicks)
                self.assertIn(WITHDRAW.name, replay.clicks)
                self.assertNotIn(AUTO_SEARCH_MAP_OPTION_ON.name, replay.clicks)
                self.assertNotIn(AUTO_SEARCH_MAP_OPTION_OFF.name, replay.clicks)
                self.assertEqual(campaign.emotion.reduce.call_args_list, [call(1), call(1, shipwreck=True)])

    def test_actual_fleet2_frame_allows_explicit_switch_policy(self):
        replay = PixelReplay([
            screen('COMBAT'), load_image(str(FIXTURES / 'defeat.png')),
            screen(EXP_INFO_D), load_image(str(FIXTURES / 'unavailable.png')),
            load_image(str(FIXTURES / 'map_fleet2.png')),
            screen(AUTO_SEARCH_MAP_OPTION_ON, FLEET_NUM_2)])
        campaign = replay.make_campaign(policy='switch_fleet')
        replay.run()
        self.assertFalse(campaign._withdraw)
        self.assertIn(AUTO_SEARCH_MAP_OPTION_OFF.name, replay.clicks)
        self.assertNotIn(WITHDRAW.name, replay.clicks)
        self.assertNotIn(GET_MISSION.name, replay.clicks)

    def test_centered_body_shift_does_not_move_fixed_confirm_button(self):
        original = load_image(str(FIXTURES / 'unavailable.png'))
        x1, y1, x2, y2 = FLEET_UNAVAILABLE.area
        for shift in (-100, 100):
            with self.subTest(body_shift=shift):
                shifted = original.copy()
                shifted[y1:y2, x1:x2] = 0
                shifted[y1:y2, x1 + shift:x2 + shift] = original[y1:y2, x1:x2]
                replay = PixelReplay([
                    screen('COMBAT'), shifted, shifted,
                    load_image(str(FIXTURES / 'map_fleet2.png')),
                    screen(AUTO_SEARCH_MAP_OPTION_ON, FLEET_NUM_2)])
                campaign = replay.make_campaign(policy='switch_fleet')
                confirm_areas = []

                def click(button):
                    if button.name == FLEET_UNAVAILABLE.name:
                        confirm_areas.append(tuple(button.button))
                    replay.click(button)

                campaign.device.click.side_effect = click
                replay.run()
                self.assertEqual(confirm_areas, [(553, 481, 728, 541)])
                self.assertNotIn(GET_MISSION.name, replay.clicks)
                self.assertEqual(campaign.emotion.reduce.call_args_list, [call(1), call(1, shipwreck=True)])


class CombatResultTests(unittest.TestCase):
    def test_fleet_popup_without_captured_defeat_still_records_failure_once(self):
        replay = ScreenReplay(retreat_frames(
            screen('COMBAT'), screen(EXP_INFO_C), *[screen(FLEET_UNAVAILABLE, GET_MISSION)] * 5))
        campaign = replay.make_campaign()
        with self.assertRaises(CampaignEnd):
            replay.run()
        self.assertEqual(campaign._defeat_count, 1)
        self.assertEqual(campaign.emotion.reduce.call_args_list, [call(1), call(1, shipwreck=True)])
        self.assertNotIn(GET_MISSION.name, replay.clicks)

    def test_reversed_fleet_order_switches_using_displayed_fleet_number(self):
        replay = ScreenReplay([
            screen('COMBAT'), screen(OPTS_INFO_D), screen(FLEET_UNAVAILABLE),
            screen(AUTO_SEARCH_MAP_OPTION_OFF, FLEET_NUM_1),
            screen(AUTO_SEARCH_MAP_OPTION_ON, FLEET_NUM_1)])
        campaign = replay.make_campaign(policy='switch_fleet')
        campaign.config.FLEET_2 = True
        campaign.config.Fleet_FleetOrder = 'fleet1_boss_fleet2_mob'
        self.assertTrue(campaign.fleets_reversed)
        replay.run(fleet_index=2)
        self.assertFalse(campaign._withdraw)
        self.assertEqual(campaign.emotion.reduce.call_args_list, [call(2), call(2, shipwreck=True)])
        self.assertNotIn(WITHDRAW.name, replay.clicks)

    def test_drop_capture_cooldown_does_not_delay_recording_or_repeat_clicks(self):
        replay = ScreenReplay([screen(BATTLE_STATUS_A)])
        campaign = replay.make_campaign(RaidCombat)
        campaign.combat_result_reset(emotion_reduce=True)
        campaign.battle_status_click_interval = 7
        drop = Mock()
        with patch('module.base.timer.time', side_effect=lambda: replay.time):
            campaign.interval_reset(BATTLE_STATUS_A, interval=7)
            self.assertFalse(campaign.handle_battle_status(drop=drop))
            self.assertEqual(replay.clicks, [])
            campaign.emotion.reduce.assert_called_once_with(1, shipwreck=True)
            replay.time += 8
            self.assertTrue(campaign.handle_battle_status(drop=drop))
            self.assertFalse(campaign.handle_battle_status(drop=drop))
        drop.handle_add.assert_called_once_with(campaign)
        self.assertEqual(replay.clicks, [BATTLE_STATUS_A.name])

    def test_success_grades_reduce_once_in_both_result_pages(self):
        for battle, exp, penalty in ((BATTLE_STATUS_S, EXP_INFO_S, False),
                                     (BATTLE_STATUS_A, EXP_INFO_A, True),
                                     (BATTLE_STATUS_B, EXP_INFO_B, True)):
            with self.subTest(grade=battle.name):
                replay = ScreenReplay([screen('COMBAT'), screen(battle), screen(battle), screen(exp),
                                       screen(exp), screen(AUTO_SEARCH_MAP_OPTION_ON)])
                campaign = replay.make_campaign()
                replay.run(fleet_index=2)
                expected = [call(2)] + ([call(2, shipwreck=True)] if penalty else [])
                self.assertEqual(campaign.emotion.reduce.call_args_list, expected)
                self.assertFalse(campaign.combat_result.defeated)

    def test_c_and_d_use_shared_defeat_even_without_fleet_popup(self):
        for cls, grade, policy in product(
                (AutoSearchCombat, GemsCampaignOverride),
                (BATTLE_STATUS_C, BATTLE_STATUS_D, EXP_INFO_C, EXP_INFO_D),
                ('withdraw_stop', 'withdraw_continue', 'switch_fleet')):
            with self.subTest(cls=cls.__name__, grade=grade.name, policy=policy):
                prefix = [screen('COMBAT'), screen(grade), screen(OPTS_INFO_D)]
                frames = retreat_frames(*prefix, screen(AUTO_SEARCH_MAP_OPTION_ON, FLEET_NUM_1))
                replay = ScreenReplay(frames)
                campaign = replay.make_campaign(cls, policy)
                with self.assertRaises(CampaignEnd):
                    replay.run()
                self.assertIn(WITHDRAW.name, replay.clicks)
                self.assertNotIn(SWITCH_OVER.name, replay.clicks)
                self.assertNotIn(AUTO_SEARCH_MAP_OPTION_OFF.name, replay.clicks)
                self.assertTrue(campaign.combat_result.defeated)
                self.assertEqual(campaign.emotion.reduce.call_args_list, [call(1), call(1, shipwreck=True)])

    def test_switch_cannot_resume_damaged_same_fleet(self):
        replay = ScreenReplay([
            screen('COMBAT'), screen(OPTS_INFO_D), screen(EXP_INFO_C),
            screen(AUTO_SEARCH_MAP_OPTION_ON, FLEET_NUM_1),
            *[screen(WITHDRAW, SWITCH_OVER, FLEET_NUM_1, AUTO_SEARCH_MAP_OPTION_OFF)] * 5,
            screen('STAGE')])
        campaign = replay.make_campaign(policy='switch_fleet')
        with self.assertRaises(CampaignEnd):
            replay.run()
        self.assertIn(WITHDRAW.name, replay.clicks)
        self.assertNotIn(AUTO_SEARCH_MAP_OPTION_OFF.name, replay.clicks)
        self.assertNotIn(AUTO_SEARCH_MAP_OPTION_ON.name, replay.clicks)
        self.assertNotIn(SWITCH_OVER.name, replay.clicks)

    def test_normal_and_scuttle_tasks_share_defeat_but_keep_separate_policies(self):
        classes = (RaidCombat, RaidScuttleCombat, RaidScuttleRun,
                   CoalitionCombat, CoalitionScuttleCombat, CoalitionScuttleRun)
        for cls in classes:
            with self.subTest(cls=cls.__name__):
                replay = ScreenReplay([screen(EXP_INFO_A), screen(OPTS_INFO_D), screen(OPTS_INFO_D)])
                campaign = replay.make_campaign(cls)
                campaign.combat_result_reset(emotion_reduce=True, fleet_index=2)
                with patch('module.base.timer.time', side_effect=lambda: replay.time):
                    campaign.handle_exp_info()
                    replay.screenshot()
                    campaign.handle_combat_defeat()
                    replay.screenshot()
                    campaign.handle_combat_defeat()
                expected = [call(2, shipwreck=True)] if campaign.combat_shipwreck_emotion else []
                self.assertEqual(campaign.emotion.reduce.call_args_list, expected)
                self.assertTrue(campaign.combat_result.defeated)
                self.assertFalse(getattr(campaign, '_withdraw', False))

    def test_raid_full_combat_initializes_and_resets_result_context(self):
        for cls in (RaidCombat, RaidScuttleRun):
            replay = ScreenReplay([screen('COMBAT'), screen(BATTLE_STATUS_A), screen(EXP_INFO_A), screen('END')])
            campaign = replay.make_campaign(cls)
            campaign.config.campaign_name = 'test_raid'
            campaign.config.DropRecord_CombatRecord = 'do_not'
            campaign.stat = MagicMock()
            campaign.combat_preparation = Mock(side_effect=lambda **kw: campaign.emotion.reduce(kw['fleet_index']))
            for _ in range(2):
                replay.load([screen('COMBAT'), screen(BATTLE_STATUS_A), screen(EXP_INFO_A), screen('END')])
                with patch('module.base.timer.time', side_effect=lambda: replay.time):
                    campaign.combat(balance_hp=False, emotion_reduce=True, auto_mode='combat_auto',
                                    submarine_mode='do_not_use', save_get_items=False, fleet_index=2,
                                    expected_end=lambda: 'END' in replay.device.image)
            expected = [call(2)] + ([call(2, shipwreck=True)] if campaign.combat_shipwreck_emotion else [])
            self.assertEqual(campaign.emotion.reduce.call_args_list, expected * 2)

    def test_coalition_base_cost_and_result_cost_are_independent(self):
        for cls, fleet in product((CoalitionCombat, CoalitionScuttleRun), ('single', 'multi')):
            with self.subTest(cls=cls.__name__, fleet=fleet):
                replay = ScreenReplay([screen('COMBAT'), screen(EXP_INFO_A)])
                campaign = replay.make_campaign(cls)
                campaign.config.Coalition_Fleet = fleet
                for i in range(4):
                    campaign.battle_count = i
                    replay.load([screen('COMBAT'), screen(EXP_INFO_A)])
                    with patch('module.base.timer.time', side_effect=lambda: replay.time):
                        campaign.auto_search_combat_execute(
                            emotion_reduce=campaign.coalition_emotion_reduce(),
                            fleet_index=i + 1 if cls is CoalitionScuttleRun else 1,
                            shipwreck_reduce=True)
                if cls is CoalitionScuttleRun:
                    # Modify by MHY, 连战1/2队各记一场，后续牺牲队不扣基础或额外心情。
                    self.assertEqual(campaign.emotion.reduce.call_args_list, [call(1), call(2)])
                    self.assertEqual(campaign.config.CoalitionScuttle_Fleet1Affection, 0.0625)
                    self.assertEqual(campaign.config.CoalitionScuttle_Fleet2Affection, 0.0625)
                else:
                    self.assertEqual(campaign.emotion.reduce.call_args_list.count(call(1)),
                                     4 if fleet == 'single' else 1)
                    self.assertEqual(campaign.emotion.reduce.call_args_list.count(call(1, shipwreck=True)), 4)

    def test_coalition_full_flow_keeps_scuttle_confirm_and_result_context(self):
        for cls, fleet in product((CoalitionCombat, CoalitionScuttleRun), ('single', 'multi')):
            with self.subTest(cls=cls.__name__, fleet=fleet):
                confirm = SCUTTLE_CONFIRM if cls is CoalitionScuttleRun else COALITION_REWARD_CONFIRM
                replay = ScreenReplay([
                    screen('COMBAT'), screen(OPTS_INFO_D), screen(confirm), screen('COMBAT'),
                    screen(EXP_INFO_A), screen(COALITION_REWARD_CONFIRM), screen('COALITION')])
                campaign = replay.make_campaign(cls)
                campaign.config.Coalition_Fleet = fleet
                campaign.FUNCTION_NAME_BASE = 'battle_'
                campaign.combat_preparation = Mock()
                campaign.is_combat_loading = Mock(return_value=False)
                campaign.in_coalition = Mock(side_effect=lambda: 'COALITION' in replay.device.image)
                with patch('module.base.timer.time', side_effect=lambda: replay.time):
                    campaign.coalition_combat()
                calls = campaign.emotion.reduce.call_args_list
                self.assertEqual(calls.count(call(1)), 2 if cls is CoalitionCombat and fleet == 'single' else 1)
                self.assertEqual(calls.count(call(1, shipwreck=True)), 2 if cls is CoalitionCombat else 0)
                if cls is CoalitionScuttleRun:
                    self.assertEqual(calls, [call(1), call(2)])
                    self.assertEqual(campaign.config.CoalitionScuttle_Fleet2Affection, 0.0625)
                self.assertIn(confirm.name, replay.clicks)
                self.assertFalse(campaign._withdraw)
                self.assertEqual(campaign.combat_result.rank, 'A')

    # Add by MHY, 回放本地三队连战，重复评价/经验页不能多扣心情或重复加好感。
    def test_affection_coalition_keeps_two_beneficiaries_and_untracked_sacrifice(self):
        replay = ScreenReplay([
            screen('COMBAT'), screen(BATTLE_STATUS_S), screen(EXP_INFO_S),
            screen(COALITION_REWARD_CONFIRM), screen('COMBAT'),
            screen(BATTLE_STATUS_A), screen(EXP_INFO_A), screen(COALITION_REWARD_CONFIRM),
            screen('COMBAT'), screen(BATTLE_STATUS_D), screen(OPTS_INFO_D),
            screen(EXP_INFO_D), screen(SCUTTLE_CONFIRM), screen('COALITION')])
        campaign = replay.make_campaign(CoalitionScuttleRun)
        campaign.FUNCTION_NAME_BASE = 'battle_'
        campaign.combat_preparation = Mock()
        campaign.in_coalition = Mock(side_effect=lambda: 'COALITION' in replay.device.image)
        with patch('module.base.timer.time', side_effect=lambda: replay.time):
            campaign.coalition_combat()
        self.assertEqual(campaign.emotion.reduce.call_args_list, [call(1), call(2)])
        self.assertEqual(campaign.config.CoalitionScuttle_Fleet1Affection, 0.0625)
        self.assertEqual(campaign.config.CoalitionScuttle_Fleet2Affection, 0.0625)
        self.assertEqual(campaign.combat_result.fleet_index, 3)
        self.assertTrue(campaign.combat_result.defeated)
        self.assertFalse(campaign.combat_result.shipwreck_reduced)
        self.assertFalse(campaign._withdraw)
        self.assertIn(SCUTTLE_CONFIRM.name, replay.clicks)
        self.assertTrue(campaign._is_sacrifice_fleet)
        self.assertFalse(campaign.handle_combat_weapon_release())

    # Add by MHY, 连战无视模式保留好感计数，但不访问需要校准的恢复状态。
    def test_affection_coalition_ignored_emotion_still_counts_success_once(self):
        replay = ScreenReplay([screen('COMBAT'), screen(EXP_INFO_S)])
        campaign = replay.make_campaign(CoalitionScuttleRun)
        campaign.emotion.is_calculate = False
        with patch('module.base.timer.time', side_effect=lambda: replay.time):
            campaign.auto_search_combat_execute(emotion_reduce=False, fleet_index=2)
            campaign.combat_result_record(rank='S')
        campaign.emotion.reduce.assert_not_called()
        self.assertEqual(campaign.config.CoalitionScuttle_Fleet2Affection, 0.0625)

    # Add by MHY, 共斗双线使用恢复下限选线，并保留低心情时跳过与恢复时间计算。
    def test_raid_affection_lines_use_real_recovery_range_and_shared_ledger(self):
        for public in (False, True):
            with self.subTest(public=public):
                spec = ShipSpec('dormitory_floor_2', True)
                clock = Clock(500_000, LuaOracle(spec, 43, 500_000, 0))
                ledger = MemoryConfig(clock, spec, 43, 2, 'prevent_red_face', public)
                ledger.PublicEmotion_Tasks = 'Main, Event, RaidAffection'
                ledger.task.command = 'RaidAffection'
                ledger.RaidAffection_Fleet2VanguardAffection = 0.0
                replay = ScreenReplay([screen()])
                campaign = replay.make_campaign(RaidAffectionRun)
                campaign.config = ledger
                with patch.object(emotion_source, 'current_time', clock.now), \
                        patch('module.raid.affection.current_time', clock.now), \
                        patch.object(emotion_source, 'logger', QuietLogger()):
                    campaign.emotion = emotion_source.Emotion(ledger)
                    self.assertTrue(campaign._line_emotion_ready(2))
                    campaign.emotion.reduce(2)
                    campaign._affection_add(2, 'vanguard')
                    self.assertEqual(ledger.RaidAffection_Fleet2VanguardAffection, 0.0625)
                    self.assertFalse(campaign._line_emotion_ready(2))
                    self.assertGreater(campaign._line_recovered(2), clock.now())

    # Add by MHY, 油耗复核只接收正向成功信号，下一场必须清空旧标记。
    def test_raid_normal_result_marker_survives_result_pages_and_resets_next_battle(self):
        replay = ScreenReplay([screen(EXP_INFO_A), screen(EXP_INFO_A), screen(OPTS_INFO_D)])
        campaign = replay.make_campaign(RaidScuttleRun)
        campaign.combat_result_reset(emotion_reduce=True)
        with patch('module.base.timer.time', side_effect=lambda: replay.time):
            campaign.handle_exp_info()
            replay.screenshot()
            campaign.handle_exp_info()
            self.assertTrue(campaign.triggered_normal_end)
            replay.screenshot()
            campaign.handle_combat_defeat()
        self.assertFalse(campaign.triggered_normal_end)
        campaign.combat_result_reset(emotion_reduce=True)
        campaign.combat_result_record(rank='S')
        self.assertTrue(campaign.triggered_normal_end)
        campaign.combat_result_reset(emotion_reduce=True)
        self.assertFalse(campaign.triggered_normal_end)
        campaign.emotion.reduce.assert_not_called()
        replay.load([screen(BATTLE_STATUS_CF)])
        with patch('module.base.timer.time', side_effect=lambda: replay.time):
            self.assertTrue(campaign.handle_battle_status())
        self.assertTrue(campaign.triggered_normal_end)
        self.assertIsNone(campaign.combat_result.rank)

    def test_real_emotion_ledger_obeys_modes_shared_fleet_books_and_sinking_ignore(self):
        for mode, public, book, ignore, rank in product(
                ('calculate', 'ignore', 'calculate_ignore'), (False, True), (False, True),
                (False, True), ('S', 'A', 'B', 'defeat')):
            with self.subTest(mode=mode, public=public, book=book, ignore=ignore, rank=rank):
                spec = ShipSpec('dormitory_floor_2', True)
                clock = Clock(500_000, LuaOracle(spec, 150, 500_000, 0))
                ledger = MemoryConfig(clock, spec, 150, 4 if book else 2, 'prevent_red_face', public)
                # Add by MHY, 内存夹具补齐本地主线好感配置，避免把夹具缺字段当作生产失败。
                ledger.MainAffection_AffectionLimit = 0
                ledger.MainAffection_Fleet1Affection = 0.0
                ledger.MainAffection_Fleet2Affection = 0.0
                ledger.Emotion_Mode = mode
                ledger.Emotion_IgnoreShipwreck = ignore
                if public:
                    # Add by MHY, 独立二队未校准也不能影响已启用的共享好感账本。
                    ledger.Emotion_Fleet2Value = 0
                replay = ScreenReplay([screen()])
                campaign = replay.make_campaign(RaidCombat)
                with patch.object(emotion_source, 'current_time', clock.now), \
                        patch.object(emotion_source, 'logger', QuietLogger()):
                    campaign.emotion = emotion_source.Emotion(ledger)
                    campaign.emotion.map_is_2x_book = book
                    campaign.combat_result_reset(emotion_reduce=campaign.emotion.is_calculate, fleet_index=2)
                    campaign.emotion.reduce(2)
                    self.assertEqual(ledger.MainAffection_Fleet2Affection, 0.0)
                    for _ in range(3):
                        campaign.combat_result_record(rank=None if rank == 'defeat' else rank,
                                                      defeated=rank == 'defeat')
                    self.assertEqual(ledger.MainAffection_Fleet2Affection,
                                     0.0625 if mode != 'ignore' and rank != 'defeat' else 0.0)
                    fleet = campaign.emotion.public_fleet if public else campaign.emotion.fleet_2
                    if mode == 'ignore':
                        # 无视模式不创建恢复相位，也不应为了断言强制要求校准。
                        self.assertEqual(fleet.value, 150)
                        self.assertFalse(campaign.combat_result.shipwreck_reduced)
                        continue
                    cost = (4 if book else 2) + (10 if rank != 'S' and not ignore else 0)
                    expected = 150 - cost
                    self.assertEqual((fleet.lower, fleet.upper, fleet.value), (expected,) * 3)


if __name__ == '__main__':
    unittest.main()
