"""赛季开发计划页面读取的纯逻辑测试（离线，注入假 OCR）。"""
import sys
import unittest

sys.path.insert(0, '.')

from module.island.island_season_plan_reader import (
    card_boxes,
    fix_progress,
    match_task,
    normalize_name,
    parse_progress,
    read_cards,
)


class TestParseProgress(unittest.TestCase):
    def test_normal(self):
        self.assertEqual(parse_progress('70/100'), (70, 100))
        self.assertEqual(parse_progress('6 / 250'), (6, 250))
        self.assertEqual(parse_progress('250/250'), (250, 250))

    def test_ocr_noise(self):
        self.assertEqual(parse_progress('70|100'), (70, 100))
        self.assertEqual(parse_progress(' 12/34 '), (12, 34))

    def test_invalid(self):
        for bad in ('', None, 'abc', '100', '/'):
            self.assertIsNone(parse_progress(bad), bad)


class TestMatchTask(unittest.TestCase):
    def test_exact(self):
        self.assertEqual(match_task('甜蜜引擎', 'autumn'), ('甜蜜引擎', 'apple_juice', 250))

    def test_extra_trailing_char(self):
        """cnocr 会多带尾字，模糊匹配要能吸收"""
        self.assertEqual(match_task('烤肉能量家', 'autumn')[0], '烤肉能量')
        self.assertEqual(match_task('营养组合一', 'autumn')[0], '营养组合')

    def test_noise_chars(self):
        self.assertEqual(match_task(' 拿铁时光 ', 'autumn')[0], '拿铁时光')

    def test_unknown(self):
        self.assertEqual(match_task('不存在的任务', 'autumn'), (None, None, 0))
        self.assertEqual(match_task('', 'autumn'), (None, None, 0))


class TestCardBoxes(unittest.TestCase):
    def test_geometry_inside_card(self):
        """名字框与进度框要落在卡片范围内"""
        for row in range(2):
            for col in range(3):
                name, progress = card_boxes(row, col)
                cx1, cx2 = card_boxes.__globals__['CARD_COLUMNS'][col]
                ry1, ry2 = card_boxes.__globals__['CARD_ROWS'][row]
                self.assertGreaterEqual(name[0], cx1)
                self.assertLessEqual(name[2], cx2)
                self.assertGreaterEqual(progress[0], cx1)
                self.assertLessEqual(progress[2], cx2)
                for box in (name, progress):
                    self.assertGreaterEqual(box[1], ry1)
                    self.assertLessEqual(box[3], ry2)


class TestBoxGeometry(unittest.TestCase):
    """区域必须落在卡片范围内。

    CARD_ROWS 是 (上边缘, 下边缘)，取错成 [1]（下边缘）时所有区域会整体下移
    一个卡片高度：徽章区域偏了 361px，永远读不到「已领取」；名字区只在进度锚点
    恰好补偿回来时才对。真机排查了很久，用几何断言钉死。
    """

    def test_name_and_progress_inside_card(self):
        from module.island.island_season_plan_reader import (CARD_COLUMNS, CARD_ROWS,
                                                             card_boxes)

        for row in range(len(CARD_ROWS)):
            top, bottom = CARD_ROWS[row]
            for col in range(len(CARD_COLUMNS)):
                name_box, progress_box = card_boxes(row, col)
                for label, box in (('名字', name_box), ('进度', progress_box)):
                    self.assertGreaterEqual(box[1], top - 20,
                                            f'行{row}列{col} {label}区域越过卡片上边缘')
                    self.assertLessEqual(box[3], bottom + 5,
                                         f'行{row}列{col} {label}区域越过卡片下边缘')

    def test_claim_boxes_inside_card(self):
        from module.island.island_season_plan_reader import (CARD_COLUMNS, CARD_ROWS,
                                                             claim_boxes)

        for row in range(len(CARD_ROWS)):
            top, bottom = CARD_ROWS[row]
            for col in range(len(CARD_COLUMNS)):
                for box in claim_boxes(row, col):
                    self.assertGreaterEqual(box[1], top,
                                            f'行{row}列{col} 徽章区域在卡片上方')
                    # 第二行卡片的「下边缘」是屏幕裁出来的，留 20px 余量；
                    # 取错上下边缘时会偏一个卡片高度（211px），照样能抓到
                    self.assertLessEqual(box[3], bottom + 20,
                                         f'行{row}列{col} 徽章区域越过卡片下边缘')

    def test_row_span_is_row_distance(self):
        """ROW_SPAN 是两行卡片的间距（约 229），不是卡片高度"""
        from module.island.island_season_plan_reader import CARD_ROWS, ROW_SPAN

        self.assertEqual(ROW_SPAN, CARD_ROWS[1][0] - CARD_ROWS[0][0])
        self.assertGreater(ROW_SPAN, 200)


class TestReadCards(unittest.TestCase):
    def _fake_ocr(self, mapping):
        def ocr(image, area, lang):
            return mapping.get((area, lang), '')
        return ocr

    def test_reads_and_maps(self):
        name_box, prog_box = card_boxes(0, 0)
        mapping = {
            (name_box, 'ppocr_v6'): '甜蜜引擎',
            (prog_box, 'azur_lane'): '6/250',
        }
        cards = read_cards(None, self._fake_ocr(mapping), season='autumn')
        self.assertEqual(len(cards), 1)
        card = cards[0]
        self.assertEqual((card['row'], card['col']), (0, 0))
        self.assertEqual(card['have'], 6)
        self.assertEqual(card['need'], 250)
        self.assertEqual(card['task'], '甜蜜引擎')
        self.assertEqual(card['item'], 'apple_juice')

    def test_fills_need_from_season_data(self):
        """进度读不出来时用赛季数据里的需求量兜底"""
        name_box, _ = card_boxes(1, 2)
        mapping = {(name_box, 'ppocr_v6'): '便携快餐'}
        cards = read_cards(None, self._fake_ocr(mapping), season='autumn')
        self.assertEqual(cards[0]['task'], '便携快餐')
        self.assertEqual(cards[0]['item'], 'steak_bowl')
        self.assertEqual(cards[0]['need'], 50)

    def test_skips_blank_cards(self):
        self.assertEqual(read_cards(None, self._fake_ocr({}), season='autumn'), [])

    def test_no_season_keeps_raw(self):
        name_box, prog_box = card_boxes(0, 1)
        mapping = {(name_box, 'ppocr_v6'): '咖啡供应', (prog_box, 'azur_lane'): '5/250'}
        cards = read_cards(None, self._fake_ocr(mapping))
        self.assertIsNone(cards[0]['task'])
        self.assertEqual(cards[0]['name'], '咖啡供应')


class TestFixProgress(unittest.TestCase):
    """真机 10-10 的 OCR 读数：前缀多读一位会让「82/100」变成「282/100」并错发达标邮件。"""

    def test_real_ocr_samples(self):
        samples = [
            ('282/100', 100, (82, 100)),       # 拿铁实际 82
            ('7250/250', 250, (250, 250)),
            ('2150/150', 150, (150, 150)),
            ('760/60', 60, (60, 60)),
            ('210/10', 10, (10, 10)),
            ('25/5', 5, (5, 5)),
            ('500/5500', 500, (500, 500)),     # 需求量多读
            ('100/199', 100, (100, 100)),      # 需求量读错
            ('C1100/109', 100, (100, 100)),
            ('-29/39', 30, (29, 30)),
        ]
        for text, cfg, want in samples:
            with self.subTest(text=text):
                have, need = parse_progress(text)
                self.assertEqual(fix_progress(have, need, cfg), want)

    def test_correct_readings_untouched(self):
        for have, need in ((82, 100), (0, 100), (99, 100), (100, 100), (250, 250), (48, 250)):
            with self.subTest(have=have):
                self.assertEqual(fix_progress(have, need, need), (have, need))

    def test_unknown_need_keeps_raw(self):
        self.assertEqual(fix_progress(282, 100, 0), (282, 100))

    def test_read_cards_applies_fix(self):
        name_box, prog_box = card_boxes(0, 1)
        mapping = {(name_box, 'ppocr_v6'): '拿铁时光', (prog_box, 'azur_lane'): '282/100'}

        def ocr(image, area, lang):
            return mapping.get((area, lang), '')

        cards = read_cards(None, ocr, season='autumn')
        self.assertEqual((cards[0]['have'], cards[0]['need']), (82, 100))


class TestNormalizeName(unittest.TestCase):
    def test_strip_noise(self):
        self.assertEqual(normalize_name(' 甜蜜 引擎 '), '甜蜜引擎')
        self.assertEqual(normalize_name('拿铁·时光'), '拿铁时光')
        self.assertEqual(normalize_name(None), '')


if __name__ == '__main__':
    unittest.main()
