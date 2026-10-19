"""META 求援次数、最后一轮等待、断点恢复和信标切换的离线回归。"""

import copy
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.config.config import AzurLaneConfig, TaskEnd
from module.config.config_updater import ConfigUpdater
from module.os_ash.assets import ASH_SHOWDOWN, BEACON_LIST, DOSSIER_LIST
from module.os_ash.meta import MetaState, OpsiAshBeacon


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
        with self.assertRaises(TaskEnd):
            runner._attack_meta()

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


if __name__ == '__main__':
    unittest.main()
