"""大世界地图格子"点击前对准镜头"的单元测试。

背景：重扫地图会把镜头停在扫描点，此时检测到的事件（明石/塞壬装置/记录塔）
可能落在屏幕边缘，点击区域与四周固定 UI（左下角舰队切换按钮、底部按钮排、
右侧雷达与按钮列、顶部资源栏）重合，点击会被 UI 吃掉而不是落到地图格子上。
2026-09-11 曾出现"点明石点到舰队切换按钮、把舰队列表点开导致任务卡死"的事故。

本测试只覆盖纯逻辑：安全区判定与聚焦决策，不依赖模拟器。
"""

import unittest
from unittest.mock import Mock

from module.os.map import OSMap


class FakeGrid:
    """带 location / button 的最小格子替身。"""

    def __init__(self, location, button):
        self.location = location
        self.button = button

    def __repr__(self):
        return f"Grid{self.location}"


class FakeImage:
    """1280x720 截图替身。"""

    shape = (720, 1280, 3)


def make_os_map():
    """构造绕过 __init__ 的 OSMap 实例，只注入本用例需要的最小属性。"""
    obj = OSMap.__new__(OSMap)
    obj.__dict__["device"] = Mock(image=FakeImage())
    return obj


class TestGridClickSafeArea(unittest.TestCase):
    def test_screen_center_grid_is_safe(self):
        obj = make_os_map()
        grid = FakeGrid((2, 3), (580, 305, 700, 415))

        self.assertTrue(obj._is_grid_in_click_safe_area(grid))

    def test_bottom_left_fleet_button_area_is_unsafe(self):
        # 事故现场：明石格子的点击区域压在左下角"第一舰队"切换按钮上
        obj = make_os_map()
        grid = FakeGrid((1, 4), (254, 575, 374, 685))

        self.assertFalse(obj._is_grid_in_click_safe_area(grid))

    def test_top_resource_bar_area_is_unsafe(self):
        obj = make_os_map()
        grid = FakeGrid((2, 0), (580, 5, 700, 115))

        self.assertFalse(obj._is_grid_in_click_safe_area(grid))

    def test_right_radar_area_is_unsafe(self):
        obj = make_os_map()
        grid = FakeGrid((7, 2), (1040, 240, 1160, 350))

        self.assertFalse(obj._is_grid_in_click_safe_area(grid))

    def test_grid_without_click_area_is_unsafe(self):
        obj = make_os_map()

        self.assertFalse(obj._is_grid_in_click_safe_area(object()))


class TestFocusGridBeforeClick(unittest.TestCase):
    def test_safe_grid_returns_unchanged_without_moving_camera(self):
        obj = make_os_map()
        grid = FakeGrid((2, 3), (580, 305, 700, 415))
        obj.__dict__["focus_to"] = Mock()
        obj.__dict__["convert_local_to_global"] = Mock()

        result = obj._focus_grid_before_click(grid)

        self.assertIs(result, grid)
        obj.focus_to.assert_not_called()
        obj.convert_local_to_global.assert_not_called()

    def test_unsafe_grid_focuses_camera_and_returns_relocated_grid(self):
        obj = make_os_map()
        grid = FakeGrid((1, 4), (254, 575, 374, 685))
        relocated = FakeGrid((1, 4), (580, 305, 700, 415))
        obj.__dict__["focus_to"] = Mock()
        obj.__dict__["convert_local_to_global"] = Mock(
            return_value=FakeGrid((1, 4), (0, 0, 0, 0))
        )
        obj.__dict__["convert_global_to_local"] = Mock(return_value=relocated)

        result = obj._focus_grid_before_click(grid)

        obj.focus_to.assert_called_once_with((1, 4))
        obj.convert_global_to_local.assert_called_once_with((1, 4))
        self.assertIs(result, relocated)

    def test_unsafe_grid_prefers_event_redetected_after_focus(self):
        # 聚焦后优先用重新检测的结果：检测结果自带当前屏幕坐标，不受相机换算偏差影响
        obj = make_os_map()
        grid = FakeGrid((1, 4), (254, 575, 374, 685))
        grid.is_akashi = True
        redetected = FakeGrid((1, 4), (580, 305, 700, 415))
        obj.__dict__["focus_to"] = Mock()
        obj.__dict__["convert_local_to_global"] = Mock(
            return_value=FakeGrid((1, 4), (0, 0, 0, 0))
        )
        obj.__dict__["convert_global_to_local"] = Mock()
        obj.__dict__["view"] = Mock()
        obj.view.select.return_value = [redetected]

        result = obj._focus_grid_before_click(grid)

        obj.view.select.assert_called_once_with(is_akashi=True)
        obj.convert_global_to_local.assert_not_called()
        self.assertIs(result, redetected)

    def test_falls_back_to_conversion_when_redetected_location_differs(self):
        # 重新检测到的同名事件不在目标坐标上（可能是另一个同名事件）时不采信
        obj = make_os_map()
        grid = FakeGrid((1, 4), (254, 575, 374, 685))
        grid.is_akashi = True
        converted = FakeGrid((1, 4), (580, 305, 700, 415))
        obj.__dict__["focus_to"] = Mock()
        obj.__dict__["convert_local_to_global"] = Mock(
            return_value=FakeGrid((1, 4), (0, 0, 0, 0))
        )
        obj.__dict__["convert_global_to_local"] = Mock(return_value=converted)
        obj.__dict__["view"] = Mock()
        obj.view.select.return_value = [FakeGrid((6, 2), (900, 200, 1020, 310))]

        result = obj._focus_grid_before_click(grid)

        self.assertIs(result, converted)

    def test_keeps_original_grid_when_global_location_unavailable(self):
        obj = make_os_map()
        grid = FakeGrid((1, 4), (254, 575, 374, 685))
        obj.__dict__["focus_to"] = Mock()
        obj.__dict__["convert_local_to_global"] = Mock(side_effect=KeyError)

        result = obj._focus_grid_before_click(grid)

        self.assertIs(result, grid)
        obj.focus_to.assert_not_called()

    def test_keeps_original_grid_when_relocated_grid_missing(self):
        obj = make_os_map()
        grid = FakeGrid((1, 4), (254, 575, 374, 685))
        obj.__dict__["focus_to"] = Mock()
        obj.__dict__["convert_local_to_global"] = Mock(
            return_value=FakeGrid((1, 4), (0, 0, 0, 0))
        )
        obj.__dict__["convert_global_to_local"] = Mock(side_effect=KeyError)

        result = obj._focus_grid_before_click(grid)

        self.assertIs(result, grid)


if __name__ == "__main__":
    unittest.main()
