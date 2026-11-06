"""The player-owned ledger changes only through edits or reviewed proposals."""
import copy
import json
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

from module.api.dock_service import DockService
from module.api.fleet_tech_service import FleetTechService
from module.api.protocol import FleetTechChange
from module.runtime import dock_data
from module.runtime.fleet_database import FleetDatabase, FleetDatabaseConflict


class FleetLedgerTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'pilot.json'
        self.path.write_text('{}', encoding='utf-8')
        self.db = FleetDatabase(self.path)
        self.configs = SimpleNamespace(path=lambda _: self.path, lock=threading.RLock(),
            read=lambda _: (json.loads(self.path.read_text(encoding='utf-8')), 'fixture'))

    def revision(self):
        return dock_data.read_snapshot(self.db.load())['revision']

    def cards(self):
        return copy.deepcopy(dock_data.read_snapshot(self.db.load())['ships'])

    def edit(self, *changes):
        self.db.patch_cards(list(changes), self.revision())

    def scan(self, rows):
        value = dock_data.build_snapshot(rows, min_level=1, max_level=125,
            reached_bottom=True, filters_clear=True, physical_count=len(rows),
            expected_count=len(rows), updated_at='2026-10-25T12:00:00+00:00')
        self.db.save_scan(value, self.revision())
        return self.db.load(include_pending=True)

    def decide(self, decisions):
        state = self.db.load()
        self.db.review(decisions, self.revision(), state['pending_revision'])

    def test_duplicate_cards_have_stable_independent_ids_and_nullable_experience(self):
        self.edit(dict(name='杜威', group_type=10102, level=100, extra_exp=None),
                  dict(name='杜威', group_type=10102, level=100, extra_exp=0))
        first, second = self.cards()
        self.assertNotEqual(first['id'], second['id'])
        self.assertEqual((first['extra_exp'], second['extra_exp']), (None, 0))
        self.edit(dict(id=first['id'], level=101, review=True))
        changed, untouched = self.cards()
        self.assertEqual((changed['id'], changed['level'], changed['extra_exp'], changed['review']),
                         (first['id'], 101, None, True))
        self.assertEqual(untouched, second)
        self.edit(dict(id=second['id'], delete=True))
        self.assertEqual(self.cards(), [changed])
        with closing(sqlite3.connect(self.db.path)) as connection:
            self.assertNotIn('mind_settings', {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")})

    def test_scan_only_stages_and_individual_review_does_not_apply_other_rows(self):
        self.edit(dict(name='杜威', group_type=10102, level=100, extra_exp=350),
                  dict(name='卡辛', group_type=10103, level=100, extra_exp=0))
        before = self.cards()
        pending = self.scan([dict(name='杜威', group_type=10102, level=110),
                             dict(name='卡辛', group_type=10103, level=120)])
        self.assertEqual(self.cards(), before)
        proposals = [item for item in pending['pending_changes'] if item['kind'] == 'ship']
        self.assertEqual(len(proposals), 2)
        accepted = next(item for item in proposals if item['group_type'] == 10102)
        rejected = next(item for item in proposals if item['group_type'] == 10103)
        self.decide([dict(id=accepted['id'], accept=True)])
        cards = {row['id']: row for row in self.cards()}
        self.assertEqual(cards[before[0]['id']]['level'], 110)
        self.assertEqual(cards[before[1]['id']], before[1])
        self.assertIn(rejected['id'], {item['id'] for item in self.db.load(include_pending=True)['pending_changes']})
        self.decide([dict(id=rejected['id'], accept=False)])
        self.assertEqual({row['id']: row for row in self.cards()}[before[1]['id']], before[1])

    def test_ambiguous_duplicates_require_explicit_target_and_never_blindly_overwrite(self):
        self.edit(dict(name='杜威', group_type=10102, level=100),
                  dict(name='杜威', group_type=10102, level=100))
        before = self.cards()
        pending = self.scan([dict(name='杜威', group_type=10102, level=110)])
        proposals = [item for item in pending['pending_changes'] if item['kind'] == 'ship']
        ambiguous = next(item for item in proposals if item['operation'] == 'resolve')
        self.assertEqual({item['id'] for item in ambiguous['candidates']}, {row['id'] for row in before})
        with self.assertRaises(ValueError):
            self.decide([dict(id=ambiguous['id'], accept=True)])
        self.assertEqual(self.cards(), before)
        self.decide([dict(id=ambiguous['id'], accept=True, ship_id=before[1]['id'])])
        cards = {row['id']: row for row in self.cards()}
        self.assertEqual(cards[before[0]['id']], before[0])
        self.assertEqual(cards[before[1]['id']]['level'], 110)

    def test_accept_all_and_reject_all_are_explicit_and_leave_no_pending_rows(self):
        pending = self.scan([dict(name='杜威', group_type=10102, level=105),
                             dict(name='卡辛', group_type=10103, level=110)])
        self.assertEqual(self.cards(), [])
        self.decide([dict(id=item['id'], accept=False) for item in pending['pending_changes']])
        self.assertEqual(self.cards(), [])
        self.assertEqual(self.db.load(include_pending=True)['pending_changes'], [])
        pending = self.scan([dict(name='杜威', group_type=10102, level=105),
                             dict(name='卡辛', group_type=10103, level=110)])
        self.decide([dict(id=item['id'], accept=True) for item in pending['pending_changes']])
        self.assertEqual(sorted((row['name'], row['level']) for row in self.cards()),
                         [('卡辛', 110), ('杜威', 105)])
        self.assertEqual(self.db.load(include_pending=True)['pending_changes'], [])

    def test_stale_manual_edit_and_stale_pending_review_do_not_change_state(self):
        stale_revision = self.revision()
        self.edit(dict(name='杜威', group_type=10102, level=100))
        committed = self.db.load(include_pending=True)
        with self.assertRaises(FleetDatabaseConflict):
            self.db.patch_cards([dict(name='卡辛', level=100)], stale_revision)
        self.assertEqual(self.db.load(include_pending=True), committed)
        old = self.scan([dict(name='杜威', group_type=10102, level=110)])
        with self.assertRaises(FleetDatabaseConflict):
            self.scan([dict(name='杜威', group_type=10102, level=120)])
        self.decide([dict(id=item['id'], accept=False) for item in old['pending_changes']])
        latest = self.scan([dict(name='杜威', group_type=10102, level=120)])
        with self.assertRaises(FleetDatabaseConflict):
            self.db.review([dict(id=old['pending_changes'][0]['id'], accept=True)],
                           self.revision(), old['pending_revision'])
        self.assertEqual(self.db.load(include_pending=True), latest)

    def test_technology_manual_decisions_survive_card_updates_and_rejected_scans(self):
        service = FleetTechService(self.configs)
        report = service.report('pilot')
        service.patch('pilot', report['revision'], [FleetTechChange(group_type=10102,
            owned=False, full_star=False)], {'1': 3})
        manual = copy.deepcopy(self.db.load()['technology'])
        self.edit(dict(name='杜威', group_type=10102, level=125))
        self.assertEqual([row['level'] for row in self.cards()], [125])
        pending = self.scan([dict(name='杜威', group_type=10102, level=120)])
        self.decide([dict(id=item['id'], accept=False) for item in pending['pending_changes']])
        self.assertEqual(self.db.load()['technology'], manual)
        reloaded = service.report('pilot')
        row = next(item for item in reloaded['ships'] if item['group_type'] == 10102)
        self.assertFalse(row['owned'])
        self.assertEqual(row['current_count'], 1)
        self.assertEqual(row['current_level'], 125)
        self.assertEqual(reloaded['nation_levels']['1'], 3)

    def test_local_legacy_read_stages_without_mutating_ledger_or_source_json(self):
        source = {'MindCalculatorScan': {'MindCalculator': {'Result': {
            'ships': [dict(name='杜威', level=110)]}}}}
        self.path.write_text(json.dumps(source, ensure_ascii=False), encoding='utf-8')
        original = self.path.read_bytes()
        service = DockService(self.configs)
        initial = service.report('pilot')
        self.assertEqual(initial['ships'], [])
        self.assertFalse(self.db.path.exists())
        service.import_legacy('pilot', initial['revision'])
        self.assertEqual(self.cards(), [])
        self.assertTrue(self.db.load(include_pending=True)['pending_changes'])
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(service.report('pilot')['ships'], [])
        self.assertEqual(self.path.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
