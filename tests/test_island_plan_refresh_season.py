"""方案刷新：赛季进度 -> 各店排产目标（纯逻辑，不需要设备）。"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, '.')

from module.island import island_plan_refresh


class TestSeasonStockpile(unittest.TestCase):
    """赛季进度（仓库读数） -> 各店排产目标。

    真机踩过：方案刷新从不传 stockpile，导致「只在赛季任务里需要、却不在货架
    也不在基础需求里」的物品永远生产不出来（胡萝卜厚蛋烧/拿铁/便携快餐一直是 0）。
    """

    def setUp(self):
        self.module = island_plan_refresh

    def test_collects_gaps_by_shop(self):
        """按「任务需求 + SEASON_BUFFER」排产，不是按需求本身。"""
        buffer = self.module.SEASON_BUFFER
        progress = {
            'carrot_omelette': [0, 100],
            'latte': [5, 100],
            'apple_juice': [250, 250],
            'iced_coffee': [250 + buffer, 250],
        }
        result = self.module.season_stockpile(progress)
        self.assertEqual(result.get('grill'), {'carrot_omelette': 100 + buffer})
        self.assertEqual(result.get('juu_coffee'), {'latte': 100 + buffer})
        self.assertEqual(result.get('teahouse'), {'apple_juice': 250 + buffer},
                         '刚好卡在需求线上还不够，要留出余量')
        self.assertNotIn('iced_coffee', result.get('juu_coffee', {}),
                         '已经到需求+余量就不该再排')

    def test_materials_are_skipped(self):
        """材料类（农田牧场产物）没有对应店铺，交给农田牧场。"""
        self.assertEqual(self.module.season_stockpile({'corn': [0, 500]}), {})

    def test_zero_need_stops_production(self):
        """需求改成 0 就不再排产，用来手动停掉某项。"""
        self.assertEqual(self.module.season_stockpile({'salad': [0, 0]}), {})

    def test_none_progress_returns_empty(self):
        self.assertEqual(self.module.season_stockpile(None), {})

    def test_season_have_feeds_capacity_estimate(self):
        """产能估算要按「还差多少」：仓库已有 248/270 不该按从零做 270 估。

        真机：碳烤肉串就差 22 个却被估成 102 时，远超整店预算 43.2 时而被误判
        「产能不足」整个跳过。
        """
        self.assertEqual(
            self.module.season_have({'carrot_omelette': [86, 100], 'salad': [2100, 100]}),
            {'carrot_omelette': 86, 'salad': 2100})
        self.assertEqual(self.module.season_have(None), {})


class TestAutoRefreshOnGapChange(unittest.TestCase):
    """赛季缺口出现新项时自动请求刷新方案（Add by MHY）。

    货架方案是一次性快照：物品进囤积会被从货架剔除，攒够之后也不会自己回到
    货架。靠手勾「刷新生产/上架方案」容易忘，所以比对快照自动触发。

    关键取舍：「攒够目标」本身不触发——那时物品正停在囤积里、既不上架也不被
    买走，刷新反而会把它推回货架、被买空后又成缺口，来回翻。
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original = island_plan_refresh.GAP_FILE
        island_plan_refresh.GAP_FILE = str(Path(self.tmp.name) / 'gap.json')
        self.config = MagicMock()

    def tearDown(self):
        island_plan_refresh.GAP_FILE = self.original
        self.tmp.cleanup()

    def _call(self, gap):
        with patch.object(island_plan_refresh, 'current_progress', lambda config, season: {}), \
                patch.object(island_plan_refresh, 'season_stockpile', lambda progress: gap):
            return island_plan_refresh.request_refresh_on_gap_change(self.config, 'autumn')

    def test_flatten_gap(self):
        self.assertEqual(island_plan_refresh.flatten_gap({'grill': {'steak_bowl': 70}}),
                         {'grill/steak_bowl'})
        self.assertEqual(island_plan_refresh.flatten_gap({}), set())

    def test_new_gap_requests_refresh(self):
        """出现新缺口：要把物品从货架挪进囤积。"""
        self.assertTrue(self._call({'grill': {'steak_bowl': 70}}))
        self.config.cross_set.assert_called_once()

    def test_satisfied_item_does_not_request_refresh(self):
        """只是攒够了：留在囤积里，不动方案，免得来回翻。"""
        self._call({'grill': {'steak_bowl': 70}})
        self.config.reset_mock()
        self.assertFalse(self._call({}))
        self.config.cross_set.assert_not_called()

    def test_gap_reappears_after_submit(self):
        """提交任务后仓库掉下去，缺口重新出现：再次请求刷新。"""
        self._call({'grill': {'steak_bowl': 70}})
        self._call({})
        self.config.reset_mock()
        self.assertTrue(self._call({'grill': {'steak_bowl': 70}}))
        self.config.cross_set.assert_called_once()

    def test_no_change_is_noop(self):
        self._call({'grill': {'steak_bowl': 70}})
        self.config.reset_mock()
        self.assertFalse(self._call({'grill': {'steak_bowl': 70}}))
        self.config.cross_set.assert_not_called()


if __name__ == '__main__':
    unittest.main()
