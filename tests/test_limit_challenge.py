"""限界挑战截图识别、月度进度与持久化回归，不连接模拟器。"""

import json
import tempfile
import time
import unittest
from contextlib import contextmanager, nullcontext
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

import module.limit_challenge.limit_challenge as source
from module.api.config_service import ConfigService
from module.api.protocol import ApiError, ConfigChange
from module.base.utils import load_image
from module.base.base import ModuleBase
from module.combat.assets import (
    BATTLE_STATUS_S, BATTLE_STATUS_A, BATTLE_STATUS_B, EXP_INFO_C, EXP_INFO_D, GET_ITEMS_1, OPTS_INFO_D,
)
from module.combat.result import CombatResult
from module.config.config import AzurLaneConfig, TaskEnd
from module.config.config_updater import ConfigUpdater
from module.exception import GameStuckError, RequestHumanTakeover
from module.limit_challenge.assets import CHALLENGE_PREPARATION, CHALLENGE_START, TEMPLATE_LEVEL_LOCKED
from module.limit_challenge.limit_challenge import LEVELS, LimitChallenge, challenge_month
from module.ui.assets import CAMPAIGN_MENU_GOTO_LIMIT_CHALLENGE, LIMIT_CHALLENGE_CHECK
from module.ui.page import Page, page_campaign_menu, page_limit_challenge, page_limit_challenge_preparation
from tests.test_api import fixture
from tests.test_auto_search_defeat import ScreenReplay, screen


FIXTURES = Path(__file__).parent / 'fixtures' / 'limit_challenge'


@contextmanager
def temporary_config_directory():
    """保留真实事务读写，仅对 Windows 临时目录清理的短暂非空重试。"""
    directory = tempfile.TemporaryDirectory()
    try:
        yield directory.name
    finally:
        # 与已有配置事务测试一致：刚释放的锁文件可能延迟完成删除。
        for attempt in range(3):
            try:
                directory.cleanup()
                break
            except OSError as exc:
                if getattr(exc, 'winerror', None) != 145 or attempt == 2:
                    raise
                time.sleep(0.05)
        if Path(directory.name).exists():
            raise AssertionError('限界挑战测试临时配置未清理')


class OriginalFrameReplay(ScreenReplay):
    """原图使用真实识别，战斗符号帧沿用共用回放工具。"""

    def appear(self, button, **kwargs):
        if isinstance(self.device.image, np.ndarray):
            return ModuleBase.appear(self.campaign, button, **kwargs)
        return super().appear(button, **kwargs)


class ChallengeRecognitionTests(unittest.TestCase):
    def setUp(self):
        self.task = LimitChallenge.__new__(LimitChallenge)
        self.task.device = Mock()
        self.task.config = SimpleNamespace(BUTTON_OFFSET=(30, 30))
        self.task.interval_timer = {}
        self.images = {name: load_image(str(FIXTURES / f'{name}.png'))
                       for name in ('menu', 'easy', 'preparation', 'normal', 'hard', 'rewards')}

    def test_original_screens_identify_only_their_own_page(self):
        for name, image in self.images.items():
            with self.subTest(screen=name):
                self.task.device.image = image
                self.assertEqual(self.task.is_in_challenge(), name in ('easy', 'normal', 'hard'))
                self.assertEqual(self.task.is_in_challenge_preparation(), name == 'preparation')
                self.assertEqual(self.task.appear(CAMPAIGN_MENU_GOTO_LIMIT_CHALLENGE, offset=(3, 3)), name == 'menu')
                self.assertEqual(image.shape, (720, 1280, 3))

    def test_easy_selected_and_later_levels_locked_in_original_image(self):
        self.task.device.image = self.images['easy']
        self.assertEqual(self.task.selected_level(), 1)
        for index, row in enumerate(LEVELS, 1):
            self.assertEqual(TEMPLATE_LEVEL_LOCKED.match(self.task.image_crop(row.area)), index > 1)
        self.assertTrue(self.task.appear(CHALLENGE_START, offset=(3, 3)))

    def test_reward_overlay_does_not_end_combat_early(self):
        self.task.device.image = (self.images['easy'] * 0.4).astype(np.uint8)
        self.assertFalse(self.task.is_in_challenge())

    def test_normal_and_hard_selected_in_original_images(self):
        for name, level in (('normal', 2), ('hard', 3)):
            with self.subTest(level=name):
                self.task.device.image = self.images[name]
                self.assertEqual(self.task.selected_level(), level)
                self.assertTrue(self.task.appear(CHALLENGE_START, offset=(3, 3)))
                self.assertFalse(TEMPLATE_LEVEL_LOCKED.match(self.task.image_crop(LEVELS[level - 1].area)))

    def test_original_reward_popup_is_dismissed_before_starting(self):
        self.task.device.image = self.images['rewards']
        self.assertFalse(self.task.is_in_challenge())
        self.assertTrue(self.task.handle_challenge_rewards())
        self.task.device.click.assert_called_once_with(GET_ITEMS_1)

    def test_selection_marker_is_unique_and_position_based(self):
        # 只模拟共用菱形的行位置，不把合成帧当作审视/洞察真实截图。
        original = self.images['easy']
        marker = original[438:461, 30:52].copy()
        for selected in (None, 1, 2, 3):
            with self.subTest(selected=selected):
                frame = original.copy()
                frame[420:680, 27:54] = 0
                if selected is not None:
                    y = 438 + (selected - 1) * 100
                    frame[y:y + 23, 30:52] = marker
                self.task.device.image = frame
                self.assertEqual(self.task.selected_level(), selected)
        frame[438:461, 30:52] = marker
        self.assertIsNone(self.task.selected_level())

    def test_navigation_has_entrance_and_return_links(self):
        self.assertIs(page_campaign_menu.links[page_limit_challenge], CAMPAIGN_MENU_GOTO_LIMIT_CHALLENGE)
        self.assertIs(page_limit_challenge.check_button, LIMIT_CHALLENGE_CHECK)
        self.assertIn(page_campaign_menu, page_limit_challenge.links)
        self.assertIn(page_limit_challenge, page_limit_challenge_preparation.links)
        Page.init_connection(page_limit_challenge)
        self.addCleanup(Page.clear_connection)
        self.assertIs(page_limit_challenge_preparation.parent, page_limit_challenge)

    def test_locked_level_is_never_started(self):
        self.task.device.image = self.images['easy']
        self.task.loop = Mock(return_value=iter(range(4)))
        self.task.handle_challenge_rewards = Mock(return_value=False)
        with self.assertRaises(GameStuckError):
            self.task.enter_challenge_preparation(2)
        self.task.device.click.assert_not_called()

    def test_easy_entrance_waits_for_actual_preparation_screen(self):
        self.task.device.image = self.images['easy']
        def frames(**kwargs):
            yield self.task.device.image
            self.task.device.image = self.images['preparation']
            yield self.task.device.image
        self.task.loop = frames
        self.task.handle_challenge_rewards = Mock(return_value=False)
        self.task.enter_challenge_preparation(1)
        self.task.device.click.assert_called_once_with(CHALLENGE_START)

    def test_unrecognized_level_starts_current_unlocked_stage(self):
        for name, level in (('easy', 1), ('normal', 2), ('hard', 3)):
            with self.subTest(level=name):
                self.task.device.click.reset_mock()
                self.task.interval_timer = {}
                self.task.device.image = self.images[name]
                def frames(**kwargs):
                    yield self.task.device.image
                    self.task.device.image = self.images['preparation']
                    yield self.task.device.image
                self.task.loop = frames
                with patch.object(self.task, 'selected_level', return_value=None):
                    self.task.enter_challenge_preparation(level)
                self.task.device.click.assert_called_once_with(CHALLENGE_START)

    def test_unrecognized_level_does_not_start_a_known_locked_stage(self):
        self.task.device.image = self.images['easy']
        self.task.loop = Mock(return_value=iter(range(4)))
        self.task.handle_challenge_rewards = Mock(return_value=False)
        with patch.object(self.task, 'selected_level', return_value=None), self.assertRaises(GameStuckError):
            self.task.enter_challenge_preparation(2)
        self.task.device.click.assert_not_called()

    def test_auto_advance_starts_next_level_after_closing_reward_popup(self):
        for name, level in (('normal', 2), ('hard', 3)):
            with self.subTest(level=name):
                self.task.device.click.reset_mock()
                self.task.interval_timer = {}
                def frames(**kwargs):
                    for frame in ('rewards', name, 'preparation'):
                        self.task.device.image = self.images[frame]
                        yield self.task.device.image
                self.task.loop = frames
                self.task.enter_challenge_preparation(level)
                self.assertEqual([call.args[0].name for call in self.task.device.click.call_args_list],
                                 [GET_ITEMS_1.name, CHALLENGE_START.name])


class ChallengeProgressTests(unittest.TestCase):
    def setUp(self):
        self.directory = self.enterContext(temporary_config_directory())
        self.root = fixture(self.directory)
        self.path = self.root / 'config/testpilot.json'
        self.now = datetime(2026, 10, 12, 12)
        self.enterContext(patch.object(source.server, 'server', 'cn'))
        self.enterContext(patch.object(source, 'current_time', side_effect=lambda: self.now))
        self.enterContext(patch.object(source, 'server_time_offset', return_value=timedelta(0)))
        self.enterContext(patch('module.config.utils.server_time_offset', return_value=timedelta(0)))
        for name in ('module.config.config', 'module.config.config_updater', 'module.config.utils', 'module.config.watcher'):
            self.enterContext(patch(f'{name}.filepath_config', side_effect=lambda name, *args: str(self.root / f'config/{name}.json')))
        self.enterContext(patch('module.config.config.current_time', side_effect=lambda: self.now))
        for name in ('hr', 'info', 'warning', 'attr'):
            self.enterContext(patch.object(source.logger, name))
        self.config = AzurLaneConfig('testpilot', task='LimitChallenge')
        self.levels = []
        self.outcomes = ['S']
        self.make_task()

    def make_task(self):
        self.task = LimitChallenge.__new__(LimitChallenge)
        self.task.config = self.config
        self.task.device = Mock()
        self.task.interval_timer = {}
        self.task.ui_ensure = Mock()
        self.task.loop = lambda **kwargs: iter(range(4))
        self.task.handle_challenge_rewards = Mock(return_value=False)
        self.task.is_in_challenge = Mock(return_value=True)
        self.task.selected_level = Mock(return_value=1)
        self.task.is_in_challenge_preparation = Mock(return_value=True)
        self.task.enter_challenge_preparation = Mock()
        self.task.combat = Mock(side_effect=self.battle)
        self.task.get_interval_timer = Mock(return_value=Mock(reached=Mock(return_value=True)))
        self.task.interval_reset = Mock()

    def battle(self, **kwargs):
        level = self.task._challenge_level
        self.assertFalse(kwargs['emotion_reduce'])
        self.assertFalse(kwargs['balance_hp'])
        self.assertEqual(kwargs['auto_mode'], 'combat_auto')
        self.assertTrue(self.task.handle_battle_preparation())
        # 已点击出击时必须已有独立磁盘记录；不能用内存字段代替保存成功。
        persisted = self.disk()['LimitChallenge']['LimitChallenge']
        self.assertEqual(persisted['AttemptedLevel'], level)
        self.levels.append(level)
        rank = self.outcomes.pop(0)
        if isinstance(rank, BaseException):
            raise rank
        self.task.combat_result = CombatResult(rank=rank, defeated=rank in ('C', 'D'))

    def disk(self):
        return json.loads(self.path.read_text(encoding='utf-8'))

    def reload(self):
        self.config = AzurLaneConfig('testpilot', task='LimitChallenge')
        self.make_task()

    def test_each_target_runs_only_its_required_levels(self):
        for target, count in (('easy', 1), ('normal', 2), ('hard', 3)):
            with self.subTest(target=target):
                self.config.LimitChallenge_Month = 0
                self.config.LimitChallenge_TargetLevel = target
                self.outcomes = ['S', 'A', 'B'][:count]
                self.levels.clear()
                self.task.run()
                self.assertEqual(self.levels, list(range(1, count + 1)))
                self.assertEqual(self.disk()['LimitChallenge']['LimitChallenge']['CompletedLevel'], count)
                self.assertNotIn('emotion', self.task.__dict__)

    def test_c_and_d_stop_remaining_levels_and_survive_reload(self):
        for grade in ('C', 'D'):
            with self.subTest(grade=grade):
                self.config.LimitChallenge_Month = 0
                self.config.LimitChallenge_TargetLevel = 'hard'
                self.outcomes = ['A', grade]
                self.levels.clear()
                self.task.run()
                self.assertEqual(self.levels, [1, 2])
                self.assertTrue(self.disk()['LimitChallenge']['LimitChallenge']['Failed'])
                self.reload()
                self.task.run()
                self.task.combat.assert_not_called()
                self.task.ui_ensure.assert_not_called()

    def test_success_survives_restart_without_repeating(self):
        self.task.run()
        self.reload()
        self.task.run()
        self.task.combat.assert_not_called()
        self.assertEqual(self.levels, [1])

    def test_raising_target_continues_after_previous_clear(self):
        self.task.run()
        self.reload()
        self.config.LimitChallenge_TargetLevel = 'hard'
        self.outcomes = ['A', 'B']
        self.task.run()
        self.assertEqual(self.levels, [1, 2, 3])

    def test_defeat_flag_takes_precedence_over_positive_grade(self):
        def battle(**kwargs):
            self.task.handle_battle_preparation()
            self.task.combat_result = CombatResult(rank='A', defeated=True)
        self.task.combat.side_effect = battle
        self.task.run()
        self.assertTrue(self.config.LimitChallenge_Failed)
        self.assertEqual(self.config.LimitChallenge_CompletedLevel, 0)

    def test_unconfirmed_grade_is_not_a_win_and_is_not_retried(self):
        self.outcomes = [None]
        self.task.run()
        self.assertEqual(self.config.LimitChallenge_CompletedLevel, 0)
        self.reload()
        self.task.run()
        self.task.combat.assert_not_called()

    def test_interruption_after_launch_does_not_repeat_the_attempt(self):
        self.outcomes = [GameStuckError('模拟中断')]
        with self.assertRaises(GameStuckError):
            self.task.run()
        self.reload()
        self.task.run()
        self.task.combat.assert_not_called()
        self.assertEqual(self.levels, [1])

    def test_unlocked_higher_level_confirms_previous_monthly_clear(self):
        self.config.LimitChallenge_TargetLevel = 'hard'
        self.task.selected_level.return_value = 3
        self.outcomes = ['B']
        self.task.run()
        self.assertEqual(self.levels, [3])

    def test_unrecognized_level_uses_success_count_until_target(self):
        for target, count in (('normal', 2), ('hard', 3)):
            with self.subTest(target=target):
                self.config.LimitChallenge_Month = 0
                self.config.LimitChallenge_TargetLevel = target
                self.task.selected_level.return_value = None
                self.levels.clear()
                self.outcomes = ['S', 'A', 'B'][:count]
                self.task.run()
                self.assertEqual(self.levels, list(range(1, count + 1)))
                self.assertEqual(self.config.LimitChallenge_CompletedLevel, count)
                self.reload()
                self.task.run()
                self.task.combat.assert_not_called()

    def test_next_month_resets_success_and_defeat(self):
        self.outcomes = ['D']
        self.task.run()
        self.now = datetime(2026, 11, 1, 0, 0, 1)
        self.reload()
        self.outcomes = ['A']
        self.task.run()
        self.assertEqual(self.levels, [1, 1])
        self.assertEqual(self.config.LimitChallenge_Month, 202611)
        self.assertFalse(self.config.LimitChallenge_Failed)

    def test_month_boundary_before_launch_never_clicks(self):
        def enter(level):
            self.now = datetime(2026, 11, 1)
        self.task.enter_challenge_preparation.side_effect = enter
        with self.assertRaises(TaskEnd):
            self.task.run()
        self.task.device.click.assert_not_called()
        self.assertEqual(self.config.LimitChallenge_AttemptedLevel, 0)

    def test_month_boundary_during_battle_does_not_carry_clear_to_new_month(self):
        original_battle = self.battle
        def battle(**kwargs):
            original_battle(**kwargs)
            self.now = datetime(2026, 11, 1)
        self.task.combat.side_effect = battle
        self.task.run()
        self.assertEqual(self.config.LimitChallenge_CompletedLevel, 0)
        self.assertEqual(self.config.Scheduler_NextRun, self.now)

    def test_failure_to_persist_prevents_clicking(self):
        self.config.LimitChallenge_Month = 202610
        self.task._challenge_level = 1
        self.task._attempt_recorded = False
        with patch.object(self.config, 'write_file', side_effect=OSError('模拟磁盘写入失败')):
            with self.assertRaises(OSError):
                self.task.handle_battle_preparation()
        self.task.device.click.assert_not_called()

    def test_repeated_preparation_frames_record_only_one_attempt(self):
        self.config.LimitChallenge_Month = 202610
        self.task._challenge_level = 1
        self.task._attempt_recorded = False
        with patch.object(self.config, 'write_file', wraps=self.config.write_file) as write:
            self.task.handle_battle_preparation()
            self.task.handle_battle_preparation()
        self.assertEqual(write.call_count, 1)
        self.assertEqual(self.config.LimitChallenge_AttemptedLevel, 1)

    def test_invalid_target_and_unsupported_server_stop_before_navigation(self):
        self.config.LimitChallenge_TargetLevel = 'unknown'
        with self.assertRaises(RequestHumanTakeover):
            self.task.run()
        self.config.LimitChallenge_TargetLevel = 'easy'
        with patch.object(source.server, 'server', 'en'), self.assertRaises(RequestHumanTakeover):
            self.task.run()
        self.task.ui_ensure.assert_not_called()

    def test_schedule_is_first_day_of_next_month_in_server_timezone(self):
        for now, expected in (
            (datetime(2026, 10, 12, 12), datetime(2026, 11, 1)),
            (datetime(2026, 12, 31, 23), datetime(2027, 1, 1)),
            (datetime(2028, 2, 29, 23), datetime(2028, 3, 1)),
        ):
            with self.subTest(now=now):
                self.now = now
                self.task.delay_next_month()
                local_expected = expected.replace(tzinfo=timezone(timedelta(hours=8))).astimezone().replace(tzinfo=None)
                self.assertEqual(self.config.Scheduler_NextRun, local_expected)

    def test_month_uses_server_date_even_when_local_date_is_different(self):
        self.now = datetime(2026, 10, 31, 17)
        with patch.object(source, 'server_time_offset', return_value=timedelta(hours=-8)):
            self.assertEqual(challenge_month(), 202611)


class ChallengeCombatLifecycleTests(unittest.TestCase):
    def test_real_combat_lifecycle_uses_custom_launch_and_never_consumes_emotion(self):
        preparation = load_image(str(FIXTURES / 'preparation.png'))
        end = load_image(str(FIXTURES / 'easy.png'))
        for rank, result_frames in (
            ('S', [screen(BATTLE_STATUS_S)]), ('A', [screen(BATTLE_STATUS_A)]),
            ('B', [screen(BATTLE_STATUS_B)]),
            ('C', [screen(OPTS_INFO_D), screen(EXP_INFO_C)]),
            ('D', [screen(OPTS_INFO_D), screen(EXP_INFO_D)]),
        ):
            with self.subTest(rank=rank):
                replay = OriginalFrameReplay([preparation, screen('LOADING'), screen('COMBAT'), *result_frames, end])
                task = replay.make_campaign(LimitChallenge)
                task.config.LimitChallenge_Month = 202610
                task.config.LimitChallenge_AttemptedLevel = 0
                task.config.campaign_name = 'limit_challenge'
                task.config.DropRecord_CombatRecord = 'do_not'
                task.config.multi_set = lambda: nullcontext()
                task.config.task_delay = Mock()
                task._challenge_level = 1
                task._attempt_recorded = False
                task.stat = Mock()
                task.stat.new.return_value = nullcontext()
                task.handle_in_stage = Mock(return_value=False)
                task.handle_urgent_commission = Mock(return_value=False)
                task.is_combat_executing.side_effect = lambda: (
                    isinstance(task.device.image, frozenset) and 'COMBAT' in task.device.image)
                task.is_combat_loading.side_effect = lambda: (
                    isinstance(task.device.image, frozenset) and 'LOADING' in task.device.image)
                task.is_in_challenge = lambda: (
                    isinstance(task.device.image, np.ndarray) and LimitChallenge.is_in_challenge(task))
                task.is_in_challenge_preparation = lambda: (
                    isinstance(task.device.image, np.ndarray) and LimitChallenge.is_in_challenge_preparation(task))
                with patch('module.base.timer.time', side_effect=lambda: replay.time), \
                        patch.object(source, 'challenge_month', return_value=202610), \
                        patch.object(source, 'current_time', return_value=datetime(2026, 10, 12, 12)):
                    task.combat(balance_hp=False, emotion_reduce=False, auto_mode='combat_auto',
                                submarine_mode='every_combat', save_get_items=False,
                                expected_end=task.is_in_challenge)
                self.assertEqual(task.combat_result.rank, rank if rank in ('S', 'A', 'B') else None)
                self.assertEqual(task.combat_result.defeated, rank in ('C', 'D'))
                self.assertIn(CHALLENGE_PREPARATION.name, replay.clicks)
                self.assertEqual(task.config.LimitChallenge_AttemptedLevel, 1)
                task.emotion.wait.assert_not_called()
                task.emotion.reduce.assert_not_called()
                task.emotion.record.assert_not_called()

    def test_combat_status_dismisses_original_reward_before_auto_advanced_page(self):
        rewards = load_image(str(FIXTURES / 'rewards.png'))
        for name, level in (('normal', 2), ('hard', 3)):
            with self.subTest(level=name):
                end = load_image(str(FIXTURES / f'{name}.png'))
                replay = OriginalFrameReplay([screen(BATTLE_STATUS_S), rewards, end])
                task = replay.make_campaign(LimitChallenge)
                task.handle_get_items = LimitChallenge.handle_get_items.__get__(task)
                task.handle_in_stage = Mock(return_value=False)
                task.is_in_challenge = lambda: (
                    isinstance(task.device.image, np.ndarray) and LimitChallenge.is_in_challenge(task))
                task.combat_result_reset(emotion_reduce=False)
                with patch('module.base.timer.time', side_effect=lambda: replay.time):
                    task.combat_status(expected_end=task.is_in_challenge)
                self.assertEqual(replay.clicks, [BATTLE_STATUS_S.name, GET_ITEMS_1.name])
                self.assertEqual(replay.index, 2)
                self.assertEqual(task.selected_level(), level)
                self.assertEqual(task.combat_result.rank, 'S')
                task.emotion.reduce.assert_not_called()


class ChallengeConfigurationTests(unittest.TestCase):
    def test_menu_defaults_translations_and_legacy_migration(self):
        template = json.loads(Path('config/template.json').read_text(encoding='utf-8'))
        group = template['LimitChallenge']
        self.assertFalse(group['Scheduler']['Enable'])
        self.assertEqual(group['LimitChallenge']['TargetLevel'], 'easy')
        menu = json.loads(Path('module/config/argument/menu.json').read_text(encoding='utf-8'))
        self.assertIn('LimitChallenge', menu['DailyMission']['tasks'])
        template.pop('LimitChallenge')
        migrated = ConfigUpdater().config_update(template)
        self.assertEqual(migrated['LimitChallenge']['LimitChallenge']['AttemptedLevel'], 0)
        # Modify by MHY, 本分支仅保留四种正式语言。
        for language in ('zh-CN', 'zh-TW', 'en-US', 'ja-JP'):
            text = json.loads(Path(f'module/config/i18n/{language}.json').read_text(encoding='utf-8'))
            self.assertNotIn('Task.LimitChallenge', text['Task']['LimitChallenge']['name'])
            self.assertNotIn('LimitChallenge.', json.dumps(text['LimitChallenge']))
            for value in ('easy', 'normal', 'hard'):
                self.assertNotEqual(text['LimitChallenge']['TargetLevel'][value], value)

    def test_target_options_roundtrip_through_real_api(self):
        with temporary_config_directory() as directory:
            service = ConfigService(fixture(directory))
            path = 'LimitChallenge.LimitChallenge.TargetLevel'
            for target in ('easy', 'normal', 'hard'):
                result = service.patch('testpilot', None, [ConfigChange(path=path, value=target)])
                self.assertEqual(result['values']['LimitChallenge']['LimitChallenge']['TargetLevel'], target)
            with self.assertRaises(ApiError):
                service.validate(path, 'unknown')


if __name__ == '__main__':
    unittest.main()
