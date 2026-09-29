"""赛季页读取的端到端测试（Add by MHY）。

用假 OCR + 假设备把 read_season_plan_page 完整跑一遍：函数里的变量作用域写错、
方法内 import 写错，只有真跑才会暴露。真机踩过两次：
- module.config.time_source 里没有 current_time → ImportError
- 聚合结果时引用了 _read_screen 的局部变量 offset → NameError，
  每轮崩一次 → 触发重启游戏 + 报警邮件（20 多分钟一封）
"""
import sys
import unittest

import numpy as np

sys.path.insert(0, '.')

from module.island.island_season_plan_reader import (
    PLAN_TAB_INDEX,
    TAB_CENTERS,
    TAB_Y,
    read_season_plan_page,
)


class FakeDevice:
    def __init__(self, image):
        self.image = image
        self.clicks = []

    def stuck_record_clear(self):
        pass

    def screenshot(self):
        return self.image

    def sleep(self, seconds=0):
        pass

    def click_minitouch(self, x, y):
        self.clicks.append((x, y))

    def drag(self, *args, **kwargs):
        pass


class FakeIsland:
    """只实现读取页面所需的最小接口。"""

    def __init__(self, image):
        self.device = FakeDevice(image)
        self.assets = object()

    def ui_goto(self, page, get_ship=True):
        pass

    def loop(self, timeout=0):
        return [None]

    def appear(self, button, offset=0):
        return True

    def appear_then_click(self, button, interval=2):
        return False


def make_image():
    """黑底图 + 把「开发计划」页签涂白，让 ensure_bottom_tab 一次通过。"""
    image = np.zeros((720, 1280, 3), dtype=np.uint8)
    cx = TAB_CENTERS[PLAN_TAB_INDEX - 1]
    image[TAB_Y - 12:TAB_Y + 12, cx - 60:cx + 60] = 255
    return image


def make_ocr(name='甜蜜引擎', progress='5/250', badge=''):
    """假 OCR：按区域高度区分名字框（32）和徽章框（60）。"""

    def ocr(image, area, lang):
        if lang == 'azur_lane':
            return progress
        return badge if area[3] - area[1] > 45 else name

    return ocr


class TestReadSeasonPlanPage(unittest.TestCase):
    def test_reads_card_and_keeps_offset(self):
        """卡片要带出 row/col/offset：提交时按这些坐标点按钮"""
        island = FakeIsland(make_image())
        result = read_season_plan_page(island, 'autumn', max_scrolls=1, ocr=make_ocr())
        self.assertIn('甜蜜引擎', result)
        card = result['甜蜜引擎']
        self.assertEqual((card['have'], card['need']), (5, 250))
        self.assertFalse(card['claimed'])
        self.assertIsInstance(card['offset'], int)
        self.assertIsInstance(card['row'], int)
        self.assertIsInstance(card['col'], int)

    def test_claimed_card_is_marked(self):
        """徽章读到「已领取」时 claimed 为真"""
        island = FakeIsland(make_image())
        result = read_season_plan_page(island, 'autumn', max_scrolls=1,
                                       ocr=make_ocr(name='麦田守望', progress='500/500',
                                                    badge='已领取'))
        self.assertTrue(result['麦田守望']['claimed'])

    def test_no_cards_returns_empty(self):
        """读不到任务时返回空字典，不抛异常"""
        island = FakeIsland(make_image())
        result = read_season_plan_page(island, 'autumn', max_scrolls=1,
                                       ocr=make_ocr(name='无关文字'))
        self.assertEqual(result, {})


if __name__ == '__main__':
    unittest.main()
