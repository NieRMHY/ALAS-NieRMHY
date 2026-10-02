"""方案刷新（一次性刷新开关）测试。"""
import sys
import unittest

sys.path.insert(0, '.')


class TestSeasonStockpile(unittest.TestCase):
    """赛季页面读数 -> 各店排产目标。

    真机踩过：方案刷新从不传 stockpile，导致「只在赛季任务里需要、却不在货架
    也不在基础需求里」的物品永远生产不出来（胡萝卜厚蛋烧/拿铁/便携快餐一直是 0）。
    """

    def setUp(self):
        import json
        import tempfile
        from pathlib import Path
        from module.island import island_plan_refresh

        self.module = island_plan_refresh
        self.tmp = tempfile.TemporaryDirectory()
        self.page_file = Path(self.tmp.name) / 'page.json'
        self.original = island_plan_refresh.PAGE_FILE
        island_plan_refresh.PAGE_FILE = str(self.page_file)
        self.write = lambda data: self.page_file.write_text(
            json.dumps(data, ensure_ascii=False), encoding='utf-8')

    def tearDown(self):
        self.module.PAGE_FILE = self.original
        self.tmp.cleanup()

    def test_collects_gaps_by_shop(self):
        """按「任务需求 + SEASON_BUFFER」排产，不是按需求本身。"""
        buffer = self.module.SEASON_BUFFER
        self.write({
            '营养组合': {'item': 'carrot_omelette', 'have': 0, 'need': 100, 'claimed': False},
            '拿铁时光': {'item': 'latte', 'have': 5, 'need': 100, 'claimed': False},
            '甜蜜引擎': {'item': 'apple_juice', 'have': 250, 'need': 250, 'claimed': False},
            '咖啡供应': {'item': 'iced_coffee', 'have': 250 + buffer, 'need': 250,
                         'claimed': False},
        })
        result = self.module.season_stockpile()
        self.assertEqual(result.get('grill'), {'carrot_omelette': 100 + buffer})
        self.assertEqual(result.get('juu_coffee'), {'latte': 100 + buffer})
        self.assertEqual(result.get('teahouse'), {'apple_juice': 250 + buffer},
                         '刚好卡在需求线上还不够，要留出余量')
        self.assertNotIn('iced_coffee', result.get('juu_coffee', {}),
                         '已经到需求+余量就不该再排')

    def test_materials_and_claimed_are_skipped(self):
        self.write({
            '黄金粮仓': {'item': 'corn', 'have': 0, 'need': 500, 'claimed': False},
            '健康饮食': {'item': 'salad', 'have': 100, 'need': 100, 'claimed': True},
        })
        self.assertEqual(self.module.season_stockpile(), {})

    def test_done_items_are_skipped(self):
        """已提交（done）的物品不再排产。

        真机：蔬菜沙拉 done 之后库存 2100 只是碰巧高过需求 100 才没被排产，
        一旦被别的菜谱消耗到 100 以下就会被重新排进生产目标——这正是
        「提交过了还在产」的成因之一。
        """
        from unittest.mock import patch
        from module.island import island_away_cook

        self.write({
            '健康饮食': {'item': 'salad', 'have': 0, 'need': 100, 'claimed': False},
            '营养组合': {'item': 'carrot_omelette', 'have': 0, 'need': 100,
                         'claimed': False},
        })
        notified = {'autumn': {'salad': {'done': True, 'notified': True, 'last': 100}}}
        with patch.object(island_away_cook, 'load_notified', lambda: notified):
            result = self.module.season_stockpile('autumn')
        self.assertNotIn('salad', result.get('restaurant', {}), '已提交的不该再排产')
        self.assertEqual(result.get('grill'),
                         {'carrot_omelette': 100 + self.module.SEASON_BUFFER})

    def test_done_filter_needs_season(self):
        """不传赛季时判断不了 done，退回「只按页面读数排」的旧行为。"""
        from unittest.mock import patch
        from module.island import island_away_cook

        self.write({
            '健康饮食': {'item': 'salad', 'have': 0, 'need': 100, 'claimed': False},
        })
        notified = {'autumn': {'salad': {'done': True}}}
        with patch.object(island_away_cook, 'load_notified', lambda: notified):
            result = self.module.season_stockpile()
        self.assertEqual(result.get('restaurant'),
                         {'salad': 100 + self.module.SEASON_BUFFER})

    def test_buffer_keeps_a_margin_after_submit(self):
        """提交会把物品扣走，余量保证扣完还剩一点，不会立刻又排产。"""
        buffer = self.module.SEASON_BUFFER
        self.assertGreater(buffer, 0)
        self.write({
            '健康饮食': {'item': 'salad', 'have': 100, 'need': 100, 'claimed': False},
        })
        self.assertEqual(self.module.season_stockpile().get('restaurant'),
                         {'salad': 100 + buffer})

    def test_season_have_feeds_capacity_estimate(self):
        """产能估算要按「还差多少」：仓库已有 248/270 不该按从零做 270 估。

        真机：碳烤肉串就差 22 个却被估成 102 时，远超整店预算 43.2 时而被误判
        「产能不足」整个跳过。
        """
        self.write({
            '营养组合': {'item': 'carrot_omelette', 'have': 86, 'need': 100,
                         'claimed': False},
            '健康饮食': {'item': 'salad', 'have': 2100, 'need': 100, 'claimed': None},
        })
        self.assertEqual(self.module.season_have(),
                         {'carrot_omelette': 86, 'salad': 2100})

    def test_missing_file_returns_empty(self):
        self.assertEqual(self.module.season_stockpile(), {})


class TestAutoRefreshOnGapChange(unittest.TestCase):
    """赛季缺口变化时自动请求刷新方案（Add by MHY）。

    货架方案是一次性快照：物品进囤积会被从货架剔除，攒够之后也不会自己回到
    货架。靠手勾「刷新生产/上架方案」容易忘，所以比对快照自动触发。

    关键取舍：「攒够目标」本身不触发——那时物品正停在囤积里、既不上架也不被
    买走，刷新反而会把它推回货架、被买空后又成缺口，来回翻。
    """

    def setUp(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import MagicMock
        from module.island import island_plan_refresh

        self.module = island_plan_refresh
        self.tmp = tempfile.TemporaryDirectory()
        self.original = island_plan_refresh.GAP_FILE
        island_plan_refresh.GAP_FILE = str(Path(self.tmp.name) / 'gap.json')
        self.config = MagicMock()

    def tearDown(self):
        self.module.GAP_FILE = self.original
        self.tmp.cleanup()

    def _call(self, gap, done):
        from unittest.mock import patch
        with patch.object(self.module, 'season_stockpile',
                          lambda season=None: gap), \
             patch('module.island.island_away_cook.load_notified', lambda: {}), \
             patch('module.island.island_away_cook.done_items',
                   lambda season, notified: done):
            return self.module.request_refresh_on_gap_change(self.config, 'autumn')

    def test_flatten_gap(self):
        self.assertEqual(self.module.flatten_gap({'grill': {'steak_bowl': 70}}),
                         {'grill/steak_bowl'})
        self.assertEqual(self.module.flatten_gap({}), set())

    def test_new_gap_requests_refresh(self):
        """出现新缺口：要把物品从货架挪进囤积。"""
        self.assertTrue(self._call({'grill': {'steak_bowl': 70}}, set()))
        self.config.cross_set.assert_called_once()

    def test_satisfied_item_does_not_request_refresh(self):
        """只是攒够了：留在囤积里，不动方案，免得来回翻。"""
        self._call({'grill': {'steak_bowl': 70}}, set())
        self.config.reset_mock()
        self.assertFalse(self._call({}, set()))
        self.config.cross_set.assert_not_called()

    def test_done_change_requests_refresh(self):
        """任务交掉了：物品该回货架正常售卖。"""
        self._call({'grill': {'steak_bowl': 70}}, set())
        self.config.reset_mock()
        self.assertTrue(self._call({}, {'steak_bowl'}))
        self.config.cross_set.assert_called_once()

    def test_no_change_is_noop(self):
        self._call({'grill': {'steak_bowl': 70}}, set())
        self.config.reset_mock()
        self.assertFalse(self._call({'grill': {'steak_bowl': 70}}, set()))
        self.config.cross_set.assert_not_called()
