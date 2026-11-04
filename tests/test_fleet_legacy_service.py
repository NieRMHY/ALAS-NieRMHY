"""显式本地迁移、默认空白及迁移后的 SQLite 隔离边界。"""
import copy
import json
import tempfile
import unittest
from unittest.mock import Mock, patch

from module.api.config_service import ConfigService
from module.api.dock_service import DockService
from module.api.fleet_tech_service import FleetTechService
from module.api.mind_calculator_service import MindCalculatorService
from module.api.protocol import ApiError
from module.api.router import Router
from module.config.config_updater import ConfigUpdater
from module.config.deep import deep_get, deep_set
from module.config.fleet_legacy import LEGACY_PATHS
from module.runtime import dock_data
from module.runtime.fleet_database import FleetDatabase
from tests.test_api import fixture


class LocalLegacyImportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.configs = ConfigService(fixture(temporary.name))
        self.path = self.configs.path('testpilot')
        self.database = FleetDatabase(self.path)
        self.dock = DockService(self.configs)
        self.mind = MindCalculatorService(self.configs)
        self.tech = FleetTechService(self.configs)
        self.runtime = Mock()
        self.router = Router(self.configs, self.runtime)
        self.data, _ = self.configs.read('testpilot')
        self.snapshot = dock_data.build_snapshot([
            dict(name='杜威', group_type=10102, level=120, rarity='R', base_rarity='R', review=False),
            dict(name='杜威', group_type=10102, level=100, rarity='R', base_rarity='R', review=False),
        ], min_level=1, max_level=125, reached_bottom=True, filters_clear=True,
            physical_count=2, expected_count=2, updated_at='2026-10-22T12:00:00')
        deep_set(self.data, LEGACY_PATHS[0], self.snapshot)
        deep_set(self.data, LEGACY_PATHS[1], dict(ships=[
            dict(name='杜威', level=110, rarity='R', base_rarity='R', excluded=True, review=False,
                 source='旧人工清单')], updated_at='2026-10-22T12:00:00'))
        deep_set(self.data, LEGACY_PATHS[4], dict(observed={'10103': 125},
                 manual={'10102': {'owned': True, 'level': 105}}, nations={'1': 3}))
        self.write()

    def write(self):
        self.path.write_text(json.dumps(self.data, ensure_ascii=False), encoding='utf-8')

    def migrate(self):
        return self.router.dispatch('dock.importLegacy', {
            'instance': 'testpilot', 'revision': self.dock.report('testpilot')['revision']})

    def accept_pending(self, report):
        return self.router.dispatch('dock.review', dict(instance='testpilot', revision=report['revision'],
            pending_revision=report['pending_revision'],
            decisions=[dict(id=row['id'], accept=True) for row in report['pending_changes']]))

    def test_default_reports_ignore_old_data_until_import_is_reviewed_and_keep_source(self):
        original = self.path.read_bytes()
        self.assertEqual(self.dock.report('testpilot')['ships'], [])
        self.assertEqual(self.dock.report('testpilot')['ships'], [])
        self.assertFalse(next(row for row in self.tech.report('testpilot')['ships']
                              if row['group_type'] == 10102)['owned'])
        self.assertEqual(original, self.path.read_bytes())
        self.assertFalse(self.database.path.exists())
        report = self.migrate()
        self.assertTrue(report['legacy_imported'])
        self.assertEqual(report['ships'], [])
        self.assertTrue(report['pending_changes'])
        self.assertEqual(self.dock.report('testpilot')['ships'], [])
        self.assertEqual(self.tech.report('testpilot')['completed'], 0)
        report = self.accept_pending(report)
        self.assertEqual(len(report['ships']), 2)
        self.assertEqual(self.dock.report('testpilot')['ships'][0]['level'], 110)
        tech = {row['group_type']: row for row in self.tech.report('testpilot')['ships']}
        self.assertEqual(tech[10102]['current_level'], 110)
        self.assertTrue(tech[10102]['owned'])
        self.assertIsNone(tech[10103]['current_level'])
        self.assertTrue(tech[10103]['owned'])
        self.assertTrue(tech[10103]['lv120'])
        self.assertEqual(self.tech.report('testpilot')['nation_levels']['1'], 3)
        saved = json.loads(self.path.read_text())
        self.assertEqual(self.path.read_bytes(), original)
        self.assertTrue(all(deep_get(saved, key) == deep_get(self.data, key) for key in LEGACY_PATHS))
        self.assertEqual(saved['DockScan']['Dock']['MinLevel'], self.data['DockScan']['Dock']['MinLevel'])
        self.runtime.start.assert_not_called()

    def test_import_is_once_and_later_json_changes_are_not_consumed(self):
        self.accept_pending(self.migrate())
        self.write()
        before = self.database.path.read_bytes()
        with self.assertRaises(ApiError) as error:
            self.migrate()
        self.assertEqual(error.exception.code, 'ALREADY_IMPORTED')
        self.assertEqual(self.database.path.read_bytes(), before)
        deep_set(self.data, LEGACY_PATHS[4], {'manual': {'10102': {'owned': False}}})
        self.write()
        for _ in range(2):
            self.dock.report('testpilot')
            self.dock.report('testpilot')
            report = self.tech.report('testpilot')
            self.assertTrue(next(row for row in report['ships'] if row['group_type'] == 10102)['owned'])
        self.assertEqual(self.database.path.read_bytes(), before)

    def test_current_database_wins_and_keeps_physical_snapshot(self):
        snapshot = copy.deepcopy(self.snapshot)
        snapshot['ships'] = snapshot['ships'][:1]
        snapshot['ships'][0]['level'] = 125
        snapshot['revision'] = 'new-snapshot'
        self.database.patch_cards(snapshot['ships'], dock_data.read_snapshot(self.database.load())['revision'])
        stored_cards = self.database.load()['snapshot']['ships']
        from module.runtime import fleet_tech
        self.database.patch_technology([dict(group_type=10102, owned=False)], {'1': 0},
            fleet_tech.revision(dock_data.technology_record(self.database.load())))
        self.migrate()
        state = self.database.load()
        self.assertEqual(state['snapshot']['ships'], stored_cards)
        self.assertEqual(len(stored_cards), 1)
        self.assertEqual(stored_cards[0]['level'], 125)
        self.assertEqual(state['technology']['progress']['10102']['owned'], False)
        self.assertNotIn('manual', state['technology'])
        self.assertEqual(state['technology']['nations']['1'], 0)

    def test_invalid_source_and_stale_revision_do_not_consume_import(self):
        self.data['DockScan']['Dock']['Result']['ships'][0]['level'] = 126
        self.write()
        before = self.path.read_bytes()
        with self.assertRaises(ApiError):
            self.migrate()
        self.assertFalse(self.database.load(include_import_status=True)['legacy_imported'])
        self.assertEqual(self.path.read_bytes(), before)
        self.data['DockScan']['Dock']['Result']['ships'][0]['level'] = 120
        self.write()
        with self.assertRaises(ApiError) as error:
            self.dock.import_legacy('testpilot', 'stale')
        self.assertEqual(error.exception.code, 'CONFLICT')
        self.assertFalse(self.database.load(include_import_status=True)['legacy_imported'])
        self.assertTrue(self.migrate()['legacy_imported'])

    def test_no_data_demo_and_path_guards(self):
        self.path.write_text('{}')
        with self.assertRaises(ApiError):
            self.migrate()
        self.assertFalse(self.database.load(include_import_status=True)['legacy_imported'])
        self.write()
        with patch.dict('os.environ', {'DEMO': '1'}), self.assertRaises(ApiError):
            self.migrate()
        with self.assertRaises(ApiError):
            self.dock.import_legacy('../testpilot', 'stale')
        self.assertFalse(self.database.load(include_import_status=True)['legacy_imported'])
        self.runtime.start.assert_not_called()

    def test_config_update_retains_opaque_source_until_explicit_import(self):
        before = copy.deepcopy(self.data)
        updated = ConfigUpdater().config_update(self.data)
        for key in LEGACY_PATHS:
            self.assertEqual(deep_get(updated, key), deep_get(self.data, key))
        self.assertEqual(self.data, before)
        self.assertFalse(self.database.path.exists())

    def test_import_never_attempts_config_cleanup_or_applies_candidates(self):
        before = self.path.read_bytes()
        with patch('module.api.dock_service.atomic_write', side_effect=OSError('readonly config')) as write:
            report = self.migrate()
        write.assert_not_called()
        self.assertTrue(report['legacy_imported'])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertIsNone(self.database.load()['snapshot'])
        self.assertEqual(sum(row['kind'] == 'ship' for row in report['pending_changes']), 2)
