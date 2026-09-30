"""方案刷新的两道护栏。

背景（均由真机现象定位）：
  1. 「已验证可生产」白名单原来是整体覆盖、只挖最近 3 个日志。真机 log/ 下只有
     一个匹配文件时挖出 4 个商品，把已有的 40 个冲成 4 个；商品只要连续几天没被
     排产就永久退出白名单——与 verified_only 死锁同源。
  2. Product1-5 正是刷新自己写进去的键，却被当成「用户手动上架清单」置顶，
     第二次刷新起货架再也换不了品（离线实测 5 家店 shelf 与线上完全一致）。
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, '.')

import module.island.island_plan_refresh as refresh
import module.island.island_planner as planner


class FakeConfig:
    """最小配置替身（与 test_island_plan_refresh 同款）。"""

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


class TempStateMixin:
    """把状态文件指到临时路径，避免污染工作区。"""

    module = None
    attr = ''

    def setUp(self):
        fd, path = tempfile.mkstemp(suffix='.json')
        os.close(fd)
        os.remove(path)
        self._orig = getattr(self.module, self.attr)
        setattr(self.module, self.attr, path)

    def tearDown(self):
        path = getattr(self.module, self.attr)
        try:
            os.remove(path)
        except OSError:
            pass
        setattr(self.module, self.attr, self._orig)


class TestVerifiedWhitelistGrows(TempStateMixin, unittest.TestCase):
    """白名单只增不减。"""

    module = planner
    attr = 'VERIFIED_FILE'

    def test_union_keeps_existing_when_nothing_mined(self):
        planner.save_verified({'grill': {'double_energy', 'carnival'}})
        counts = planner.refresh_verified_from_logs(
            log_glob='log/__definitely_not_here__*.txt')
        self.assertEqual(counts.get('grill'), 2)
        self.assertEqual(planner.load_verified()['grill'], {'double_energy', 'carnival'})

    def test_remine_adds_without_dropping(self):
        planner.save_verified({'grill': {'double_energy'}})
        with tempfile.TemporaryDirectory() as tmp:
            log = os.path.join(tmp, '2026-09-30_ALAS.txt')
            with open(log, 'w', encoding='utf-8') as f:
                f.write('2026-09-30 00:00:00 | INFO | [岛屿] 已安排生产：烤肉狂欢 x7\n')
            planner.refresh_verified_from_logs(log_glob=os.path.join(tmp, '*.txt'))
        verified = planner.load_verified()
        self.assertIn('double_energy', verified['grill'])  # 原有条目保留
        self.assertIn('carnival', verified['grill'])       # 新挖到的并入


class TestManualShelfSource(TempStateMixin, unittest.TestCase):
    """上架清单来源区分。"""

    module = refresh
    attr = 'GENERATED_FILE'

    @staticmethod
    def _config_with_shelf(shelf_by_shop):
        from module.island.island_planner import SHELF_SLOTS, SHOP_TASKS
        values = {}
        for shop, items in shelf_by_shop.items():
            _, index, _ = SHOP_TASKS[shop]
            for i in range(1, SHELF_SLOTS + 1):
                key = f'IslandBusiness.IslandBusinessShop{index}.Product{i}'
                values[key] = items[i - 1] if i <= len(items) else 'None'
        return values

    def test_own_output_is_not_manual(self):
        plans = planner.plan_all(season='autumn', shelf_slots=4, verified_only=False)
        refresh.save_generated(plans)
        config = FakeConfig(self._config_with_shelf(
            {shop: plan.shelf for shop, plan in plans.items()}))
        self.assertEqual(refresh._manual_shelf(config), {})

    def test_user_edit_is_manual(self):
        plans = planner.plan_all(season='autumn', shelf_slots=4, verified_only=False)
        refresh.save_generated(plans)
        edited = {shop: list(plan.shelf) for shop, plan in plans.items()}
        edited['grill'] = ['steak_bowl']
        config = FakeConfig(self._config_with_shelf(edited))
        manual = refresh._manual_shelf(config)
        self.assertEqual(manual.get('grill'), ['steak_bowl'])

    def test_no_record_keeps_old_behaviour(self):
        """没有生成记录时（首次刷新前用户就填好了）仍按手动处理。"""
        config = FakeConfig(self._config_with_shelf({'grill': ['double_energy']}))
        self.assertEqual(refresh._manual_shelf(config), {'grill': ['double_energy']})

    def test_refresh_records_its_own_shelf(self):
        """端到端：刷新写出的 Product1-5 不会再被自己当成手动配置。"""
        config = FakeConfig({
            'IslandPlan.IslandPlan.RefreshPlan': True,
            'IslandPlan.IslandPlan.Season': 'autumn',
            'IslandPlan.IslandPlan.PlanVerifiedOnly': False,
            'IslandPlan.IslandPlan.PlanMineVerified': False,
            'IslandPlan.IslandPlan.PlanShelfSlots': 4,
        })
        refresh.refresh_plan_if_requested(config)
        self.assertTrue(refresh.load_generated())
        self.assertEqual(refresh._manual_shelf(config), {})


if __name__ == '__main__':
    unittest.main()
