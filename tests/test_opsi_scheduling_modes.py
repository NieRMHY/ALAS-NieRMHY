"""智能调度两种模式的配置归属与决策回归，不连接游戏。"""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from module.os.tasks.scheduling import OpsiScheduling


class TestSmartSchedulingModes(unittest.TestCase):
    def make_scheduling(self, coin_target, smart_preserve=40000, cl1_preserve=90000):
        scheduling = OpsiScheduling.__new__(OpsiScheduling)
        values = {
            scheduling.CONFIG_PATH_USE_SMART_CL1_PRESERVE: coin_target,
            scheduling.CONFIG_PATH_SMART_CL1_PRESERVE: smart_preserve,
            scheduling.CONFIG_PATH_CL1_PRESERVE: cl1_preserve,
            scheduling.CONFIG_PATH_SMART_COIN_RETURN_THRESHOLD: 20000,
            scheduling.CONFIG_PATH_SMART_AP_PRESERVE: 200,
            scheduling.CONFIG_PATH_CL1_MIN_AP_RESERVE: 100,
        }
        config = SimpleNamespace(
            task=SimpleNamespace(command='OpsiScheduling'),
            modified={},
            cross_get=lambda keys, default=None: values.get(keys, default),
        )

        def save():
            values.update(config.modified)
            config.modified.clear()

        config.save = save
        scheduling.config = config
        return scheduling, values

    def run_decision(self, scheduling, yellow_coins, total_ap=500):
        with (
            patch.object(scheduling, 'get_yellow_coins', return_value=yellow_coins),
            patch.object(scheduling, '_get_scheduling_action_point', return_value=(total_ap, 100)),
            patch.object(scheduling, '_reset_month_end_cleanup_first_run_if_new_month'),
            patch.object(scheduling, '_is_month_end_cleanup_active', return_value=False),
            patch.object(scheduling, '_dispatch_coin_task') as dispatch,
            patch.object(scheduling, '_execute_hazard1_leveling') as leveling,
        ):
            scheduling.run_smart_scheduling_once()
        return dispatch, leveling

    def test_both_modes_level_when_own_coin_reserve_is_met(self):
        # 侵蚀 1 的保留值更高，不应影响智能调度自己的补币决策。
        for coin_target in (True, False):
            with self.subTest(coin_target=coin_target):
                scheduling, _ = self.make_scheduling(coin_target)
                dispatch, leveling = self.run_decision(scheduling, yellow_coins=60000)
                dispatch.assert_not_called()
                leveling.assert_called_once_with(60000, 500, 100)

    def test_both_modes_replenish_when_below_own_coin_reserve(self):
        # 侵蚀 1 的保留值更低，仍应按智能调度保留值进入补币阶段。
        for coin_target, target in ((True, 60000), (False, 40000)):
            with self.subTest(coin_target=coin_target):
                scheduling, _ = self.make_scheduling(coin_target, cl1_preserve=10000)
                dispatch, leveling = self.run_decision(scheduling, yellow_coins=30000)
                dispatch.assert_called_once_with(30000, 500, target, 200, 100)
                leveling.assert_not_called()

    def test_zero_coin_reserve_is_valid_in_both_modes(self):
        for coin_target in (True, False):
            with self.subTest(coin_target=coin_target):
                scheduling, _ = self.make_scheduling(coin_target, smart_preserve=0)
                dispatch, leveling = self.run_decision(scheduling, yellow_coins=0)
                dispatch.assert_not_called()
                leveling.assert_called_once_with(0, 500, 100)

    def test_missing_coin_reserve_defaults_to_zero(self):
        for coin_target in (True, False):
            with self.subTest(coin_target=coin_target):
                scheduling, values = self.make_scheduling(coin_target)
                values.pop(scheduling.CONFIG_PATH_SMART_CL1_PRESERVE)
                self.assertEqual(scheduling._get_smart_scheduling_operation_coins_preserve(), 0)

    def test_fallback_meow_ap_reserve_preserves_explicit_zero(self):
        scheduling, values = self.make_scheduling(False)
        values[scheduling.CONFIG_PATH_SMART_AP_PRESERVE] = 0
        values[scheduling.CONFIG_PATH_MEOW_AP_PRESERVE] = 0
        self.assertEqual(scheduling._get_coin_task_action_point_preserve(), 0)

    def test_missing_fallback_meow_ap_reserve_uses_default(self):
        scheduling, values = self.make_scheduling(False)
        values[scheduling.CONFIG_PATH_SMART_AP_PRESERVE] = 0
        self.assertEqual(scheduling._get_coin_task_action_point_preserve(), 1000)
