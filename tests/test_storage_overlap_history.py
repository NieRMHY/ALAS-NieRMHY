"""原生三页回放：只更新已确认重叠的图像，不放宽身份、数量或完整性。"""

from pathlib import Path
import unittest
import cv2

from module.base.utils import load_image
from module.storage.statistics_recognition import (
    StorageCard, StorageCatalog, StorageNoProgressError, StorageRecognitionError, StorageTraversal, same_card, same_row)


class OverlapHistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.samples = load_image(str(Path(__file__).parent / 'fixtures/storage_statistics/live_overlap_chain.png'))

    def row(self, index):
        row = [StorageCard((column * 128, 0, (column + 1) * 128, 128),
                           self.samples[index * 128:(index + 1) * 128,
                                        column * 128:(column + 1) * 128].copy())
               for column in range(7)]
        if index in (0, 1, 3):
            row[4].identifier, row[4].amount = 'CognitiveChips', 8628
            row[5].identifier, row[5].amount = 'CognitiveChipsII', 9657
        elif index in (2, 4):
            row[6].identifier, row[6].amount = 'PlateGeneralT4', 881
        return row

    def test_last_confirmed_image_allows_three_native_pages_without_relaxing_matching(self):
        first, middle, last = [self.row(index) for index in (0, 1, 3)]
        self.assertTrue(same_row(first, middle))
        self.assertTrue(same_row(middle, last))
        # 已确认的身份和数量不受旧心智单元图像的虹彩差异影响。
        self.assertTrue(same_row(first, last))
        traversal = StorageTraversal()
        traversal.append([first])
        traversal.append([middle, self.row(2)])
        traversal.append([last, self.row(4), self.row(5)])
        self.assertEqual(len(traversal.rows), 3)
        self.assertEqual(traversal.pages, 3)
        self.assertIs(traversal.rows[0], last)
        self.assertEqual(traversal.rows[0][4].amount, 8628)

    def test_quantity_change_cannot_refresh_or_extend_confirmed_rows(self):
        traversal = StorageTraversal()
        traversal.append([self.row(0)])
        traversal.append([self.row(1), self.row(2)])
        original = list(traversal.rows)
        changed = self.row(3)
        changed[4].amount += 1
        with self.assertRaises(StorageRecognitionError):
            traversal.append([changed, self.row(4), self.row(5)])
        self.assertEqual(traversal.pages, 2)
        self.assertTrue(all(a is b for a, b in zip(traversal.rows, original)))

    def test_no_progress_cannot_refresh_confirmed_rows(self):
        traversal = StorageTraversal()
        traversal.append([self.row(1), self.row(2)])
        original = list(traversal.rows)
        with self.assertRaises(StorageNoProgressError):
            traversal.append([self.row(4)])
        self.assertEqual(traversal.pages, 1)
        self.assertTrue(all(a is b for a, b in zip(traversal.rows, original)))

    def test_native_rainbow_blueprints_and_counts_remain_distinct(self):
        samples = load_image(str(Path(__file__).parent / 'fixtures/storage_statistics/live_rainbow_overlap.png'))
        rows = [[StorageCard((column * 128, 0, (column + 1) * 128, 128),
                             samples[row * 128:(row + 1) * 128,
                                     column * 128:(column + 1) * 128])
                 for column in range(7)] for row in range(4)]
        before, after = rows[0] + rows[1], rows[2] + rows[3]
        self.assertTrue(same_row(rows[0], rows[2]))
        self.assertTrue(same_row(rows[1], rows[3]))
        # 同主体的 ALL 蓝图也须区分 62/143/142/76，不能仅看共同的边框。
        for i, left in enumerate(before):
            for j, right in enumerate(after):
                with self.subTest(before=i, after=j):
                    self.assertEqual(same_card(left, right), i == j)

    def test_confirmed_template_and_amount_survive_real_overlay_differences(self):
        samples = load_image(str(Path(__file__).parent / 'fixtures/storage_statistics/live_confirmed_item_pairs.png'))
        for start, identifier, amount in [(0, 'SecretDesignPlanT5', 1), (2, 'SecretDesignPlanT4', 767)]:
            first, second = [StorageCard((0, 0, 128, 128), samples[:, index * 128:(index + 1) * 128].copy(),
                                         identifier=identifier, amount=amount)
                             for index in (start, start + 1)]
            with self.subTest(identifier=identifier):
                score = cv2.minMaxLoc(cv2.matchTemplate(first.image, second.image[3:125, 3:125],
                                                       cv2.TM_CCOEFF_NORMED))[1]
                self.assertLess(score, .985)
                self.assertTrue(same_card(first, second))
                second.amount += 1
                self.assertFalse(same_card(first, second))
                first.amount = second.amount = None
                self.assertFalse(same_card(first, second))

    def test_strong_rainbow_requires_confirmed_quantity_and_matching_foreground(self):
        samples = load_image(str(Path(__file__).parent / 'fixtures/storage_statistics/live_rainbow_brightness.png'))
        catalog = StorageCatalog()
        rows = []
        for y in range(0, 512, 128):
            row = []
            for x in range(0, 896, 128):
                card = StorageCard((x, y, x + 128, y + 128), samples[y:y + 128, x:x + 128].copy())
                try:
                    card.comparison_amount = catalog.read_amount(card.image)
                except StorageRecognitionError:
                    pass
                row.append(card)
            rows.append(row)
        before, after = rows[0] + rows[1], rows[2] + rows[3]
        for i, left in enumerate(before):
            for j, right in enumerate(after):
                with self.subTest(before=i, after=j):
                    self.assertEqual(same_card(left, right), i == j)
        # 第二格必须依赖完整数量；既不能强取未知数量，也不能忽略数量变化。
        self.assertEqual(before[1].comparison_amount, 215)
        self.assertEqual(after[1].comparison_amount, 215)
        after[1].comparison_amount = None
        self.assertFalse(same_card(before[1], after[1]))
        after[1].comparison_amount = 216
        self.assertFalse(same_card(before[1], after[1]))


if __name__ == '__main__':
    unittest.main()
