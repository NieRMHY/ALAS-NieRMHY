"""
岛屿计划总览「刷新方案」开关的离线测试：配置键映射 + 一次性开关语义。
"""
import os
import tempfile
import unittest
from unittest.mock import patch

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

    def setUp(self):
        # 刷新会写「上次自动生成的上架清单」，指到临时文件，别落到工作区里
        import module.island.island_plan_refresh as refresh
        fd, path = tempfile.mkstemp(suffix='.json')
        os.close(fd)
        os.remove(path)
        self._orig_generated = refresh.GENERATED_FILE
        refresh.GENERATED_FILE = path

    def tearDown(self):
        import module.island.island_plan_refresh as refresh
        try:
            os.remove(refresh.GENERATED_FILE)
        except OSError:
            pass
        refresh.GENERATED_FILE = self._orig_generated

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


class TestExtraMealsSwitch(unittest.TestCase):
    """PlanExtraMeals（额外餐品排产，默认关）被读取并透传给 plan_all。

    销量封顶口径下不在货架上的商品卖不掉，额外餐品循环只会占满槽位、把赛季囤积
    挤掉，所以默认必须关闭；配置里显式打开才排。
    """

    def setUp(self):
        import module.island.island_plan_refresh as refresh
        self.refresh = refresh
        fd, path = tempfile.mkstemp(suffix='.json')
        os.close(fd)
        os.remove(path)
        self._orig_generated = refresh.GENERATED_FILE
        refresh.GENERATED_FILE = path

    def tearDown(self):
        try:
            os.remove(self.refresh.GENERATED_FILE)
        except OSError:
            pass
        self.refresh.GENERATED_FILE = self._orig_generated

    def _refresh_with(self, extra):
        values = {
            'IslandPlan.IslandPlan.RefreshPlan': True,
            'IslandPlan.IslandPlan.Season': 'autumn',
            # 别去挖真实日志更新白名单，测试不该动工作区里的名单文件
            'IslandPlan.IslandPlan.PlanMineVerified': False,
            'IslandPlan.IslandPlan.PlanVerifiedOnly': False,
        }
        if extra:
            values['IslandPlan.IslandPlan.PlanExtraMeals'] = extra
        config = FakeConfig(values)
        with patch.object(self.refresh, 'plan_all', return_value={}) as plan_all:
            self.assertTrue(refresh_plan_if_requested(config))
        return plan_all.call_args

    def test_default_off(self):
        """配置里没有该键时按关闭处理"""
        call = self._refresh_with(None)
        self.assertFalse(call.kwargs['extra_meals'])

    def test_switch_on_passed_through(self):
        call = self._refresh_with(True)
        self.assertTrue(call.kwargs['extra_meals'])


if __name__ == '__main__':
    unittest.main()
