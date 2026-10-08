"""舰队准备阶段的回归测试（困难图推荐配队、跳过编队检测时的按钮校准）。

全程内存操作，不读取实例配置，也不连接设备。
"""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from module.config import server as server_module
from module.exception import HardNotSatisfied
from module.handler.assets import AUTO_SEARCH_SET_ALL, AUTO_SEARCH_SET_BOSS, \
    AUTO_SEARCH_SET_MOB, AUTO_SEARCH_SET_STANDBY
from module.map import map_fleet_preparation
from module.map.assets import FLEET_1_CLEAR, RECOMMEND_A, RECOMMEND_B, RECOMMEND_C
from module.map.map_fleet_preparation import FleetPreparation
from tests.test_farming_combat_config import make_config


class FakeFleetOperator:
    """舰队槽位操作器替身，只保留舰队准备流程用到的接口。"""

    def __init__(self, name, satisfied=True, allow=True):
        self.name = name
        self.satisfied = satisfied
        self._allow = allow
        self.clear = Mock()
        self.ensure_to_be = Mock()

    def __str__(self):
        return f'FLEET_{self.name}_CLEAR'

    def allow(self):
        return self._allow

    def is_hard_satisfied(self):
        return self.satisfied

    def raise_hard_not_satisfied(self):
        if self.satisfied is False:
            raise HardNotSatisfied


def prepare(use_recommend=True, satisfied=(True, True, True), allow=(True, True, True)):
    """构造只带真实配置绑定的 FleetPreparation 实例。

    Returns:
        tuple[FleetPreparation, dict[str, FakeFleetOperator]]: 实例与按槽位名索引的替身舰队。
    """
    config = make_config('WarArchives', Campaign={'UseRecommendFleet': use_recommend})
    config.override(
        Fleet_Fleet1=1, Fleet_Fleet2=2, Submarine_Fleet=0,
        Fleet_FleetOrder='fleet1_all_fleet2_standby', Fleet_SkipPreparation=False,
    )
    operators = {
        '1': FakeFleetOperator('1', satisfied=satisfied[0], allow=allow[0]),
        '2': FakeFleetOperator('2', satisfied=satisfied[1], allow=allow[1]),
        '3': FakeFleetOperator('3', satisfied=satisfied[2], allow=allow[2]),
    }
    instance = object.__new__(FleetPreparation)
    instance.config = config
    instance.device = SimpleNamespace(click=Mock(), screenshot=Mock(), sleep=Mock())
    instance.appear = Mock(return_value=False)
    instance.appear_then_click = Mock(return_value=True)
    instance.handle_popup_confirm = Mock(return_value=False)
    instance.map_fleet_checked = False
    instance.map_is_hard_mode = False
    return instance, operators


def build_operators(operators):
    """按槽位名把 FleetOperator 的 clear 按钮映射到替身。"""
    mapping = {
        'FLEET_1_CLEAR': operators['1'],
        'FLEET_2_CLEAR': operators['2'],
        'SUBMARINE_CLEAR': operators['3'],
    }
    return lambda **kwargs: mapping[str(kwargs['clear'])]


class RecommendFleetTests(unittest.TestCase):
    def setUp(self):
        # 困难限制校验只在 cn/en/jp 生效，固定全局服务器避免受其他测试影响
        self._server = server_module.server
        server_module.server = 'cn'

    def tearDown(self):
        server_module.server = self._server

    def test_recommend_fleet_fills_unsatisfied_hard_fleet(self):
        """自动配队开启时点击推荐，复查通过后不再误报需要人工准备舰队。"""
        instance, operators = prepare(satisfied=(False, True, True), allow=(True, True, False))

        def recommend(button, **kwargs):
            operators['1'].satisfied = True
            return True

        instance.appear_then_click = Mock(side_effect=recommend)
        with patch.object(map_fleet_preparation, 'FleetOperator', side_effect=build_operators(operators)):
            self.assertFalse(instance.fleet_preparation())

        clicked = [call.args[0] for call in instance.appear_then_click.call_args_list]
        self.assertEqual(clicked, [RECOMMEND_A, RECOMMEND_B])
        self.assertNotIn(RECOMMEND_C, clicked)
        # 潜艇槽位不可用时同步关闭潜艇配置
        self.assertEqual(instance.config.SUBMARINE, 0)

    def test_recommend_fleet_still_escalates_when_recheck_fails(self):
        """推荐后仍不满足困难限制，保留人工介入告警。"""
        instance, operators = prepare(satisfied=(False, True, True), allow=(True, True, True))
        with patch.object(map_fleet_preparation, 'FleetOperator', side_effect=build_operators(operators)):
            with self.assertRaises(HardNotSatisfied):
                instance.fleet_preparation()

        self.assertEqual(instance.appear_then_click.call_count, 2)

    def test_recommend_fleet_clicks_submarine_only_when_configured(self):
        """潜艇槽位有配置时点推荐，否则清空潜艇。"""
        instance, operators = prepare(allow=(True, True, True))
        instance.config.override(Submarine_Fleet=3)
        with patch.object(map_fleet_preparation, 'FleetOperator', side_effect=build_operators(operators)):
            instance.fleet_preparation()

        clicked = [call.args[0] for call in instance.appear_then_click.call_args_list]
        self.assertEqual(clicked, [RECOMMEND_A, RECOMMEND_B, RECOMMEND_C])
        operators['3'].clear.assert_not_called()

        instance, operators = prepare(allow=(True, True, True))
        with patch.object(map_fleet_preparation, 'FleetOperator', side_effect=build_operators(operators)):
            instance.fleet_preparation()

        clicked = [call.args[0] for call in instance.appear_then_click.call_args_list]
        self.assertNotIn(RECOMMEND_C, clicked)
        operators['3'].clear.assert_called()

    def test_disabled_recommend_fleet_keeps_standby_fleet_exempt(self):
        """自动配队关闭时不点推荐，待命舰队的困难限制不参与校验。"""
        instance, operators = prepare(
            use_recommend=False, satisfied=(True, False, True), allow=(True, True, True))
        with patch.object(map_fleet_preparation, 'FleetOperator', side_effect=build_operators(operators)):
            self.assertFalse(instance.fleet_preparation())

        instance.appear_then_click.assert_not_called()


class SkipPreparationTests(unittest.TestCase):
    """跳过编队检测（Fleet_SkipPreparation）时，按钮校准仍须执行。"""

    def test_skip_preparation_still_calibrates_auto_search_buttons(self):
        """提前返回不应跳过 load_offset：自动搜索设置扫描依赖它，缺了就整排扫不到高亮。"""
        config = make_config('WarArchives', Campaign={'UseRecommendFleet': False})
        config.override(
            Fleet_Fleet1=1, Fleet_Fleet2=2, Submarine_Fleet=0, Fleet_SkipPreparation=True)
        instance = object.__new__(FleetPreparation)
        instance.config = config
        instance.device = SimpleNamespace(click=Mock(), screenshot=Mock(), sleep=Mock())
        instance.map_fleet_checked = False
        instance.map_is_hard_mode = False

        def appear(button, offset=(0, 0), **kwargs):
            if button is FLEET_1_CLEAR:
                # 模拟 W15/16 章新布局：清空按钮整体上移 44px
                button._button_offset = tuple(np.array(button._button) + (0, -44, 0, -44))
                return True
            return False

        instance.appear = Mock(side_effect=appear)

        try:
            self.assertTrue(instance.fleet_preparation())
            # 跳过编队本身不点击界面
            instance.device.click.assert_not_called()
            # 四个舰队分工按钮必须已按清空按钮的实测位移校准
            for button in (AUTO_SEARCH_SET_MOB, AUTO_SEARCH_SET_BOSS,
                           AUTO_SEARCH_SET_ALL, AUTO_SEARCH_SET_STANDBY):
                self.assertEqual(button.button[1], button.area[1] - 44)
        finally:
            FLEET_1_CLEAR.clear_offset()
            for button in (AUTO_SEARCH_SET_MOB, AUTO_SEARCH_SET_BOSS,
                           AUTO_SEARCH_SET_ALL, AUTO_SEARCH_SET_STANDBY):
                button.clear_offset()


if __name__ == '__main__':
    unittest.main()
