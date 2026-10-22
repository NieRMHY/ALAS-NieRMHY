"""心情相位计算、出击保护、校准和真实存档的定向回归。"""

import copy
import json
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from dev_tools.emotion_simulate import Clock, LuaOracle, MemoryConfig, QuietLogger, ShipSpec, simulate
import module.combat.emotion as production
import module.config.config as config_source
from module.combat.emotion_state import EmotionRecoveryState, PERIOD_US
from module.config.config import AzurLaneConfig, Function
from module.config.utils import read_file, write_file
from module.exception import CampaignEnd, RequestHumanTakeover, ScriptEnd
from module.handler.info_handler import InfoHandler


class RecoveryStateTests(unittest.TestCase):
    def test_tick_boundaries_and_partitioned_time_match(self):
        start = datetime(2026, 10, 9, microsecond=500_000)
        whole = EmotionRecoveryState.calibrate(70, start, 'dormitory_floor_2', True, False)
        split = copy.deepcopy(whole)
        for delta in (1, 17, 359_999_999, 360_000_000, 360_000_001, 5 * PERIOD_US + 113):
            split.advance(start + timedelta(microseconds=delta))
        whole.advance(split.record)
        self.assertEqual(whole.export(), split.export())
        self.assertEqual((100, 106), (whole.lower, whole.upper))

    def test_cap_and_zero_clamping_do_not_accumulate_uncertainty(self):
        state = EmotionRecoveryState.calibrate(119, datetime(2026, 10, 9), 'not_in_dormitory', False, False)
        state.advance(state.record + timedelta(hours=6))
        self.assertEqual((119, 119), (state.lower, state.upper))
        state.consume(120)
        self.assertEqual([(0, PERIOD_US, 0)], state.segments)
        self.assertEqual(0, state.value)

    def test_port_preserves_existing_emotion_above_119(self):
        state = EmotionRecoveryState.calibrate(150, datetime(2026, 10, 9), 'not_in_dormitory', True, False)
        state.advance(state.record + timedelta(days=30))
        self.assertEqual(150, state.value)
        state.consume(34)
        state.advance(state.record + timedelta(minutes=6))
        self.assertEqual(119, state.value)

    def test_onsen_cap_and_error_bound_are_explicit(self):
        state = EmotionRecoveryState.calibrate(119, datetime(2026, 10, 9), 'not_in_dormitory', False, True)
        state.advance(state.record + timedelta(days=1))
        self.assertEqual(150, state.value)
        state = EmotionRecoveryState.calibrate(80, state.record, 'dormitory_floor_2', True, True)
        state.advance(state.record + timedelta(seconds=60))
        self.assertEqual(7, state.upper - state.lower)
        self.assertEqual(4, state.upper - state.value)

    def test_bad_state_and_clock_rollback_are_rejected(self):
        state = EmotionRecoveryState.calibrate(80, datetime(2026, 10, 9), 'dormitory_floor_2', True, False)
        valid = state.export()
        for field, value in [('version', True), ('record', 'invalid'), ('signature', ['dormitory_floor_1', True, False]),
                             ('segments', [[PERIOD_US, PERIOD_US, 80]]), ('segments', [[0, PERIOD_US, 81]]),
                             ('segments', [[0, PERIOD_US, True]])]:
            bad = {**valid, field: value}
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                EmotionRecoveryState.restore(bad, 80, state.record, state.recover, state.oath, state.onsen)
        with self.assertRaises(ValueError):
            state.advance(state.record - timedelta(microseconds=1))

    def test_wait_target_is_conservative_and_ceil_to_second(self):
        state = EmotionRecoveryState.calibrate(40, datetime(2026, 10, 9, microsecond=500_000),
                                               'dormitory_floor_2', True, False)
        state.advance(state.record + timedelta(seconds=60))
        self.assertEqual((40, 46, 43), (state.lower, state.upper, state.value))
        target = state.recovered_at(42)
        self.assertEqual(datetime(2026, 10, 9, 0, 6, 1), target)
        state.advance(target)
        self.assertGreaterEqual(state.lower, 42)


class EmotionIntegrationTests(unittest.TestCase):
    def setup_tracker(self, initial=70, public=False):
        spec = ShipSpec('dormitory_floor_2', True)
        oracle = LuaOracle(spec, initial, 500_000, 0)
        clock = Clock(500_000, oracle)
        config = MemoryConfig(clock, spec, initial, 2, 'prevent_green_face', public)
        self.enterContext(patch.object(production, 'current_time', clock.now))
        self.enterContext(patch.object(config_source, 'current_time', clock.now))
        self.enterContext(patch.object(production, 'logger', QuietLogger()))
        self.enterContext(patch.object(config_source, 'logger', QuietLogger()))
        return clock, config, production.Emotion(config)

    def test_reserve_allows_continuous_maps_down_to_control_line(self):
        clock, config, emotion = self.setup_tracker(initial=150)
        config.Emotion_MinReserve = 150
        config.Emotion_Fleet1Control = 'prevent_yellow_face'
        for _ in range(10):
            emotion.check_reduce(6)
            for _ in range(6):
                emotion.reduce(1)
        self.assertEqual(30, config.Emotion_Fleet1Value)
        self.assertIsNone(getattr(config, 'Emotion_RecoveryWait', None))
        with self.assertRaises(ScriptEnd):
            emotion.check_reduce(6)
        self.assertEqual(['1'], config.Emotion_RecoveryWait)
        self.assertEqual(clock.now().replace(microsecond=0) + timedelta(hours=2, seconds=1),
                         config.fields['Main.Scheduler.NextRun'])

    def test_zero_reserve_preserves_existing_short_delay(self):
        clock, config, emotion = self.setup_tracker(initial=30)
        config.Emotion_MinReserve = 0
        config.Emotion_Fleet1Control = 'prevent_yellow_face'
        with self.assertRaises(ScriptEnd):
            emotion.check_reduce(6)
        self.assertEqual(clock.now().replace(microsecond=0) + timedelta(minutes=12, seconds=1),
                         config.fields['Main.Scheduler.NextRun'])
        self.assertIsNone(getattr(config, 'Emotion_RecoveryWait', None))

    def test_reserve_survives_reload_and_releases_after_recovery(self):
        for public in (False, True):
            with self.subTest(public=public):
                clock, config, emotion = self.setup_tracker(initial=30, public=public)
                config.Emotion_MinReserve = 150
                prefix = 'PublicEmotion_Fleet' if public else 'Emotion_Fleet1'
                setattr(config, prefix + 'Control', 'prevent_yellow_face')
                with self.assertRaises(ScriptEnd):
                    emotion.check_reduce(6)
                target = config.fields['Main.Scheduler.NextRun']
                # 已够打一张图，但没有恢复到预留值，重建任务对象后也不能提前续刷。
                clock.advance(12 * 60_000_000)
                with self.assertRaises(ScriptEnd):
                    production.Emotion(config).check_reduce(6)
                self.assertEqual(target, config.fields['Main.Scheduler.NextRun'])
                clock.advance((target - clock.now()) // timedelta(microseconds=1))
                reloaded = production.Emotion(config)
                reloaded.check_reduce(6)
                self.assertIsNone(config.Emotion_RecoveryWait)
                fleet = reloaded.public_fleet if public else reloaded.fleet_1
                self.assertEqual(150, fleet.lower)
                reloaded.reduce(1)
                production.Emotion(config).check_reduce(6)
                self.assertEqual(148, getattr(config, prefix + 'Value'))
                self.assertIsNone(config.Emotion_RecoveryWait)

    def test_reserve_uses_participating_fleets_for_each_order(self):
        for order, waiting in (
                ('fleet1_all_fleet2_standby', ['1']),
                ('fleet1_standby_fleet2_all', ['2']),
                ('fleet1_mob_fleet2_boss', ['1', '2']),
                ('fleet1_boss_fleet2_mob', ['1', '2'])):
            with self.subTest(order=order):
                _, config, emotion = self.setup_tracker(initial=30)
                config.Emotion_MinReserve = 150
                config.Fleet_FleetOrder = order
                config.Emotion_Fleet1Control = config.Emotion_Fleet2Control = 'prevent_yellow_face'
                with self.assertRaises(ScriptEnd):
                    emotion.check_reduce(6)
                self.assertEqual(waiting, config.Emotion_RecoveryWait)

    def test_reserve_wait_only_marks_the_insufficient_fleet(self):
        clock, config, emotion = self.setup_tracker(initial=70)
        config.Emotion_MinReserve = 150
        config.Fleet_FleetOrder = 'fleet1_mob_fleet2_boss'
        config.Emotion_Fleet2Value = 40
        config.Emotion_Fleet2RecoveryState = EmotionRecoveryState.calibrate(
            40, clock.now(), 'dormitory_floor_2', True, False).export()
        with self.assertRaises(ScriptEnd):
            emotion.check_reduce(6)
        self.assertEqual(['2'], config.Emotion_RecoveryWait)
        self.assertEqual(70, config.Emotion_Fleet1Value)

    def test_reserve_handoff_precheck_uses_actual_successor(self):
        clock, config, emotion = self.setup_tracker(initial=40)
        config.Emotion_MinReserve = 150
        with self.assertRaises(ScriptEnd):
            emotion.check_fleet(2)
        self.assertEqual(['2'], config.Emotion_RecoveryWait)
        self.assertEqual((40, 40), (config.Emotion_Fleet1Value, config.Emotion_Fleet2Value))
        self.assertEqual(clock.now().replace(microsecond=0) + timedelta(minutes=114, seconds=1),
                         config.fields['Main.Scheduler.NextRun'])

    def test_reserve_cannot_lower_full_sortie_requirement(self):
        clock, config, emotion = self.setup_tracker(initial=40)
        config.Emotion_MinReserve = 41
        with self.assertRaises(ScriptEnd):
            emotion.check_reduce(6)
        self.assertEqual(clock.now().replace(microsecond=0) + timedelta(minutes=12, seconds=1),
                         config.fields['Main.Scheduler.NextRun'])

    def test_reserve_caps_port_recovery_without_infinite_delay(self):
        clock, config, emotion = self.setup_tracker(initial=30)
        config.Emotion_MinReserve = 150
        config.Emotion_Fleet1Control = 'prevent_yellow_face'
        config.Emotion_Fleet1Recover = 'not_in_dormitory'
        config.Emotion_Fleet1Oath = False
        config.Emotion_Fleet1RecoveryState = EmotionRecoveryState.calibrate(
            30, clock.now(), 'not_in_dormitory', False, False).export()
        with self.assertRaises(ScriptEnd):
            emotion.check_reduce(6)
        target = config.fields['Main.Scheduler.NextRun']
        self.assertEqual(clock.now().replace(microsecond=0) + timedelta(minutes=270, seconds=1), target)
        clock.advance((target - clock.now()) // timedelta(microseconds=1))
        production.Emotion(config).check_reduce(6)
        self.assertEqual(119, config.Emotion_Fleet1Value)
        self.assertIsNone(config.Emotion_RecoveryWait)

    def test_reserve_supports_double_book_oversized_map(self):
        clock, config, emotion = self.setup_tracker(initial=120)
        config.Emotion_MinReserve = 150
        config.Emotion_Fleet1Control = 'keep_exp_bonus'
        config.Campaign_Use2xBook = True
        with self.assertRaises(ScriptEnd):
            emotion.check_reduce(8)
        target = config.fields['Main.Scheduler.NextRun']
        self.assertEqual(clock.now().replace(microsecond=0) + timedelta(minutes=30, seconds=1), target)
        clock.advance((target - clock.now()) // timedelta(microseconds=1))
        production.Emotion(config).check_reduce(8)
        self.assertEqual(150, config.Emotion_Fleet1Value)

    def test_reserve_can_be_disabled_or_lowered_while_waiting(self):
        for new_reserve in (0, 80):
            with self.subTest(new_reserve=new_reserve):
                clock, config, emotion = self.setup_tracker(initial=40)
                config.Emotion_MinReserve = 150
                with self.assertRaises(ScriptEnd):
                    emotion.check_reduce(6)
                clock.advance(42 * 60_000_000)
                config.Emotion_MinReserve = new_reserve
                production.Emotion(config).check_reduce(6)
                self.assertIsNone(config.Emotion_RecoveryWait)

    def test_reserve_is_limited_to_calculation_modes(self):
        for mode in ('calculate', 'calculate_ignore', 'ignore'):
            with self.subTest(mode=mode):
                _, config, emotion = self.setup_tracker(initial=40)
                config.Emotion_MinReserve = 150
                config.Emotion_Mode = mode
                if mode == 'ignore':
                    before = copy.deepcopy(config.fields)
                    emotion.check_reduce(6)
                    emotion.check_fleet(2)
                    emotion.reduce(1)
                    self.assertEqual(before, config.fields)
                else:
                    with self.assertRaises(ScriptEnd):
                        emotion.check_reduce(6)
                    self.assertEqual(['1'], config.Emotion_RecoveryWait)

    def test_reserve_in_map_wait_uses_same_recovery_target(self):
        clock, config, emotion = self.setup_tracker(initial=40)
        config.Emotion_MinReserve = 150
        with patch.object(production, 'sleep', side_effect=lambda seconds: clock.advance(seconds * 1_000_000)) as sleep:
            emotion.wait(1)
            self.assertEqual(150, config.Emotion_Fleet1Value)
            self.assertIsNone(config.Emotion_RecoveryWait)
            calls = sleep.call_count
            emotion.reduce(1)
            emotion.wait(1)
            self.assertEqual(calls, sleep.call_count)
        production.Emotion(config).check_reduce(6)
        self.assertEqual(148, config.Emotion_Fleet1Value)
        self.assertIsNone(config.Emotion_RecoveryWait)

    def test_uncalibrated_standby_does_not_stop_and_legacy_config_migrates(self):
        _, config, emotion = self.setup_tracker()
        config.Emotion_Fleet2RecoveryState = None
        emotion.check_reduce(1)
        self.assertEqual(70, config.Emotion_Fleet2Value)
        self.assertIsNone(config.Emotion_Fleet2RecoveryState)
        # 升级前的配置只有数值与时间：重建后按当前值继续，不要求人工校准。
        config.Emotion_Fleet1RecoveryState = None
        emotion.check_reduce(1)
        self.assertIn(config.Emotion_Fleet1RecoveryState['version'], (1, 2))
        self.assertEqual(70, config.Emotion_Fleet2Value)

    def test_handoff_precheck_validates_standby_without_consuming_emotion(self):
        _, config, emotion = self.setup_tracker()
        config.Emotion_Fleet2RecoveryState = None
        emotion.check_fleet(2)
        self.assertIsNotNone(config.Emotion_Fleet2RecoveryState)
        self.assertEqual((70, 70), (config.Emotion_Fleet1Value, config.Emotion_Fleet2Value))

    def test_handoff_precheck_rejects_invalid_successor(self):
        _, config, emotion = self.setup_tracker()
        config.Emotion_Fleet2Value = None
        config.Emotion_Fleet2RecoveryState = None
        with self.assertRaises(RequestHumanTakeover):
            emotion.check_fleet(2)
        self.assertIsNone(config.Emotion_Fleet2Value)
        self.assertEqual(config.Emotion_Fleet1Value, 70)

    def test_handoff_precheck_delays_low_successor(self):
        clock, config, emotion = self.setup_tracker()
        config.Emotion_Fleet2Value = 0
        config.Emotion_Fleet2RecoveryState = production.EmotionRecoveryState.calibrate(
            0, clock.now(), 'dormitory_floor_2', True, False).export()
        with self.assertRaises(ScriptEnd):
            emotion.check_fleet(2)
        self.assertEqual((70, 0), (config.Emotion_Fleet1Value, config.Emotion_Fleet2Value))
        self.assertGreater(config.fields['Main.Scheduler.NextRun'], clock.now())

    def test_handoff_precheck_respects_public_and_ignore_modes(self):
        _, config, emotion = self.setup_tracker(public=True)
        config.Emotion_Fleet2Value = None
        config.Emotion_Fleet2RecoveryState = None
        emotion.check_fleet(2)
        self.assertEqual(config.PublicEmotion_FleetValue, 70)
        for mode in ('ignore', 'calculate_ignore'):
            with self.subTest(mode=mode):
                config.Emotion_Mode = mode
                emotion.check_fleet(2)
                self.assertEqual(config.PublicEmotion_FleetValue, 70)

    def test_broken_recovery_state_is_rebuilt_conservatively(self):
        _, config, emotion = self.setup_tracker()
        # 版本无效的存档不可信：按当前心情值重建，三件套回到一致。
        config.Emotion_Fleet1RecoveryState = {'version': 3}
        emotion.check_reduce(1)
        self.assertIn(config.Emotion_Fleet1RecoveryState['version'], (1, 2))
        self.assertEqual(config.Emotion_Fleet1Record, emotion.fleet_1.record)
        self.assertEqual(70, config.Emotion_Fleet1Value)

    def test_three_way_mismatch_is_repaired(self):
        clock, config, emotion = self.setup_tracker(initial=143)
        # 实机现场：数值、记录时刻与相位互相矛盾，restore 报“不一致”，任务被拦。
        stale = EmotionRecoveryState.calibrate(150, clock.now() - timedelta(hours=5),
                                              'dormitory_floor_2', True, False)
        config.Emotion_Fleet1RecoveryState = stale.export()
        config.Emotion_Fleet1Value = 143
        config.Emotion_Fleet1Record = clock.now() - timedelta(hours=6)
        emotion.check_reduce(1)
        restored = EmotionRecoveryState.restore(config.Emotion_Fleet1RecoveryState,
                                               config.Emotion_Fleet1Value, config.Emotion_Fleet1Record,
                                               'dormitory_floor_2', True, False)
        # 重建以配置值为准，不沿用存档里偏高的 150。
        self.assertEqual(143, restored.value)

    def test_condition_change_rebuilds_from_current_value(self):
        _, config, emotion = self.setup_tracker()
        config.Emotion_Fleet1Recover = 'dormitory_floor_1'
        emotion.check_reduce(1)
        self.assertEqual('dormitory_floor_1', config.Emotion_Fleet1RecoveryState['signature'][0])

    def test_ignore_mode_does_not_require_calibration_or_record_costs(self):
        _, config, emotion = self.setup_tracker()
        config.Emotion_Mode = 'ignore'
        config.Emotion_Fleet1RecoveryState = None
        before = copy.deepcopy(config.fields)
        emotion.check_reduce(1)
        emotion.reduce(1)
        emotion.reduce(1, shipwreck=True)
        self.assertEqual(before, config.fields)

    def test_display_midpoint_does_not_authorize_unsafe_battle(self):
        clock, config, emotion = self.setup_tracker(initial=40)
        clock.advance(60_000_000)
        with self.assertRaises(ScriptEnd):
            emotion.check_reduce(1)
        self.assertGreater(emotion.fleet_1.current, 42)
        self.assertEqual(40, emotion.fleet_1.lower)
        self.assertGreater(config.fields['Main.Scheduler.NextRun'], clock.now())

    def test_save_latency_and_repeat_save_use_calculation_time(self):
        clock, config, emotion = self.setup_tracker()
        clock.advance(100_123_456)
        emotion.update()
        calculated_at = clock.now()
        clock.advance(30_333_333)
        emotion.record()
        emotion.record()
        self.assertEqual(calculated_at, config.Emotion_Fleet1Record)
        emotion.update()
        self.assertLessEqual(abs(emotion.fleet_1.current - clock.oracle.values[0]), 3)
        self.assertEqual(clock.now(), emotion.fleet_1.state.record)

    def test_recovery_condition_change_rebuilds(self):
        _, config, emotion = self.setup_tracker(public=True)
        config.PublicEmotion_FleetOath = False
        emotion.check_reduce(1)
        self.assertFalse(config.PublicEmotion_FleetRecoveryState['signature'][1])

    def test_red_fallback_recovers_automatically_after_json_reload(self):
        for public in (False, True):
            with self.subTest(public=public):
                clock, config, emotion = self.setup_tracker(public=public)
                prefixes = ['PublicEmotion_Fleet'] if public else ['Emotion_Fleet1', 'Emotion_Fleet2']
                for prefix in prefixes:
                    setattr(config, prefix + 'RecoveryState', None)
                reset_at = clock.now()
                emotion.emergency_reset()
                for prefix in prefixes:
                    self.assertEqual(0, getattr(config, prefix + 'Value'))
                    self.assertEqual(reset_at, getattr(config, prefix + 'Record'))
                    self.assertEqual([[0, PERIOD_US, 0]],
                                     getattr(config, prefix + 'RecoveryState')['segments'])
                if public:
                    self.assertEqual(70, config.Emotion_Fleet1Value)
                    config.task.command = 'Event'

                # 每批6点，防绿脸40加一场2点，需要完整恢复7批，即42分钟。
                reloaded = production.Emotion(config)
                with self.assertRaises(ScriptEnd):
                    reloaded.check_reduce(1)
                target_key = f'{config.task.command}.Scheduler.NextRun'
                recovered = config.fields[target_key]
                self.assertEqual(reset_at.replace(microsecond=0) + timedelta(minutes=42, seconds=1),
                                 recovered)
                clock.advance(7 * PERIOD_US - 1)
                with self.assertRaises(ScriptEnd):
                    reloaded.check_reduce(1)
                clock.advance((recovered - clock.now()) // timedelta(microseconds=1))
                reloaded = production.Emotion(config)
                reloaded.check_reduce(1)
                fleet = reloaded.public_fleet if public else reloaded.fleet_1
                self.assertGreaterEqual(fleet.lower, 42)
                reloaded.reduce(1)
                self.assertGreaterEqual(fleet.lower, 40)

    def test_red_popup_delays_until_full_map_can_run(self):
        clock, config, emotion = self.setup_tracker()
        reset_at = clock.now()

        def withdraw():
            raise CampaignEnd

        handler = SimpleNamespace(
            emotion=emotion, config=config, _map_battle=6,
            handle_use_data_key=lambda: False, handle_popup_cancel=lambda name: True,
            _emotion_emergency_exit=withdraw)
        with self.assertRaisesRegex(ScriptEnd, '心情清零并延时'):
            InfoHandler.handle_combat_low_emotion(handler)
        recovered = config.fields['Main.Scheduler.NextRun']
        # 防绿脸40加下一轮6场的12点，需要9批，每批6分钟。
        self.assertEqual(reset_at.replace(microsecond=0) + timedelta(minutes=54, seconds=1), recovered)
        clock.advance((recovered - clock.now()) // timedelta(microseconds=1))
        reloaded = production.Emotion(config)
        reloaded.check_reduce(6)
        self.assertGreaterEqual(reloaded.fleet_1.lower, 52)

    def test_clock_rollback_cannot_authorize_sortie(self):
        clock, _, emotion = self.setup_tracker()
        clock.advance(100_000_000)
        emotion.check_reduce(1)
        clock.us -= 1
        with self.assertRaises(RequestHumanTakeover):
            emotion.check_reduce(1)

    def test_record_conflict_does_not_authorize_using_old_state(self):
        clock, config, emotion = self.setup_tracker()
        original_multi_set = config.multi_set

        @contextmanager
        def recalibrate_during_save():
            with original_multi_set():
                yield
            stamp = clock.now() + timedelta(microseconds=1)
            config.Emotion_Fleet1Record = stamp
            config.Emotion_Fleet1RecoveryState = EmotionRecoveryState.calibrate(
                70, stamp, 'dormitory_floor_2', True, False).export()

        with patch.object(config, 'multi_set', recalibrate_during_save), self.assertRaises(RequestHumanTakeover):
            emotion.check_reduce(1)
        self.assertEqual(70, config.Emotion_Fleet1Value)
        self.assertIsNone(emotion.fleet_1.state)

    def test_double_book_oversized_map_limit_still_recovers(self):
        _, config, emotion = self.setup_tracker(initial=120)
        config.Emotion_Fleet1Control = 'keep_exp_bonus'
        emotion.update()
        target = emotion.fleet_1.get_recovered(32)
        emotion.fleet_1.state.advance(target)
        self.assertGreaterEqual(emotion.fleet_1.lower, 149)

    def test_shared_fleet_reload_uses_latest_task_state(self):
        report = simulate(ShipSpec('dormitory_floor_2', True), battles=300, public=True, alternate=True)
        self.assertLessEqual(max(report['max_overestimate'], report['max_underestimate']), 3)
        self.assertGreater(report['delays'], 0)

    def test_public_fleet_real_config_bind_and_save_across_tasks(self):
        from module.api.config_service import ConfigService
        from module.api.protocol import ConfigChange
        from tests.test_api import fixture

        clock, _, _ = self.setup_tracker(initial=85)
        with tempfile.TemporaryDirectory() as directory:
            service = ConfigService(fixture(directory))
            with patch('module.api.config_service.current_time', clock.now):
                service.patch('testpilot', None, [
                    ConfigChange(path='General.PublicEmotion.Enable', value=True),
                    ConfigChange(path='General.PublicEmotion.Tasks', value='Main, Event'),
                    ConfigChange(path='General.PublicEmotion.FleetRecover', value='dormitory_floor_2'),
                    ConfigChange(path='General.PublicEmotion.FleetOath', value=True),
                    ConfigChange(path='General.PublicEmotion.FleetValue', value=85),
                ])
            path = str(service.path('testpilot'))
            real = AzurLaneConfig.__new__(AzurLaneConfig)
            real.config_name = 'testpilot'
            real.root = service.root
            real.modified, real.bound, real.overridden = {}, {}, {}
            real.data = real.config_update(service.read('testpilot')[0])
            real._loaded_data = copy.deepcopy(real.data)
            real.auto_update = True
            with patch('module.config.config.filepath_config', return_value=path), patch(
                'module.config.config_updater.filepath_config', return_value=path
            ), patch.object(AzurLaneConfig, 'config_override'):
                for task in ('Main', 'Event'):
                    real.bind(task)
                    real.task = Function(real.data[task])
                    emotion = production.Emotion(real)
                    self.assertTrue(emotion.using_public)
                    emotion.check_reduce(1)
                    emotion.reduce(1)
                fields = service.read('testpilot')[0]['General']['PublicEmotion']
                self.assertEqual(81, fields['FleetValue'])
                self.assertEqual([[0, PERIOD_US, 81]], fields['FleetRecoveryState']['segments'])

                emotion.emergency_reset()
                fields = service.read('testpilot')[0]['General']['PublicEmotion']
                self.assertEqual(0, fields['FleetValue'])
                self.assertEqual([[0, PERIOD_US, 0]], fields['FleetRecoveryState']['segments'])
                clock.advance(42 * 60_000_000)
                real.bind('Main')
                real.task = Function(real.data['Main'])
                reloaded = production.Emotion(real)
                reloaded.check_reduce(1)
                self.assertGreaterEqual(reloaded.public_fleet.lower, 42)

    def test_legacy_config_migrates_and_persists_on_first_run(self):
        clock, _, _ = self.setup_tracker(initial=119)
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'anonymous.json')
            # 升级前的存档：只有数值与时间，没有恢复相位记录。
            disk = {'Main': {'Scheduler': {'Enable': False, 'Command': 'Main', 'NextRun': clock.now()},
                             'Emotion': {
                                 'Fleet1Value': 119, 'Fleet1Record': clock.now(),
                                 'Fleet1Control': 'prevent_green_face', 'Fleet1Recover': 'not_in_dormitory',
                                 'Fleet1Oath': False, 'Fleet1Onsen': False, 'Fleet1RecoveryState': None,
                                 'Fleet2Value': 119, 'Fleet2Record': clock.now(),
                                 'Fleet2Control': 'prevent_green_face', 'Fleet2Recover': 'not_in_dormitory',
                                 'Fleet2Oath': False, 'Fleet2Onsen': False, 'Fleet2RecoveryState': None}},
                    'Alas': {'PublicEmotion': {'Enable': False, 'Tasks': ''}}}
            write_file(path, disk)
            real = AzurLaneConfig.__new__(AzurLaneConfig)
            real.bound, real.modified, real.overridden = {}, {}, {}
            real.config_name = 'anonymous'
            real.data = copy.deepcopy(disk)
            real._loaded_data = copy.deepcopy(disk)
            real.auto_update = True
            real.task = Function(disk['Main'])

            def read_config(name):
                data = read_file(path)
                for key in list(data['Main']['Emotion']):
                    if key.endswith('Record'):
                        data['Main']['Emotion'][key] = datetime.fromisoformat(data['Main']['Emotion'][key])
                data['Main']['Scheduler']['NextRun'] = datetime.fromisoformat(data['Main']['Scheduler']['NextRun'])
                return data

            real.read_file = read_config
            real.write_file = lambda name, data: write_file(path, data)
            real.bind('Main')
            with patch.object(config_source, 'filepath_config', return_value=path):
                emotion = production.Emotion(real)
                # 旧配置不再要求人工接管，重建后三件套自洽。
                emotion.check_reduce(1)
                saved = json.loads(Path(path).read_text(encoding='utf-8'))['Main']['Emotion']
                self.assertIsNotNone(saved.get('Fleet1RecoveryState') or saved.get('Fleet2RecoveryState'))
                self.assertEqual(2, saved['Fleet2RecoveryState']['version'])
                self.assertEqual(datetime.fromisoformat(saved['Fleet2Record']),
                                 datetime.fromisoformat(saved['Fleet2RecoveryState']['record']))
                self.assertEqual(saved['Fleet2Value'], saved['Fleet2RecoveryState']['segments'][0][2])
                # 重新加载后状态可恢复，不会陷入重复迁移。
                real.data = read_config('anonymous')
                real._loaded_data = copy.deepcopy(real.data)
                real.bind('Main')
                self.assertIsNotNone(real.Emotion_Fleet2RecoveryState)

    def test_real_atomic_json_matches_memory_through_restarts(self):
        clock, fake, left = self.setup_tracker()
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'anonymous.json')
            disk = {'Main': {'Scheduler': {'Enable': False, 'Command': 'Main', 'NextRun': clock.now()},
                             'Emotion': {key.removeprefix('Emotion_'): value for key, value in fake.fields.items()
                                         if key.startswith('Emotion_')}},
                    'Alas': {'PublicEmotion': {'Enable': False, 'Tasks': ''}}}
            write_file(path, disk)
            real = AzurLaneConfig.__new__(AzurLaneConfig)
            real.bound, real.modified, real.overridden = {}, {}, {}
            real.config_name = 'anonymous'
            real.data = copy.deepcopy(disk)
            real._loaded_data = copy.deepcopy(disk)
            real.auto_update = True
            real.task = Function(disk['Main'])

            def read_config(name):
                data = read_file(path)
                for key, value in data['Main']['Emotion'].items():
                    if key.endswith('Record'):
                        data['Main']['Emotion'][key] = datetime.fromisoformat(value)
                data['Main']['Scheduler']['NextRun'] = datetime.fromisoformat(data['Main']['Scheduler']['NextRun'])
                return data

            real.read_file = read_config
            real.write_file = lambda name, data: write_file(path, data)
            real.bind('Main')
            with patch.object(config_source, 'filepath_config', return_value=path):
                for i in range(100):
                    clock.advance(90_000_000 + i * 7919)
                    right = production.Emotion(real)
                    left.reduce(1)
                    right.reduce(1)
                    clock.oracle.consume(0, 2)
                    for prefix in ('Emotion_Fleet1', 'Emotion_Fleet2'):
                        for suffix in ('Value', 'Record', 'RecoveryState'):
                            self.assertEqual(getattr(fake, prefix + suffix), getattr(real, prefix + suffix))
                    saved = json.loads(Path(path).read_text(encoding='utf-8'))['Main']['Emotion']
                    self.assertEqual(saved['Fleet1RecoveryState']['record'], real.Emotion_Fleet1Record.isoformat(timespec='microseconds'))
                    self.assertEqual(saved['Fleet1Value'], right.fleet_1.current)


class EmotionReserveConfigTests(unittest.TestCase):
    def setUp(self):
        from module.api.config_service import ConfigService
        from tests.test_api import fixture

        self.directory = self.enterContext(tempfile.TemporaryDirectory())
        self.configs = ConfigService(fixture(self.directory))

    def test_generated_reserve_order_defaults_and_translations(self):
        for task, groups in self.configs.args.items():
            if 'Emotion' not in groups:
                continue
            with self.subTest(task=task):
                fields = list(groups['Emotion'])
                self.assertEqual('MinReserve', fields[fields.index('IgnoreShipwreck') + 1])
                self.assertEqual(0, groups['Emotion']['MinReserve']['value'])
                self.assertEqual([0, 150], groups['Emotion']['MinReserve']['validate'])
                self.assertEqual('stored', groups['Emotion']['RecoveryWait']['type'])
                self.assertEqual('hide', groups['Emotion']['RecoveryWait']['display'])
        for language in ('zh-CN', 'en-US', 'ja-JP', 'zh-TW'):
            translations = json.loads(Path(f'module/config/i18n/{language}.json').read_text(encoding='utf-8'))
            for field in ('MinReserve', 'RecoveryWait'):
                self.assertTrue(translations['Emotion'][field]['name'])
                self.assertNotIn('Emotion.', translations['Emotion'][field]['name'])
            self.assertTrue(translations['Emotion']['MinReserve']['help'])

    def test_reserve_api_validates_integer_range_and_persists(self):
        from module.api.protocol import ApiError, ConfigChange

        path = 'Main.Emotion.MinReserve'
        for value in (0, 1, 80, 150):
            with self.subTest(value=value):
                self.configs.patch('testpilot', None, [ConfigChange(path=path, value=value)])
                self.assertEqual(value, self.configs.read_json(self.configs.path('testpilot'))['Main']['Emotion']['MinReserve'])
        before = self.configs.path('testpilot').read_bytes()
        for value in (-1, 151, 80.5, True, '150', None):
            with self.subTest(value=value), self.assertRaises(ApiError):
                self.configs.patch('testpilot', None, [ConfigChange(path=path, value=value)])
        with self.assertRaises(ApiError):
            self.configs.patch('testpilot', None, [ConfigChange(path='Main.Emotion.RecoveryWait', value=None)])
        self.assertEqual(before, self.configs.path('testpilot').read_bytes())

    def test_old_config_fills_disabled_defaults_without_writing_on_read(self):
        path = self.configs.path('testpilot')
        data = self.configs.read_json(path)
        for field in ('MinReserve', 'RecoveryWait'):
            data['Main']['Emotion'].pop(field)
        path.write_text(json.dumps(data), encoding='utf-8')
        before = path.read_bytes()
        fields = self.configs.get('testpilot')['values']['Main']['Emotion']
        self.assertEqual(0, fields['MinReserve'])
        self.assertIsNone(fields['RecoveryWait'])
        self.assertEqual(before, path.read_bytes())
        migrated = AzurLaneConfig.__new__(AzurLaneConfig).config_update(data)
        self.assertEqual(0, migrated['Main']['Emotion']['MinReserve'])
        self.assertIsNone(migrated['Main']['Emotion']['RecoveryWait'])

    def test_public_reserve_wait_persists_in_real_json_and_is_task_specific(self):
        from module.api.protocol import ConfigChange

        clock = Clock(500_000, LuaOracle(ShipSpec('dormitory_floor_2', True), 30, 500_000, 0))
        self.enterContext(patch.object(production, 'current_time', clock.now))
        self.enterContext(patch.object(config_source, 'current_time', clock.now))
        self.enterContext(patch.object(production, 'logger', QuietLogger()))
        self.enterContext(patch.object(config_source, 'logger', QuietLogger()))
        with patch('module.api.config_service.current_time', clock.now):
            self.configs.patch('testpilot', None, [
                ConfigChange(path='Main.Emotion.MinReserve', value=150),
                ConfigChange(path='General.PublicEmotion.Enable', value=True),
                ConfigChange(path='General.PublicEmotion.Tasks', value='Main, Event'),
                ConfigChange(path='General.PublicEmotion.FleetControl', value='prevent_yellow_face'),
                ConfigChange(path='General.PublicEmotion.FleetRecover', value='dormitory_floor_2'),
                ConfigChange(path='General.PublicEmotion.FleetOath', value=True),
                ConfigChange(path='General.PublicEmotion.FleetValue', value=30),
            ])
        path = str(self.configs.path('testpilot'))
        self.enterContext(patch('module.config.config.filepath_config', return_value=path))
        self.enterContext(patch('module.config.config_updater.filepath_config', return_value=path))
        self.enterContext(patch.object(AzurLaneConfig, 'config_override'))

        def load(task):
            config = AzurLaneConfig.__new__(AzurLaneConfig)
            config.config_name = 'testpilot'
            config.root = self.configs.root
            config.modified, config.bound, config.overridden = {}, {}, {}
            config.data = config.config_update(self.configs.read('testpilot')[0])
            config._loaded_data = copy.deepcopy(config.data)
            config.auto_update = True
            config.bind(task)
            config.task = Function(config.data[task])
            return production.Emotion(config)

        with self.assertRaises(ScriptEnd):
            load('Main').check_reduce(6)
        saved = self.configs.read_json(Path(path))
        original_target = datetime.fromisoformat(saved['Main']['Scheduler']['NextRun'])
        self.assertEqual(['Public'], saved['Main']['Emotion']['RecoveryWait'])
        self.assertIsNone(saved['Event']['Emotion']['RecoveryWait'])

        clock.advance(18 * 60_000_000)
        other = load('Event')
        other.check_reduce(1)
        other.reduce(1)
        self.assertEqual(46, other.config.PublicEmotion_FleetValue)
        with self.assertRaises(ScriptEnd):
            load('Main').check_reduce(6)
        saved = self.configs.read_json(Path(path))
        target = datetime.fromisoformat(saved['Main']['Scheduler']['NextRun'])
        self.assertGreater(target, original_target)
        self.assertIsNone(saved['Event']['Emotion']['RecoveryWait'])
        clock.advance((target - clock.now()) // timedelta(microseconds=1))
        load('Main').check_reduce(6)
        self.assertIsNone(self.configs.read_json(Path(path))['Main']['Emotion']['RecoveryWait'])


if __name__ == '__main__':
    unittest.main()
