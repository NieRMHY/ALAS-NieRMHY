"""赛季任务任务的限流逻辑测试。"""
import sys
import unittest

sys.path.insert(0, '.')


class TestSeasonPlanRateLimit(unittest.TestCase):
    """限流逻辑测试：方法内的 import 写错只有真正调用才会暴露（真机事故）。"""

    def _fake(self, path):
        from module.island.island_season_plan import IslandSeasonPlan
        obj = IslandSeasonPlan.__new__(IslandSeasonPlan)
        obj.MIN_INTERVAL_MINUTE = 20
        obj.LAST_RUN_FILE = path
        return obj

    def test_missing_file_is_not_too_soon(self):
        """没有记录时不应跳过"""
        obj = self._fake('/tmp/island_season_plan_last_missing.json')
        import os
        if os.path.exists(obj.LAST_RUN_FILE):
            os.remove(obj.LAST_RUN_FILE)
        self.assertFalse(obj._too_soon())

    def test_mark_then_too_soon(self):
        """记录后立刻再查应当判定为「太近」"""
        obj = self._fake('/tmp/island_season_plan_last_test.json')
        import os
        if os.path.exists(obj.LAST_RUN_FILE):
            os.remove(obj.LAST_RUN_FILE)
        obj._mark_ran()
        self.assertTrue(obj._too_soon())
        os.remove(obj.LAST_RUN_FILE)

    def test_stale_record_is_not_too_soon(self):
        """记录很旧时不该跳过"""
        import json
        import os
        obj = self._fake('/tmp/island_season_plan_last_old.json')
        with open(obj.LAST_RUN_FILE, 'w', encoding='utf-8') as f:
            json.dump({'last': 0}, f)
        self.assertFalse(obj._too_soon())
        os.remove(obj.LAST_RUN_FILE)
