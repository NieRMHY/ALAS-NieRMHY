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
        self.write({
            '营养组合': {'item': 'carrot_omelette', 'have': 0, 'need': 100, 'claimed': False},
            '拿铁时光': {'item': 'latte', 'have': 5, 'need': 100, 'claimed': False},
            '甜蜜引擎': {'item': 'apple_juice', 'have': 250, 'need': 250, 'claimed': False},
        })
        result = self.module.season_stockpile()
        self.assertEqual(result.get('grill'), {'carrot_omelette': 100})
        self.assertEqual(result.get('juu_coffee'), {'latte': 100})
        self.assertNotIn('teahouse', result, '已攒够的不该再排')

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
        self.assertEqual(result.get('grill'), {'carrot_omelette': 100})

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
        self.assertEqual(result.get('restaurant'), {'salad': 100})

    def test_missing_file_returns_empty(self):
        self.assertEqual(self.module.season_stockpile(), {})
