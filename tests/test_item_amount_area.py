"""获得道具页「按物品换数量区」的规则。

作战补给凭证需保留完整的四、五位数；白纸类图纸/实验计划需避开下衬。
裁剪规则与逐位字形匹配共同排除图标干扰，不能靠窄区或截断修正数量。
"""
import unittest

from module.azur_stats.image.get_items import AutoSearchAmount, GetItems
from module.statistics.item import ItemGrid

DEFAULT_AREA = GetItems.ITEM_AMOUNT_AREA


class TestAmountAreaFor(unittest.TestCase):
    def setUp(self):
        self.grid = ItemGrid(None, {}, template_area=(40, 21, 89, 70), amount_area=DEFAULT_AREA)
        self.grid.amount_area_rules = list(GetItems.ITEM_AMOUNT_AREA_RULES)

    def test_rules_are_empty_by_default(self):
        self.assertEqual(ItemGrid(None, {}).amount_area_rules, [])

    def test_unmatched_item_uses_default_area(self):
        for name in ('PlateGeneralT4', 'High_Durability_Elastomers', 'SpecialItemTokens'):
            self.assertEqual(self.grid.amount_area_for(name), DEFAULT_AREA)

    def test_operation_coin_uses_wider_area(self):
        self.assertEqual(self.grid.amount_area_for('OperationCoin'), (28, 72, 94, 94))

    def test_white_paper_uses_lower_area(self):
        for name in ('GearDesignPlanGunT4', 'GearDesignPlanPlaneT5', 'OrdnanceTestingReportT1'):
            self.assertEqual(self.grid.amount_area_for(name), (50, 76, 94, 94))

    def test_first_matching_rule_wins(self):
        self.grid.amount_area_rules = [('Plate', (1, 2, 3, 4)), ('PlateGun', (5, 6, 7, 8))]
        self.assertEqual(self.grid.amount_area_for('PlateGunT4'), (1, 2, 3, 4))

    def test_amount_ocr_keeps_fragment_filtering(self):
        # 换回不过滤碎片的 AmountOcr 会把材料底衬读成数字（氟橡胶 2 读成 12）
        self.assertTrue(AutoSearchAmount.remove_fragments)
        self.assertGreater(AutoSearchAmount.fragment_min_height, 0)


if __name__ == '__main__':
    unittest.main()
