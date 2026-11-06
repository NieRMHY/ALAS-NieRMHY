"""同一底账的真实分析服务、人工覆盖与接口边界回归；只使用临时配置。"""
import json
import tempfile
import unittest
from unittest.mock import Mock, patch

from pydantic import ValidationError

from module.api.config_service import ConfigService
from module.api.dock_service import DockService
from module.api.fleet_tech_service import FleetTechService
from module.api.mind_calculator_service import MindCalculatorService
from module.api.protocol import ApiError, FleetTechChange
from module.api.router import Router
from module.config.deep import deep_set
from module.runtime.fleet_database import FleetDatabase
from module.runtime import dock_data
from module.retire.dock_scan import DockScan
from module.exception import MindCalculatorScanError
from tests.test_api import fixture


class SharedAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.configs = ConfigService(fixture(self.temp.name))
        self.mind = MindCalculatorService(self.configs)
        self.tech = FleetTechService(self.configs)
        self.dock = DockService(self.configs)

    def write(self, data):
        self.configs.path('testpilot').write_text(json.dumps(data), encoding='utf-8')

    def test_旧100级记录读取默认满星但不回写舰船或累计科技(self):
        database = FleetDatabase(self.configs.path('testpilot'))
        initial = self.dock.report('testpilot')
        self.dock.patch('testpilot', initial['revision'], [dict(name='杜威', group_type=10102, level=100)])
        with database._transaction() as connection:
            connection.execute('UPDATE ships SET full_star=NULL')
        before = database.path.read_bytes()
        stored = database.load()
        report = self.dock.report('testpilot')
        self.assertTrue(report['ships'][0]['full_star'])
        self.assertEqual(report['revision'], stored['snapshot']['revision'])
        self.assertIsNone(database.load()['snapshot']['ships'][0]['full_star'])
        self.assertEqual(database.load()['technology'], stored['technology'])
        self.assertEqual(database.path.read_bytes(), before)

    def scan(self, level=105, rows=None, confirm=True, **extra):
        database = FleetDatabase(self.configs.path('testpilot'))
        state = database.load()
        if rows is None:
            rows = [dict(name='杜威', group_type=10102, level=level, review=False,
                         rarity='R', base_rarity='R', source='自动扫描第 1 页')]
        params = dict(min_level=1, max_level=125, reached_bottom=True, filters_clear=True,
                      physical_count=len(rows), expected_count=len(rows), updated_at=f'fixture-{level}')
        params.update(extra)
        snapshot = dock_data.build_snapshot(rows, **params)
        database.save_scan(snapshot, dock_data.read_snapshot(state)['revision'])
        pending = database.load(include_pending=True)
        if confirm and pending['pending_changes']:
            database.review([dict(id=row['id'], accept=True) for row in pending['pending_changes']],
                            dock_data.read_snapshot(pending)['revision'], pending['pending_revision'])
        return database.load()['snapshot']

    def test_同一底账自动供两份分析且读取不写盘不操作游戏(self):
        snapshot = self.scan()
        before = self.configs.path('testpilot').read_bytes()
        runtime = Mock()
        router = Router(self.configs, runtime)
        for method in ('dock.report', 'fleetTech.report'):
            self.assertIsInstance(router.dispatch(method, {'instance': 'testpilot'}), dict)
        self.assertEqual(self.dock.report('testpilot')['ships'][0]['level'], 105)
        row = next(row for row in self.tech.report('testpilot')['ships'] if row['group_type'] == 10102)
        self.assertEqual(row['current_level'], 105)
        self.assertEqual(self.dock.report('testpilot')['revision'], snapshot['revision'])
        self.assertEqual(self.configs.path('testpilot').read_bytes(), before)
        runtime.start.assert_not_called()


    def test_科技人工校正保留且不复制扫描快照(self):
        snapshot = self.scan()
        before = self.configs.path('testpilot').read_bytes()
        report = self.tech.report('testpilot')
        self.tech.patch('testpilot', report['revision'], [FleetTechChange(group_type=10102, lv120=True)], {'1': 1})
        self.assertEqual(self.configs.path('testpilot').read_bytes(), before)
        state = FleetDatabase(self.configs.path('testpilot')).load()
        self.assertEqual(state['snapshot']['ships'], snapshot['ships'])
        stored = state['technology']
        self.assertNotIn('last_scan', stored)
        self.assertNotIn('observed', stored)
        self.scan(110)
        report = self.tech.report('testpilot')
        self.assertTrue(next(row for row in report['ships'] if row['group_type'] == 10102)['lv120'])
        self.assertEqual(report['nation_levels']['1'], 1)
        self.assertEqual(self.dock.report('testpilot')['ships'][0]['level'], 110)


    def test_配置扫描范围不伪造快照覆盖且接口严格验证(self):
        self.scan()
        runtime = Mock()
        router = Router(self.configs, runtime)
        report = router.dispatch('dock.configure', dict(instance='testpilot', min_level=95, max_level=120))
        self.assertEqual((report['min_level'], report['max_level']), (95, 120))
        self.assertEqual(report['scan_range'], dict(min_level=1, max_level=125))
        before = self.configs.path('testpilot').read_bytes()
        with self.assertRaises(ApiError):
            router.dispatch('dock.configure', dict(instance='testpilot', min_level=120, max_level=95))
        with self.assertRaises(ValidationError):
            router.dispatch('dock.configure', dict(instance='testpilot', min_level=True, max_level=125))
        self.assertEqual(self.configs.path('testpilot').read_bytes(), before)
        runtime.start.assert_not_called()

    def test_底账接口严格局部更新与双版本审核受演示模式保护(self):
        runtime = Mock()
        router = Router(self.configs, runtime)
        initial = self.dock.report('testpilot')
        report = router.dispatch('dock.patch', dict(instance='testpilot', revision=initial['revision'], changes=[
            dict(name='杜威', group_type=10102, level=100),
            dict(name='杜威', group_type=10102, level=120, review=True)]))
        ids = [row['id'] for row in report['ships']]
        self.assertNotEqual(*ids)
        report = router.dispatch('dock.patch', dict(instance='testpilot', revision=report['revision'],
            changes=[dict(id=ids[0], level=106)]))
        self.assertEqual([row['level'] for row in report['ships']], [106, 120])
        self.assertTrue(report['ships'][1]['review'])
        before = FleetDatabase(self.configs.path('testpilot')).path.read_bytes()
        for change in (dict(id=True, level=100), dict(id=ids[0], level=True), dict(id=ids[0], name=None)):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                router.dispatch('dock.patch', dict(instance='testpilot', revision=report['revision'], changes=[change]))
        self.assertEqual(FleetDatabase(self.configs.path('testpilot')).path.read_bytes(), before)
        with self.assertRaises(ApiError) as stale:
            router.dispatch('dock.patch', dict(instance='testpilot', revision=initial['revision'], changes=[dict(id=ids[0], review=True)]))
        self.assertEqual(stale.exception.code, 'CONFLICT')
        requests = [('dock.patch', dict(instance='testpilot', revision=report['revision'], changes=[dict(id=ids[0], review=True)])),
                    ('dock.review', dict(instance='testpilot', revision=report['revision'], pending_revision='a' * 64,
                                         decisions=[dict(id='ship:1', accept=True)]))]
        for method, params in requests:
            self.assertTrue(router.methods[method].mutates)
            with patch.dict('os.environ', {'DEMO': '1'}), self.assertRaises(ApiError):
                router.dispatch(method, params)
        self.assertEqual(FleetDatabase(self.configs.path('testpilot')).path.read_bytes(), before)
        runtime.start.assert_not_called()

    def test_同次读取逐条匹配不能重复使用已经采纳的副本(self):
        report = self.dock.patch('testpilot', self.dock.report('testpilot')['revision'], [
            dict(name='杜威', group_type=10102, level=100),
            dict(name='杜威', group_type=10102, level=100)])
        first_id, second_id = [row['id'] for row in report['ships']]
        self.scan(rows=[dict(name='杜威', group_type=10102, level=110),
                        dict(name='杜威', group_type=10102, level=120)], confirm=False)
        staged = self.dock.report('testpilot')
        proposals = [row for row in staged['pending_changes'] if row['kind'] == 'ship']
        self.assertEqual([row['operation'] for row in proposals], ['resolve', 'resolve'])
        report = self.dock.review('testpilot', staged['revision'], staged['pending_revision'],
            [dict(id=proposals[0]['id'], accept=True, ship_id=first_id)])
        remaining = next(row for row in report['pending_changes'] if row['id'] == proposals[1]['id'])
        self.assertEqual([row['id'] for row in remaining['candidates']], [second_id])
        database = FleetDatabase(self.configs.path('testpilot'))
        before = database.load(include_pending=True)
        with self.assertRaises(ApiError) as error:
            self.dock.review('testpilot', report['revision'], report['pending_revision'],
                [dict(id=remaining['id'], accept=True, ship_id=first_id)])
        self.assertEqual(error.exception.code, 'INVALID_PARAMS')
        self.assertEqual(database.load(include_pending=True), before)
        report = self.dock.review('testpilot', report['revision'], report['pending_revision'],
            [dict(id=remaining['id'], accept=True, ship_id=second_id)])
        self.assertEqual([(row['id'], row['level']) for row in report['ships']],
                         [(first_id, 110), (second_id, 120)])

    def test_完全匹配的副本不能再分配给同次读取中的存疑卡片(self):
        report = self.dock.patch('testpilot', self.dock.report('testpilot')['revision'], [
            dict(name='杜威', group_type=10102, level=100) for _ in range(3)])
        ids = [row['id'] for row in report['ships']]
        self.scan(rows=[dict(name='杜威', group_type=10102, level=100),
                        dict(name='杜威', group_type=10102, level=110)], confirm=False)
        staged = self.dock.report('testpilot')
        ambiguous, = [row for row in staged['pending_changes'] if row['kind'] == 'ship']
        self.assertEqual(ambiguous['operation'], 'resolve')
        self.assertEqual({row['id'] for row in ambiguous['candidates']}, set(ids[1:]))
        before = FleetDatabase(self.configs.path('testpilot')).load(include_pending=True)
        with self.assertRaises(ApiError):
            self.dock.review('testpilot', staged['revision'], staged['pending_revision'],
                [dict(id=ambiguous['id'], accept=True, ship_id=ids[0])])
        self.assertEqual(FleetDatabase(self.configs.path('testpilot')).load(include_pending=True), before)

    def test_同批重复匹配失败时回滚已经处理的前一条决定(self):
        report = self.dock.patch('testpilot', self.dock.report('testpilot')['revision'], [
            dict(name='杜威', group_type=10102, level=100),
            dict(name='杜威', group_type=10102, level=100)])
        card_id = report['ships'][0]['id']
        self.scan(rows=[dict(name='杜威', group_type=10102, level=110),
                        dict(name='杜威', group_type=10102, level=120)], confirm=False)
        staged = self.dock.report('testpilot')
        proposals = [row for row in staged['pending_changes'] if row['kind'] == 'ship']
        database = FleetDatabase(self.configs.path('testpilot'))
        before = database.load(include_pending=True)
        with self.assertRaises(ApiError):
            self.dock.review('testpilot', staged['revision'], staged['pending_revision'],
                [dict(id=row['id'], accept=True, ship_id=card_id) for row in proposals])
        self.assertEqual(database.load(include_pending=True), before)

    def test_空扫描不会复活旧清单(self):
        data, _ = self.configs.read('testpilot')
        deep_set(data, 'MindCalculatorScan.MindCalculator.Result', dict(ships=[
            dict(name='杜威', level=105, source='自动扫描第 1 页')]))
        self.write(data)
        self.scan(rows=[])
        self.assertEqual(self.dock.report('testpilot')['ships'], [])

    def test_旧配置不会自动导入且分析保存不改配置(self):
        data, _ = self.configs.read('testpilot')
        deep_set(data, 'DockScan.Dock.Result', dock_data.build_snapshot(
            [dict(name='杜威', group_type=10102, level=125, review=False)],
            min_level=1, max_level=125, reached_bottom=True, filters_clear=True,
            physical_count=1, expected_count=1, updated_at='legacy'))
        deep_set(data, 'MindCalculatorScan.MindCalculator.Result', {'ships': [dict(name='杜威', level=125)]})
        deep_set(data, 'MindCalculatorScan.MindCalculator.Analysis', {'extra': [dict(name='卡辛', level=125)]})
        deep_set(data, 'FleetTechScan.FleetTech.Record', {'observed': {'10102': 125},
                                                        'manual': {'10102': {'owned': True}}, 'nations': {'1': 5}})
        deep_set(data, 'MindCalculatorScan.MindCalculator.FleetTechRecord', {'observed': {'10102': 125}})
        self.write(data)
        before = self.configs.path('testpilot').read_bytes()
        self.assertEqual(self.dock.report('testpilot')['ships'], [])
        self.assertEqual(self.tech.report('testpilot')['completed'], 0)
        self.tech.patch('testpilot', self.tech.report('testpilot')['revision'],
                        [FleetTechChange(group_type=10102, owned=True)], {})
        self.assertEqual(self.configs.path('testpilot').read_bytes(), before)
        self.assertEqual(self.dock.report('testpilot')['ships'], [])

    def test_重载独立保留人工否定且不覆盖底账正向证据(self):
        snapshot = self.scan(120)
        card_id = snapshot['ships'][0]['id']
        for field in ('owned', 'full_star', 'lv120'):
            with self.subTest(field=field, target=None), self.assertRaises(ValidationError):
                FleetTechChange(group_type=10102, **{field: None})
            before = self.tech.report('testpilot')
            restored = self.tech.patch('testpilot', before['revision'],
                [FleetTechChange(group_type=10102, owned=True, full_star=True, lv120=True)], {})
            corrected = self.tech.patch('testpilot', restored['revision'],
                [FleetTechChange(group_type=10102, **{field: False})], {})
            row = next(row for row in corrected['ships'] if row['group_type'] == 10102)
            self.assertFalse(row[field])
            self.assertEqual(self.dock.report('testpilot')['ships'], snapshot['ships'])
            self.assertEqual(self.tech.report('testpilot'), corrected)
        self.dock.patch('testpilot', self.dock.report('testpilot')['revision'],
                        [dict(id=card_id, delete=True)])
        report = self.tech.report('testpilot')
        row = next(row for row in report['ships'] if row['group_type'] == 10102)
        self.assertFalse(row['lv120'])
        self.assertEqual(row['current_count'], 0)
        corrected = self.tech.patch('testpilot', report['revision'],
                                     [FleetTechChange(group_type=10102, lv120=False)], {})
        for _ in range(2):
            self.assertEqual(self.tech.report('testpilot'), corrected)
        # Editing another type cannot restore the corrected retired milestone.
        self.dock.patch('testpilot', self.dock.report('testpilot')['revision'],
                        [dict(name='卡辛', group_type=10103, level=120)])
        row = next(row for row in self.tech.report('testpilot')['ships'] if row['group_type'] == 10102)
        self.assertFalse(row['lv120'])

    def test_历史最高只供诊断且科技随底账与人工证据变化(self):
        snapshot = self.scan(125)
        card_id = snapshot['ships'][0]['id']
        self.dock.patch('testpilot', snapshot['revision'], [dict(id=card_id, level=100)])
        row = next(row for row in self.tech.report('testpilot')['ships'] if row['group_type'] == 10102)
        self.assertEqual(row['current_level'], 100)
        self.assertTrue(row['lv120'])
        self.assertTrue(row['full_star'])
        report = self.tech.patch('testpilot', self.tech.report('testpilot')['revision'],
                                [FleetTechChange(group_type=10102, lv120=False, full_star=False)], {})
        row = next(row for row in report['ships'] if row['group_type'] == 10102)
        self.assertFalse(row['lv120'])
        self.assertFalse(row['full_star'])
        self.assertEqual(row['evidence']['owned'], [card_id])
        self.assertEqual(row['evidence']['lv120'], [])
        self.assertEqual(report, self.tech.report('testpilot'))

    def test_反复读取不写库不运行游戏(self):
        self.scan()
        database = FleetDatabase(self.configs.path('testpilot'))
        before = database.path.read_bytes()
        config_before = self.configs.path('testpilot').read_bytes()
        runtime = Mock()
        router = Router(self.configs, runtime)
        # Pending analysis belongs to a client draft until an explicit save.
        draft = self.dock.report('testpilot')['ships']
        draft[0]['review'] = True
        for _ in range(3):
            for method in ('dock.report', 'fleetTech.report'):
                router.dispatch(method, {'instance': 'testpilot'})
        self.assertFalse(self.dock.report('testpilot')['ships'][0]['review'])
        self.assertEqual(database.path.read_bytes(), before)
        self.assertEqual(self.configs.path('testpilot').read_bytes(), config_before)
        runtime.start.assert_not_called()

    def test_通用确认弹窗停止且不点击(self):
        scanner = object.__new__(DockScan)
        scanner.appear = Mock(return_value=True)
        scanner.device = Mock()
        with self.assertRaises(MindCalculatorScanError):
            scanner.handle_popup_confirm()
        scanner.device.click.assert_not_called()


if __name__ == '__main__':
    unittest.main()
