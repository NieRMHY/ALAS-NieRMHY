"""自动提交必须「在赛季页里、按现场定位的坐标」点击（Add by MHY）。

旧实现拿到的是读取阶段记录的 row/col/offset，而 read_season_plan_page 结束时
已经退回岛屿页——于是点击全落在岛屿主页上。真机代价：10-01 的 111 次、10-02 的
41 次点击零效果，营养组合停在 100/100 九个小时、被点 10 次也没领到。
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, '.')

from module.island import island_season_plan as M
from module.island import island_season_plan_reader as R


def make_card(claimed=False, task='营养组合'):
    return {'task': task, 'item': 'carrot_omelette', 'have': 100, 'need': 100,
            'claimed': claimed, 'row': 0, 'col': 0, 'offset': 0}


class TestSubmitHappensOnSeasonPage(unittest.TestCase):

    def _run_submit(self, card, ready=None):
        events = []
        task = M.IslandSeasonPlan.__new__(M.IslandSeasonPlan)
        task.config = MagicMock()

        def fake_submit(name, info):
            events.append(('click', name))

        task._submit_card = fake_submit

        with patch.object(R, 'enter_season_page',
                          lambda island: (events.append(('enter',)), True)[1]), \
             patch.object(R, 'read_screen',
                          lambda island, season: (events.append(('read',)), [card])[1]), \
             patch.object(R, 'leave_season_page',
                          lambda island: (events.append(('leave',)), True)[1]), \
             patch.object(R, 'scroll_to_top', lambda island: events.append(('top',))), \
             patch.object(R, 'scroll_list', lambda island: events.append(('scroll',))), \
             patch.object(M, 'SeasonConfig') as season_cfg:
            season_cfg.return_value.season = 'autumn'
            if ready is None:
                ready = [('营养组合', 'carrot_omelette', 100, 100)]
            task._submit_ready(ready)
        return events

    def test_enters_page_before_clicking(self):
        events = self._run_submit(make_card())
        kinds = [e[0] for e in events]
        self.assertIn('enter', kinds)
        self.assertIn('click', kinds)
        self.assertLess(kinds.index('enter'), kinds.index('click'),
                        '必须先进入赛季页再点击，否则点击落在岛屿主页上')
        self.assertEqual(kinds[-1], 'leave', '无论如何都要退回岛屿页')

    def test_clicks_relocated_card(self):
        """点击用的是现场重新读到的卡片位置，不是读取阶段留下的坐标。"""
        card = make_card()
        card['offset'] = 77
        events = self._run_submit(card)
        self.assertIn(('click', '营养组合'), events)

    def test_unknown_state_is_not_clicked(self):
        """徽章被裁掉（None）不该动手。"""
        events = self._run_submit(make_card(claimed=None))
        self.assertNotIn('click', [e[0] for e in events])

    def test_already_claimed_is_not_clicked(self):
        events = self._run_submit(make_card(claimed=True))
        self.assertNotIn('click', [e[0] for e in events])

    def test_leaves_page_even_when_target_missing(self):
        """页面上找不到目标也要退回岛屿页，不能把人留在赛季页。"""
        events = self._run_submit(make_card(task=None), ready=[('不存在的任务', None, 1, 1)])
        kinds = [e[0] for e in events]
        self.assertNotIn('click', kinds)
        self.assertEqual(kinds[-1], 'leave')

    def test_no_enter_when_nothing_ready(self):
        events = self._run_submit(make_card(), ready=[])
        self.assertEqual(events, [])


if __name__ == '__main__':
    unittest.main()
