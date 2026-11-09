"""赛季页就地提交（储备模块）必须「在读到卡片的那一屏就地点击」（Add by MHY）。

历史坑：旧实现是读完退出赛季页后再按读取阶段记录的 row/col/offset 点绝对坐标，
点击全部落在岛屿主页上——真机 10-01 的 111 次、10-02 的 41 次零效果。
当前提交逻辑作为储备保留在 island_season_submit，这里只守住它的判定规则。
"""
import sys
import unittest

sys.path.insert(0, '.')

from module.island.island_season_submit import SeasonSubmitMixin


class FakeTask(SeasonSubmitMixin):
    def __init__(self, enabled=True):
        self.submit_enabled = enabled
        self._submitted = set()
        self.clicks = []

    def _submit_card(self, name, info):
        self.clicks.append(name)
        return True


def make_card(task='营养组合', claimed=False, have=100, need=100):
    return {'task': task, 'item': 'carrot_omelette', 'have': have, 'need': need,
            'claimed': claimed, 'row': 0, 'col': 0, 'offset': 0}


class TestSubmitOnScreen(unittest.TestCase):

    def test_clicks_ready_card(self):
        task = FakeTask()
        task._submit_on_screen([make_card()])
        self.assertEqual(task.clicks, ['营养组合'])

    def test_skips_unknown_state(self):
        task = FakeTask()
        task._submit_on_screen([make_card(claimed=None)])
        self.assertEqual(task.clicks, [])

    def test_skips_already_claimed(self):
        task = FakeTask()
        task._submit_on_screen([make_card(claimed=True)])
        self.assertEqual(task.clicks, [])

    def test_skips_not_reached(self):
        task = FakeTask()
        task._submit_on_screen([make_card(have=99)])
        self.assertEqual(task.clicks, [])

    def test_skips_card_without_task(self):
        task = FakeTask()
        task._submit_on_screen([make_card(task=None)])
        self.assertEqual(task.clicks, [])

    def test_clicks_once_per_task(self):
        task = FakeTask()
        task._submit_on_screen([make_card()])
        task._submit_on_screen([make_card()])
        self.assertEqual(task.clicks, ['营养组合'])

    def test_disabled_switch_does_nothing(self):
        task = FakeTask(enabled=False)
        task._submit_on_screen([make_card()])
        self.assertEqual(task.clicks, [])


if __name__ == '__main__':
    unittest.main()
