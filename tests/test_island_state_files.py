"""岛屿运行时状态文件的位置约束。

这些文件曾平铺在 config/ 下，被 alas_instance()（module/config/utils.py）当成
ALAS 实例：真机 list_instances 返回 13 个实例，其中 6 个是状态文件；每日备份
也把它们当用户配置一起备份。回归点：位置与迁移。
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, '.')


class TestStateFileLocation(unittest.TestCase):
    """状态文件必须落在 config/island/ 子目录里。"""

    def _paths(self):
        from module.island import island_away_cook, island_plan_refresh, island_planner
        from module.island.island_season_plan import IslandSeasonPlan
        return {
            'UNPRODUCIBLE_FILE': island_planner.UNPRODUCIBLE_FILE,
            'VERIFIED_FILE': island_planner.VERIFIED_FILE,
            'PAGE_FILE': island_plan_refresh.PAGE_FILE,
            'DEFAULT_FILE': island_away_cook.DEFAULT_FILE,
            'NOTIFIED_FILE': island_away_cook.NOTIFIED_FILE,
            'LAST_RUN_FILE': IslandSeasonPlan.LAST_RUN_FILE,
        }

    def test_all_state_files_in_subdirectory(self):
        expected = os.path.join('config', 'island')
        for label, path in self._paths().items():
            self.assertTrue(str(path).startswith(expected),
                            f'{label}={path} 不在 {expected} 下')

    def test_not_exposed_as_alas_instance(self):
        """alas_instance() 只扫 config/ 顶层的 .json，子目录天然避开。"""
        from module.config.utils import alas_instance
        bogus = [name for name in alas_instance() if name.startswith('island_')]
        self.assertEqual(bogus, [], f'岛屿状态文件被当成了 ALAS 实例: {bogus}')


class TestLegacyMigration(unittest.TestCase):
    """旧位置的同名文件应被迁移，避免丢掉已验证名单等既有数据。"""

    def test_legacy_file_moved(self):
        from module.island import island_state
        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            os.chdir(tmp)
            try:
                os.makedirs('config', exist_ok=True)
                with open(os.path.join('config', 'island_verified.json'), 'w',
                          encoding='utf-8') as f:
                    f.write('{"grill": ["a"]}')
                path = island_state.state_file('island_verified.json')
                self.assertEqual(path, os.path.join('config', 'island', 'island_verified.json'))
                self.assertTrue(os.path.exists(path))
                self.assertFalse(os.path.exists(os.path.join('config', 'island_verified.json')))
            finally:
                os.chdir(cwd)

    def test_existing_new_file_not_overwritten(self):
        from module.island import island_state
        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            os.chdir(tmp)
            try:
                os.makedirs(os.path.join('config', 'island'), exist_ok=True)
                with open(os.path.join('config', 'island', 'island_verified.json'), 'w',
                          encoding='utf-8') as f:
                    f.write('{"new": ["b"]}')
                with open(os.path.join('config', 'island_verified.json'), 'w',
                          encoding='utf-8') as f:
                    f.write('{"legacy": ["a"]}')
                path = island_state.state_file('island_verified.json')
                with open(path, encoding='utf-8') as f:
                    self.assertIn('new', f.read())
                # 旧文件保持原样，不做删除
                self.assertTrue(os.path.exists(os.path.join('config', 'island_verified.json')))
            finally:
                os.chdir(cwd)

    def test_missing_both_returns_new_path(self):
        from module.island import island_state
        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            os.chdir(tmp)
            try:
                path = island_state.state_file('island_unproducible.json')
                self.assertEqual(path, os.path.join('config', 'island', 'island_unproducible.json'))
            finally:
                os.chdir(cwd)
