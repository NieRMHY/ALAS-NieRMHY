"""牧场四岗持续养殖的离线测试。

覆盖三件事：
- 默认阈值模式保持原行为，库存未知不再被当成 0；
- ContinuousBreeding 开启后鸡舍/猪圈每轮排产，牛棚/羊圈仍按 Milk/Wool 勾选；
- 饲料未知/不足时派遣决策与持续养殖的低成本补料边界。
"""
import unittest
from pathlib import Path
from types import SimpleNamespace

import yaml

from module.island.island_rancher import IslandRancher

ROOT = Path(__file__).resolve().parents[1]


class RancherStub:
    check_ranch_needs = IslandRancher.check_ranch_needs
    is_ranch_post_enabled = IslandRancher.is_ranch_post_enabled
    ranch_feed_action = IslandRancher.ranch_feed_action
    mark_ranch_retry = IslandRancher.mark_ranch_retry

    def __init__(self, chicken, pork, continuous=False, milk=True, wool=True):
        self.inventory_counts = {'ranch': {'chicken': chicken, 'pork': pork}}
        self.continuous_breeding = continuous
        self.ranch_chicken_threshold = 300
        self.ranch_pork_threshold = 300
        self.ranch_last_finish_time = None
        self.config = SimpleNamespace(IslandRancher_Milk=milk, IslandRancher_Wool=wool)


class RanchNeedsTest(unittest.TestCase):
    def test_default_mode_keeps_threshold_behavior(self):
        stub = RancherStub(chicken=100, pork=400)
        self.assertEqual(
            stub.check_ranch_needs(),
            ['ISLAND_RANCH_POST1', 'ISLAND_RANCH_POST3', 'ISLAND_RANCH_POST4'])

    def test_default_mode_unknown_inventory_is_not_zero(self):
        stub = RancherStub(chicken=None, pork=None)
        self.assertEqual(
            stub.check_ranch_needs(),
            ['ISLAND_RANCH_POST3', 'ISLAND_RANCH_POST4'])

    def test_default_mode_above_threshold_skips_chicken_and_pork(self):
        stub = RancherStub(chicken=300, pork=300)
        self.assertEqual(
            stub.check_ranch_needs(),
            ['ISLAND_RANCH_POST3', 'ISLAND_RANCH_POST4'])

    def test_continuous_mode_runs_all_unlocked_posts(self):
        stub = RancherStub(chicken=9999, pork=9999, continuous=True)
        self.assertEqual(
            stub.check_ranch_needs(),
            ['ISLAND_RANCH_POST1', 'ISLAND_RANCH_POST2',
             'ISLAND_RANCH_POST3', 'ISLAND_RANCH_POST4'])

    def test_continuous_mode_unknown_inventory_still_runs(self):
        stub = RancherStub(chicken=None, pork=None, continuous=True)
        self.assertEqual(
            stub.check_ranch_needs(),
            ['ISLAND_RANCH_POST1', 'ISLAND_RANCH_POST2',
             'ISLAND_RANCH_POST3', 'ISLAND_RANCH_POST4'])

    def test_continuous_mode_respects_unlocked_switches(self):
        stub = RancherStub(chicken=9999, pork=9999, continuous=True, milk=False, wool=True)
        self.assertEqual(
            stub.check_ranch_needs(),
            ['ISLAND_RANCH_POST1', 'ISLAND_RANCH_POST2', 'ISLAND_RANCH_POST4'])

        stub = RancherStub(chicken=9999, pork=9999, continuous=True, milk=False, wool=False)
        self.assertEqual(
            stub.check_ranch_needs(),
            ['ISLAND_RANCH_POST1', 'ISLAND_RANCH_POST2'])

    def test_continuous_flag_defaults_off_for_existing_configs(self):
        stub = SimpleNamespace(config=SimpleNamespace())
        self.assertFalse(IslandRancher.continuous_breeding.fget(stub))
        stub.config = SimpleNamespace(IslandRancher_ContinuousBreeding=True)
        self.assertTrue(IslandRancher.continuous_breeding.fget(stub))


class FeedDecisionTest(unittest.TestCase):
    def test_known_feed_states(self):
        stub = RancherStub(chicken=0, pork=0)
        self.assertEqual(stub.ranch_feed_action(50), 'dispatch')
        self.assertEqual(stub.ranch_feed_action(49), 'retry')

    def test_unknown_feed_waits_in_default_mode(self):
        stub = RancherStub(chicken=0, pork=0)
        self.assertEqual(stub.ranch_feed_action(None), 'skip')

    def test_unknown_feed_attempts_dispatch_in_continuous_mode(self):
        stub = RancherStub(chicken=0, pork=0, continuous=True)
        self.assertEqual(stub.ranch_feed_action(None), 'dispatch')

    def test_retry_only_registered_in_continuous_mode(self):
        stub = RancherStub(chicken=0, pork=0)
        stub.mark_ranch_retry('ISLAND_RANCH_POST1', '饲料不足')
        self.assertIsNone(stub.ranch_last_finish_time)

        stub = RancherStub(chicken=0, pork=0, continuous=True)
        stub.mark_ranch_retry('ISLAND_RANCH_POST1', '饲料不足')
        self.assertIsNotNone(stub.ranch_last_finish_time)


class RanchArgumentTest(unittest.TestCase):
    def test_continuous_breeding_default_is_off(self):
        argument = yaml.safe_load(
            (ROOT / 'module/config/argument/argument.yaml').read_text(encoding='utf-8'))
        self.assertIs(argument['IslandRancher']['ContinuousBreeding'], False)


if __name__ == '__main__':
    unittest.main()
