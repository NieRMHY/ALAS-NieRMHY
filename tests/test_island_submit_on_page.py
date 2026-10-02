"""自动提交必须「在读到卡片的那一屏就地点击」（Add by MHY）。

历史坑：旧实现是读完退出赛季页后再按读取阶段记录的 row/col/offset 点绝对坐标，
点击全部落在岛屿主页上——真机 10-01 的 111 次、10-02 的 41 次零效果，营养组合
停在 100/100 九个小时、被点 10 次也没领到。

改成「读完再重新进页面扫描」也不稳：两次扫描的起始滚动位置不同，卡片可能恰好停在
被屏幕下沿裁掉的位置（claimed 为 None），读不出状态就没法点。
"""
import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, '.')

from module.island import island_season_plan as M


def make_task(submit=True):
    task = M.IslandSeasonPlan.__new__(M.IslandSeasonPlan)
    task.config = MagicMock()
    task.config.IslandSeasonPlan_Submit = submit
    task._submitted = set()
    task.clicks = []
    task._submit_card = lambda name, info: task.clicks.append(name) or True
    return task


def make_card(task='营养组合', claimed=False, have=100, need=100):
    return {'task': task, 'item': 'carrot_omelette', 'have': have, 'need': need,
            'claimed': claimed, 'row': 0, 'col': 0, 'offset': 0}


class TestSubmitOnScreen(unittest.TestCase):

    def test_clicks_ready_card(self):
        task = make_task()
        task._submit_on_screen([make_card()])
        self.assertEqual(task.clicks, ['营养组合'])

    def test_skips_unknown_state(self):
        """徽章被屏幕下沿裁掉（None）时状态未知，不动手。"""
        task = make_task()
        task._submit_on_screen([make_card(claimed=None)])
        self.assertEqual(task.clicks, [])

    def test_skips_already_claimed(self):
        task = make_task()
        task._submit_on_screen([make_card(claimed=True)])
        self.assertEqual(task.clicks, [])

    def test_skips_not_reached(self):
        task = make_task()
        task._submit_on_screen([make_card(have=99)])
        self.assertEqual(task.clicks, [])

    def test_skips_card_without_task(self):
        task = make_task()
        task._submit_on_screen([make_card(task=None)])
        self.assertEqual(task.clicks, [])

    def test_clicks_once_per_task(self):
        """同一张卡在多屏重复读到，只点一次。"""
        task = make_task()
        task._submit_on_screen([make_card()])
        task._submit_on_screen([make_card()])
        self.assertEqual(task.clicks, ['营养组合'])

    def test_disabled_switch_does_nothing(self):
        task = make_task(submit=False)
        task._submit_on_screen([make_card()])
        self.assertEqual(task.clicks, [])


class TestReadPassInvokesCallback(unittest.TestCase):
    """读取器每读完一屏要回调一次——提交靠它拿到现场坐标。"""

    def test_on_cards_called_per_screen(self):
        from test_island_season_plan_page import FakeIsland, make_image, make_ocr
        from module.island.island_season_plan_reader import read_season_plan_page

        seen = []
        island = FakeIsland(make_image())
        read_season_plan_page(island, 'autumn', max_scrolls=2, ocr=make_ocr(),
                              on_cards=seen.append)
        self.assertTrue(seen, '每读完一屏都应回调一次')
        self.assertTrue(any(c.get('task') for cards in seen for c in cards))

    def test_callback_optional(self):
        from test_island_season_plan_page import FakeIsland, make_image, make_ocr
        from module.island.island_season_plan_reader import read_season_plan_page

        island = FakeIsland(make_image())
        result = read_season_plan_page(island, 'autumn', max_scrolls=1, ocr=make_ocr())
        self.assertIn('甜蜜引擎', result)


if __name__ == '__main__':
    unittest.main()
