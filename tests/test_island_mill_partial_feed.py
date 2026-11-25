"""原料不够整批时，饲料只补到派遣门槛的离线测试。

库存取自国际服实例 2026-11-08 02:31 的牧场日志：小麦 218、牧草 146，
鸡饲料 14、牛饲料 46、羊饲料 44。原逻辑固定加工 11 组（需 330 原料），
三种饲料全部放弃，鸡饲料停在 14 < 50，养鸡岗位一直空闲。
"""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from module.island.island_rancher import IslandRancher


class StubRancher:
    feed_groups_to_target = IslandRancher.feed_groups_to_target
    feed_groups_to_threshold = IslandRancher.feed_groups_to_threshold
    check_mill_supplement_needs = IslandRancher.check_mill_supplement_needs

    def is_ranch_post_enabled(self, post_id):
        return True
    process_mill_item_with_inventory = IslandRancher.process_mill_item_with_inventory
    mill_material_needed = staticmethod(IslandRancher.mill_material_needed)
    mill_output_quantity = staticmethod(IslandRancher.mill_output_quantity)

    def __init__(self, farm, mill, continuous=False):
        self.inventory_counts = {'farm': dict(farm), 'mill': dict(mill), 'ranch': {}}
        self.continuous_breeding = continuous
        self.ranch_feed_map = {
            'ISLAND_RANCH_POST1': 'chicken_feed',
            'ISLAND_RANCH_POST2': 'pig_feed',
            'ISLAND_RANCH_POST3': 'cattle_feed',
            'ISLAND_RANCH_POST4': 'sheep_feed',
        }
        self.name_to_config = {
            'chicken_feed': {'required_material': 'wheat', 'number': 11},
            'pig_feed': {'required_material': 'corn', 'number': 11},
            'cattle_feed': {'required_material': 'pasture', 'number': 11},
            'sheep_feed': {'required_material': 'pasture', 'number': 11},
            'wheat_flour': {'required_material': 'wheat', 'number': 55},
        }
        self.processed = []

    def process_mill_item(self, mill_item, quantity=None):
        self.processed.append((mill_item, quantity))
        return True

    @staticmethod
    def _item_cn(name):
        return name

    def supplement(self, needs, target=50):
        """与 process_mill_supplements 的加工循环相同（省去页面导航）。"""
        for mill_item, quantity in needs:
            fallback = self.feed_groups_to_target(mill_item, quantity, target)
            self.process_mill_item_with_inventory(mill_item, quantity, fallback_quantity=fallback)


class PartialFeedTest(unittest.TestCase):
    def test_short_materials_make_feed_up_to_dispatch_threshold(self):
        stub = StubRancher(
            farm={'wheat': 218, 'pasture': 146, 'corn': 1070},
            mill={'chicken_feed': 14, 'cattle_feed': 46, 'sheep_feed': 44},
        )
        stub.supplement([('chicken_feed', 11), ('cattle_feed', 11), ('sheep_feed', 11)])

        self.assertEqual(stub.processed, [('chicken_feed', 4), ('cattle_feed', 1), ('sheep_feed', 1)])
        self.assertEqual(stub.inventory_counts['mill'], {'chicken_feed': 54, 'cattle_feed': 56, 'sheep_feed': 54})
        self.assertEqual(stub.inventory_counts['farm']['wheat'], 218 - 120)
        self.assertEqual(stub.inventory_counts['farm']['pasture'], 146 - 60)

    def test_enough_materials_keep_full_batch(self):
        stub = StubRancher(farm={'wheat': 1000}, mill={'chicken_feed': 14})
        stub.supplement([('chicken_feed', 11)])
        self.assertEqual(stub.processed, [('chicken_feed', 11)])

    def test_too_little_even_for_threshold_skips(self):
        stub = StubRancher(farm={'wheat': 100}, mill={'chicken_feed': 0})
        stub.supplement([('chicken_feed', 11)])
        self.assertEqual(stub.processed, [])

    # Add by MHY, 未知、空库存与原料不足在实际补货入口保持不同语义。
    def test_unknown_feed_never_becomes_partial_batch(self):
        for mill in ({}, {'chicken_feed': None}):
            with self.subTest(mill=mill):
                stub = StubRancher(farm={'wheat': 218}, mill=mill)
                self.assertEqual(stub.check_mill_supplement_needs(), [])
                stub.supplement([('chicken_feed', 11)])
                self.assertEqual(stub.processed, [])
                self.assertEqual(stub.inventory_counts['farm']['wheat'], 218)

    def test_confirmed_zero_can_reach_dispatch_threshold(self):
        stub = StubRancher(farm={'wheat': 150}, mill={'chicken_feed': 0})
        stub.supplement([('chicken_feed', 11)])
        self.assertEqual(stub.processed, [('chicken_feed', 5)])
        self.assertEqual(stub.inventory_counts['mill']['chicken_feed'], 50)
        self.assertEqual(stub.inventory_counts['farm']['wheat'], 0)

    def test_unknown_material_remains_unknown_after_confirmed_purchase(self):
        stub = StubRancher(farm={'wheat': None}, mill={'chicken_feed': 14})
        stub.supplement([('chicken_feed', 11)])
        self.assertEqual(stub.processed, [('chicken_feed', 11)])
        self.assertIsNone(stub.inventory_counts['farm']['wheat'])
        self.assertEqual(stub.inventory_counts['mill']['chicken_feed'], 124)

    def test_warehouse_reading_keeps_failed_feed_and_material_unknown(self):
        stub = SimpleNamespace(
            INVENTORY_CONFIG={
                'mill': {'items': [{'name': 'chicken_feed', 'template': 'feed'}]},
                'ranch': {'items': []},
                'farm': {'items': [{'name': 'wheat', 'template': 'wheat'}]},
            },
            inventory_counts={},
            warehouse_filter=Mock(),
            device=SimpleNamespace(screenshot=Mock(return_value='image')),
            ocr_item_quantity=Mock(side_effect=lambda image, template, strict=False: None if strict else 0),
            _item_cn=lambda name: name,
        )
        IslandRancher.warehouse_mill_ranch(stub)
        self.assertIsNone(stub.inventory_counts['mill']['chicken_feed'])
        self.assertIsNone(stub.inventory_counts['farm']['wheat'])

    def test_flour_never_partial(self):
        stub = StubRancher(farm={'wheat': 218}, mill={'wheat_flour': 0})
        stub.supplement([('wheat_flour', 200)])
        self.assertEqual(stub.processed, [])
        self.assertEqual(stub.inventory_counts['farm']['wheat'], 218)

    # Add by MHY, 持续养殖按缺口补料：只补到派遣门槛，不再固定压 11 组库存。
    def test_continuous_mode_crafts_only_missing_groups(self):
        stub = StubRancher(farm={'wheat': 1000}, mill={'chicken_feed': 14}, continuous=True)
        self.assertEqual(stub.check_mill_supplement_needs(), [('chicken_feed', 4)])
        stub.supplement(stub.check_mill_supplement_needs())
        self.assertEqual(stub.processed, [('chicken_feed', 4)])
        self.assertEqual(stub.inventory_counts['mill']['chicken_feed'], 54)
        self.assertEqual(stub.inventory_counts['farm']['wheat'], 1000 - 120)

    def test_continuous_mode_one_group_near_threshold(self):
        stub = StubRancher(farm={'wheat': 1000}, mill={'chicken_feed': 49}, continuous=True)
        self.assertEqual(stub.check_mill_supplement_needs(), [('chicken_feed', 1)])
        stub.supplement(stub.check_mill_supplement_needs())
        self.assertEqual(stub.inventory_counts['mill']['chicken_feed'], 59)

    def test_continuous_mode_zero_feed_uses_five_groups(self):
        stub = StubRancher(farm={'wheat': 150}, mill={'chicken_feed': 0}, continuous=True)
        self.assertEqual(stub.check_mill_supplement_needs(), [('chicken_feed', 5)])
        stub.supplement(stub.check_mill_supplement_needs())
        self.assertEqual(stub.inventory_counts['mill']['chicken_feed'], 50)
        self.assertEqual(stub.inventory_counts['farm']['wheat'], 0)

    def test_continuous_mode_unknown_feed_still_waits(self):
        for mill in ({}, {'chicken_feed': None}):
            with self.subTest(mill=mill):
                stub = StubRancher(farm={'wheat': 1000}, mill=mill, continuous=True)
                self.assertEqual(stub.check_mill_supplement_needs(), [])

    def test_legacy_mode_keeps_fixed_batch(self):
        stub = StubRancher(farm={'wheat': 1000}, mill={'chicken_feed': 14})
        self.assertEqual(stub.check_mill_supplement_needs(), [('chicken_feed', 11)])


if __name__ == "__main__":
    unittest.main()
