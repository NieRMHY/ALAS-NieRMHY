"""开发季「累计交付岛屿订单」里程碑（Add by MHY）。

真机抓图确认这 6 项与赛季任务同页显示、通常早已全部领取。原先读取器不认识它们，
那一屏被判成「0 个新任务」，连续三屏就触发 EMPTY_LIMIT「判定到底」提前收工。

关键约束：它们没有对应物品（item=None），不能影响排产目标、库存计算与常驻餐品轮换。
"""
import os
import sys
import unittest

sys.path.insert(0, '.')

from module.island.island_away_cook import season_items_for_shop
from module.island.island_season_plan_data import (
    ORDER_MILESTONES,
    cn_name,
    plan_tasks,
    submit_priority,
    task_of_item,
)
from module.island.island_season_plan_reader import match_task


class TestOrderMilestonesInTaskTable(unittest.TestCase):

    def test_listed_for_every_season(self):
        """与季节无关：四季都要能匹配到，否则换季又会漏读那一屏。"""
        for season in ('spring', 'summer', 'autumn', 'winter'):
            names = [name for name, _, _ in plan_tasks(season)]
            for name, _, _ in ORDER_MILESTONES:
                self.assertIn(name, names, f'{season} 缺少 {name}')

    def test_names_matchable(self):
        """读取器按任务名匹配，这 6 个名字必须能映射回来。"""
        for name, _, need in ORDER_MILESTONES:
            task, item, got_need = match_task(name, 'autumn')
            self.assertEqual(task, name)
            self.assertIsNone(item)
            self.assertEqual(got_need, need)

    def test_do_not_leak_into_item_queries(self):
        """item=None 不能污染按物品反查与店铺赛季物品列表。"""
        self.assertEqual(task_of_item(None, 'autumn'), (None, 0))
        self.assertEqual(cn_name(None), '')
        for shop in ('restaurant', 'teahouse', 'juu_eatery', 'grill', 'juu_coffee'):
            for item, _, _ in season_items_for_shop(shop, 'autumn'):
                self.assertIsNotNone(item, f'{shop} 的赛季物品列表混入了 None')

    def test_submit_priority_skips_them(self):
        """订单里程碑没有物品，按仓库排优先级时应被跳过。"""
        rows = submit_priority('autumn', {'wheat': 500}, producible=None)
        self.assertTrue(all(row[1] is not None for row in rows))


if __name__ == '__main__':
    unittest.main()
