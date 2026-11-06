"""按作物设置的农田补种目标：解析配置文本与计算补种顺序。"""

import unittest

from module.island.farm_targets import (
    crop_target,
    format_crop_targets,
    parse_crop_targets,
    plan_crops_to_restock,
)

FARM_CROPS = ['wheat', 'corn', 'rice', 'chinese_cabbage', 'potato', 'soybean', 'pasture', 'coffee_bean']


class ParseCropTargetsTest(unittest.TestCase):
    def test_empty_values(self):
        self.assertEqual(parse_crop_targets(None), {})
        self.assertEqual(parse_crop_targets(''), {})

    def test_lines_and_separators(self):
        text = 'corn: 200\nWheat : 80, chinese cabbage=40；coffee-bean：10\n# 注释\n'
        self.assertEqual(
            parse_crop_targets(text, known_crops=FARM_CROPS),
            {'corn': 200, 'wheat': 80, 'chinese_cabbage': 40, 'coffee_bean': 10},
        )

    def test_unknown_and_malformed_entries_are_skipped(self):
        text = 'corn: 200\napple: 50\npotato: lots\n: 5'
        self.assertEqual(parse_crop_targets(text, known_crops=FARM_CROPS), {'corn': 200})

    def test_round_trip(self):
        targets = {'wheat': 80, 'corn': 200}
        self.assertEqual(format_crop_targets(targets), 'corn: 200\nwheat: 80')
        self.assertEqual(parse_crop_targets(format_crop_targets(targets)), targets)


class PlanCropsToRestockTest(unittest.TestCase):
    def test_without_targets_matches_area_threshold(self):
        inventory = {'wheat': 700, 'corn': 100, 'rice': 300}
        self.assertEqual(plan_crops_to_restock(inventory, {}, 660), ['corn', 'rice'])

    def test_per_crop_targets_override_threshold(self):
        inventory = {'wheat': 700, 'corn': 100, 'rice': 300}
        targets = {'wheat': 1000, 'corn': 50}
        self.assertEqual(crop_target('corn', targets, 660), 50)
        self.assertEqual(crop_target('rice', targets, 660), 660)
        # 小麦 70%、水稻 45%，玉米已达自己的目标
        self.assertEqual(plan_crops_to_restock(inventory, targets, 660), ['rice', 'wheat'])

    def test_zero_target_never_restocks(self):
        inventory = {'rubber': 0, 'apple': 10}
        self.assertEqual(plan_crops_to_restock(inventory, {'rubber': 0}, 300), ['apple'])

    def test_skip_and_tie_break(self):
        inventory = {'carrot': 20, 'onion': 10, 'pineapple': 0}
        targets = {'carrot': 40, 'onion': 20}
        # 胡萝卜与洋葱同为 50%，库存少的洋葱在前；菠萝被忽略
        self.assertEqual(
            plan_crops_to_restock(inventory, targets, 100, skip={'pineapple'}),
            ['onion', 'carrot'],
        )


if __name__ == '__main__':
    unittest.main()
