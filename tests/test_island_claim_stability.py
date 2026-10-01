"""「已领取」识别的稳定性。

真机 10-01 实测：苹果汁一天被读 32 次，28 次读成 250/250、只有 4 次读到「已领取」，
而截图证明那张卡上「已领取」清清楚楚。两个后果：

  1. done 被反复取消 → 已提交的物品重新投入生产（苹果汁停不下来）
  2. notified 被重置后又读到「未领取」→ 重复发「可以提交」邮件

对策：读取侧同一张卡多屏重复读到时 claimed 取「或」；状态侧单次漏读不取消 done。
"""
import os
import sys
import unittest

sys.path.insert(0, '.')
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from module.island import island_away_cook
from module.island.island_season_plan_reader import read_season_plan_page
from test_island_season_plan_page import FakeIsland, make_image


class TestClaimedMergedAcrossScreens(unittest.TestCase):
    """同一张卡被相邻两屏重复读到：claimed 取「或」，只补漏读。"""

    @staticmethod
    def _island_with_scroll_counter():
        island = FakeIsland(make_image())
        state = {'scrolls': 0}
        original = island.device.drag          # scroll_list 走 device.drag

        def counting_drag(*args, **kwargs):
            state['scrolls'] += 1
            return original(*args, **kwargs)

        island.device.drag = counting_drag
        return island, state

    def test_later_screen_supplies_missing_badge(self):
        island, state = self._island_with_scroll_counter()

        def ocr(image, area, lang):
            if lang == 'azur_lane':
                return '250/250'
            if area[3] - area[1] > 45:
                # 第一屏漏读徽章，滚动一次之后才读到
                return '已领取' if state['scrolls'] >= 1 else ''
            return '甜蜜引擎'

        result = read_season_plan_page(island, 'autumn', max_scrolls=2, ocr=ocr)
        self.assertTrue(result['甜蜜引擎']['claimed'],
                        '第二屏补读到的「已领取」应当被合并进来')

    def test_never_detected_stays_unclaimed(self):
        island, _ = self._island_with_scroll_counter()

        def ocr(image, area, lang):
            if lang == 'azur_lane':
                return '250/250'
            if area[3] - area[1] > 45:
                return ''          # 两屏都漏读
            return '甜蜜引擎'

        result = read_season_plan_page(island, 'autumn', max_scrolls=2, ocr=ocr)
        self.assertFalse(result['甜蜜引擎']['claimed'])


class TestDoneDebounce(unittest.TestCase):
    """单次漏读不取消 done，连续漏读才取消。"""

    @staticmethod
    def _page(claimed):
        return {'甜蜜引擎': {'item': 'apple_juice', 'claimed': claimed}}

    def test_single_miss_keeps_done(self):
        notified = {}
        island_away_cook.mark_claimed('autumn', self._page(True), notified)
        self.assertTrue(notified['autumn']['apple_juice']['done'])

        changed = island_away_cook.mark_claimed('autumn', self._page(False), notified)
        self.assertTrue(notified['autumn']['apple_juice']['done'], '一次漏读不该取消 done')
        self.assertEqual(changed, {})

    def test_consecutive_misses_cancel_done(self):
        notified = {}
        island_away_cook.mark_claimed('autumn', self._page(True), notified)
        island_away_cook.mark_claimed('autumn', self._page(False), notified)
        changed = island_away_cook.mark_claimed('autumn', self._page(False), notified)
        self.assertFalse(notified['autumn']['apple_juice']['done'])
        self.assertEqual(changed.get('apple_juice'), '取消')

    def test_claimed_clears_miss_counter(self):
        notified = {}
        island_away_cook.mark_claimed('autumn', self._page(True), notified)
        island_away_cook.mark_claimed('autumn', self._page(False), notified)
        island_away_cook.mark_claimed('autumn', self._page(True), notified)   # 又读到
        island_away_cook.mark_claimed('autumn', self._page(False), notified)  # 只漏一次
        self.assertTrue(notified['autumn']['apple_juice']['done'])
        self.assertEqual(notified['autumn']['apple_juice']['miss'], 1)

    def test_state_entry_tolerates_missing_miss_field(self):
        """旧状态文件没有 miss 字段时按 0 处理，不炸。"""
        notified = {'autumn': {'apple_juice': {'notified': False, 'last': 0, 'done': True}}}
        island_away_cook.mark_claimed('autumn', self._page(False), notified)
        self.assertTrue(notified['autumn']['apple_juice']['done'])


if __name__ == '__main__':
    unittest.main()
