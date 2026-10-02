"""战术学院添加学员的等级筛选回归，构造内存实例，不读取实例配置或连接设备。"""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.retire.dock import CARD_GRIDS
from module.tactical.tactical_class import RewardTacticalClass


def vessel(min_level, max_level, levels):
    """构造一个只带等级筛选所需依赖的 RewardTacticalClass 实例。"""
    instance = object.__new__(RewardTacticalClass)
    instance.config = SimpleNamespace(
        AddNewStudent_Enable=True,
        AddNewStudent_Favorite=False,
        AddNewStudent_MinLevel=min_level,
        AddNewStudent_MaxLevel=max_level,
    )
    instance.device = SimpleNamespace(image=object(), click=Mock())
    instance.dock_filter = SimpleNamespace(settings=[])
    instance.dock_select_index = 0
    instance.dock_favourite_set = Mock()
    instance.dock_filter_set = Mock()
    instance.dock_select_one = Mock()
    instance.dock_select_confirm = Mock()
    instance.interval_clear = Mock()
    instance.appear = Mock(return_value=False)
    instance.loop = Mock(return_value=iter([None]))
    return instance


def select(min_level, max_level, levels):
    """跑一次选船，返回被选中的卡片索引（未选中返回 None）。"""
    instance = vessel(min_level, max_level, levels)
    with patch('module.tactical.tactical_class.LevelOcr') as ocr:
        ocr.return_value.ocr.return_value = levels
        selected = instance.select_suitable_ship()
    if not selected:
        return None
    button = instance.dock_select_one.call_args[0][0]
    return CARD_GRIDS.buttons.index(button)


class TestLevelLimits(unittest.TestCase):
    def test_min_only(self):
        self.assertEqual(RewardTacticalClass._level_limits(50, 0), (50, 0))

    def test_max_only(self):
        self.assertEqual(RewardTacticalClass._level_limits(0, 60), (0, 60))

    def test_both_disabled(self):
        self.assertEqual(RewardTacticalClass._level_limits(0, 0), (0, 0))

    def test_same_level_is_not_conflict(self):
        self.assertEqual(RewardTacticalClass._level_limits(60, 60), (60, 60))

    def test_conflict_disables_both(self):
        self.assertEqual(RewardTacticalClass._level_limits(80, 60), (0, 0))

    def test_invalid_values_disable(self):
        self.assertEqual(RewardTacticalClass._level_limits('50', 'abc'), (50, 0))

    def test_negative_values_disable(self):
        self.assertEqual(RewardTacticalClass._level_limits(-5, -1), (0, 0))


class TestSelectSuitableShip(unittest.TestCase):
    def test_min_level_only(self):
        self.assertEqual(select(50, 0, [30, 60, 80]), 1)

    def test_max_level_only(self):
        self.assertEqual(select(0, 60, [70, 45, 30]), 1)

    def test_level_range(self):
        self.assertEqual(select(40, 60, [70, 30, 50]), 2)

    def test_conflict_falls_back_to_any_ship(self):
        # 最低 80 高于最高 60，两者按 0（关闭）处理，于是选中第一艘舰船
        self.assertEqual(select(80, 60, [5, 70]), 0)

    def test_empty_slots_are_skipped(self):
        self.assertEqual(select(1, 125, [0, 0, 20]), 2)

    def test_no_ship_in_range(self):
        self.assertIsNone(select(70, 80, [10, 20, 30]))


if __name__ == '__main__':
    unittest.main()
