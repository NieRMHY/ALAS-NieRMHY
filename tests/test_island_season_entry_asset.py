"""赛季入口按钮资源回归（纯离线）。

Add by MHY, 2026-10-10：入口 ISLAND_SEASON_ENTRY 的模板是 56x54 的局部裁剪，
button_extract 把它的检测区域生成成了左上角 (0, 0, 56, 54)，真机从 10-02 起再也进不去
开发季页面，赛季页快照停更十天。模板必须是 1280x720 整屏图，区域才会落在真实位置。
"""
import sys
import unittest

sys.path.insert(0, '.')

import numpy as np
from PIL import Image

FIXTURE = 'tests/fixtures/island_season_plan/island_home_autumn.png'
TEMPLATE = 'assets/cn/island_season_plan/ISLAND_SEASON_ENTRY.png'


class TestIslandSeasonEntryAsset(unittest.TestCase):
    def test_template_is_full_screen(self):
        self.assertEqual(Image.open(TEMPLATE).size, (1280, 720))

    def test_area_is_on_top_right_icon_row(self):
        from module.island_season_plan.assets import ISLAND_SEASON_ENTRY
        x1, y1, x2, y2 = ISLAND_SEASON_ENTRY.area
        self.assertGreater(x1, 900)
        self.assertLess(y2, 100)

    def test_matches_live_island_home_screenshot(self):
        from module.island_season_plan.assets import ISLAND_SEASON_ENTRY
        image = np.array(Image.open(FIXTURE).convert('RGB'))
        self.assertTrue(ISLAND_SEASON_ENTRY.match(image, offset=30))
        self.assertTrue(ISLAND_SEASON_ENTRY.appear_on(image, threshold=30))

    def test_does_not_match_unrelated_corner(self):
        from module.island_season_plan.assets import ISLAND_SEASON_ENTRY
        image = np.array(Image.open(FIXTURE).convert('RGB'))
        image[0:120, 880:1000] = 120
        self.assertFalse(ISLAND_SEASON_ENTRY.match(image, offset=30))


if __name__ == '__main__':
    unittest.main()
