"""塞壬要塞战斗结果的离线回归，避免失败被当成补币成功。"""

import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

from module.exception import RequestHumanTakeover
from module.os.fleet import BossFleet
from module.os.tasks.stronghold import OpsiStronghold


class TestStrongholdOutcome(unittest.TestCase):
    """保留 clear_stronghold 与 run_stronghold 的真实结果传递。"""

    def make_runner(self, results):
        runner = OpsiStronghold.__new__(OpsiStronghold)
        runner.config = SimpleNamespace(
            OpsiStronghold_SubmarineEveryCombat=False,
            OpsiStronghold_HasStronghold=True,
            multi_set=lambda: nullcontext(),
        )
        for method_name in (
            'cl1_ap_preserve', 'os_map_goto_globe', 'globe_update',
            'os_globe_goto_map', 'globe_enter', 'zone_init', 'os_order_execute',
            'handle_fleet_repair_by_config', 'handle_fleet_resolve',
            '_postpone_stronghold_check',
        ):
            setattr(runner, method_name, Mock())
        runner.find_siren_stronghold = Mock(side_effect=[Mock(), None])
        runner._handle_coin_task_no_content = Mock(return_value=True)
        runner.parse_fleet_filter = Mock(return_value=[BossFleet(index + 1) for index in range(len(results))])
        runner.run_stronghold_one_fleet = Mock(side_effect=results)
        return runner

    def test_exhausted_fleets_request_human_takeover(self):
        runner = self.make_runner(results=[False, False])

        with self.assertRaises(RequestHumanTakeover):
            runner.clear_stronghold()

        # 无法击败 Boss 时中止，不能继续修理、记为无内容或给调度器报成功。
        self.assertEqual(runner.run_stronghold_one_fleet.call_count, 2)
        runner.handle_fleet_repair_by_config.assert_not_called()
        runner.handle_fleet_resolve.assert_not_called()
        runner._postpone_stronghold_check.assert_not_called()
        runner._handle_coin_task_no_content.assert_not_called()
        self.assertEqual(runner.find_siren_stronghold.call_count, 1)
        self.assertTrue(runner.config.OpsiStronghold_HasStronghold)

    def test_success_keeps_post_battle_cleanup_and_content_check(self):
        runner = self.make_runner(results=[False, True])

        runner.clear_stronghold()

        self.assertEqual(runner.run_stronghold_one_fleet.call_count, 2)
        runner.handle_fleet_repair_by_config.assert_called_once_with(revert=False)
        runner.handle_fleet_resolve.assert_called_once_with(revert=False)
        runner._postpone_stronghold_check.assert_called_once_with('塞壬要塞没有更多可执行内容')
        runner._handle_coin_task_no_content.assert_called_once_with('塞壬要塞', '塞壬要塞没有更多可执行内容')
        self.assertFalse(runner.config.OpsiStronghold_HasStronghold)


if __name__ == '__main__':
    unittest.main()
