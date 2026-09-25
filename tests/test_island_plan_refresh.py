"""
岛屿计划总览「刷新方案」开关的离线测试：配置键映射 + 一次性开关语义。
"""
import os
import tempfile
import unittest

import module.island.island_planner as planner
from module.island.island_planner import config_key_values, plan_all
from module.island.island_plan_refresh import refresh_plan_if_requested


class FakeConfig:
    """最小配置替身：记录 cross_set 的值，模拟一次性开关。"""

    def __init__(self, values=None):
        self.values = dict(values or {})
        self.saved = 0

    def cross_get(self, keys, default=None):
        return self.values.get(keys, default)

    def cross_set(self, keys, value):
        self.values[keys] = value

    def cross_set_many(self, values):
        self.values.update(values)

    def update(self):
        self.saved += 1


class TestConfigKeyValues(unittest.TestCase):

    def setUp(self):
        fd, path = tempfile.mkstemp(suffix='.json')
        os.close(fd)
        os.remove(path)
        self._orig = planner.UNPRODUCIBLE_FILE
        planner.UNPRODUCIBLE_FILE = path

    def tearDown(self):
        try:
            os.remove(planner.UNPRODUCIBLE_FILE)
        except OSError:
            pass
        planner.UNPRODUCIBLE_FILE = self._orig

    def test_keys_cover_all_slots(self):
        values = config_key_values(plan_all(shops=['grill'], season='autumn'))
        self.assertIn('IslandGrill.IslandGrill.Meal1', values)
        self.assertIn('IslandGrill.IslandGrill.MealNumber1', values)
        self.assertGreaterEqual(values['IslandGrill.IslandGrill.MealNumber1'], 2)
        # 上架清单必须写在经营端分组下（顶层路径 ALAS 不读）
        self.assertIn('IslandBusiness.IslandBusinessShop4.Product1', values)
        self.assertNotIn('IslandBusinessShop4.Product1', values)

    def test_empty_slots_cleared(self):
        values = config_key_values(plan_all(shops=['grill'], season='autumn',
                                            extra_exclude={'grill': {'crayfish_stir_fry'}}))
        self.assertEqual(values['IslandGrill.IslandGrill.Meal8'], 'None')


class TestRefreshSwitch(unittest.TestCase):

    def test_noop_when_switch_off(self):
        config = FakeConfig()
        self.assertFalse(refresh_plan_if_requested(config))
        self.assertEqual(config.values, {})
        self.assertEqual(config.saved, 0)

    def test_refresh_writes_and_resets(self):
        config = FakeConfig({
            'IslandPlan.IslandPlan.RefreshPlan': True,
            'IslandPlan.IslandPlan.Season': 'autumn',
            'IslandPlan.IslandPlan.PlanVerifiedOnly': False,
            'IslandPlan.IslandPlan.PlanMineVerified': False,
            'IslandPlan.IslandPlan.PlanShelfSlots': 5,
        })
        self.assertTrue(refresh_plan_if_requested(config))
        # 已写入生产与上架清单
        self.assertIn('IslandRestaurant.IslandRestaurant.Meal1', config.values)
        self.assertIn('IslandBusiness.IslandBusinessShop1.Product1', config.values)
        # 一次性：开关自动复位并落盘
        self.assertFalse(config.values['IslandPlan.IslandPlan.RefreshPlan'])
        self.assertGreaterEqual(config.saved, 1)

    def test_开关复位后不再触发(self):
        config = FakeConfig({'IslandPlan.IslandPlan.RefreshPlan': True,
                             'IslandPlan.IslandPlan.PlanMineVerified': False})
        refresh_plan_if_requested(config)
        saved_before = config.saved
        self.assertFalse(refresh_plan_if_requested(config))
        self.assertEqual(config.saved, saved_before)


if __name__ == '__main__':
    unittest.main()
