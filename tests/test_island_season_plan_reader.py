"""赛季开发计划页面读取的纯逻辑测试（离线，注入假 OCR）。"""
import sys
import unittest

sys.path.insert(0, '.')

from module.island.island_season_plan_reader import (
    card_boxes,
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


class TestNormalizeName(unittest.TestCase):
    def test_strip_noise(self):
        self.assertEqual(normalize_name(' 甜蜜 引擎 '), '甜蜜引擎')
        self.assertEqual(normalize_name('拿铁·时光'), '拿铁时光')
        self.assertEqual(normalize_name(None), '')


if __name__ == '__main__':
    unittest.main()
