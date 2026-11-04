"""Typed canonical cards, review transactions and SQLite failure isolation."""
import copy
from contextlib import closing
import multiprocessing
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from module.runtime import dock_data
from module.runtime.fleet_database import FleetDatabase, FleetDatabaseAlreadyImported, FleetDatabaseConflict
from module.runtime.fleet_tech import revision
from tests.platform_capabilities import supports_symlinks


def snapshot(tag='first'):
    return dock_data.build_snapshot([
        dict(group_type=10102, level=125, name='杜威', rarity='R', base_rarity='R'),
        dict(group_type=10103, level=100, name='卡辛', rarity='R', base_rarity='R'),
        dict(level=0, name='未识别舰船', review=True, source='unknown')],
        min_level=1, max_level=125, physical_count=3, expected_count=None,
        reached_bottom=False, filters_clear=False, updated_at=tag)


def current_revision(database):
    return dock_data.read_snapshot(database.load())['revision']


def set_technology(database, options):
    database.patch_technology(
        [dict(group_type=int(gid), **entry) for gid, entry in options.get('progress', {}).items()],
        options.get('nations', {}), revision(dock_data.technology_record(database.load())))


def increment_worker(config_path, barrier, count):
    database = FleetDatabase(Path(config_path))
    barrier.wait(timeout=15)
    for _ in range(count):
        with database._transaction() as connection:
            connection.execute("INSERT INTO nation_technology VALUES ('1', 1) "
                               'ON CONFLICT(nation_key) DO UPDATE SET level=level+1')


def patch_worker(config_path, barrier, expected_revision, tag, queue):
    database = FleetDatabase(Path(config_path))
    barrier.wait(timeout=15)
    try:
        database.patch_cards([dict(name=tag, level=100)], expected_revision)
    except FleetDatabaseConflict:
        queue.put('conflict')
    else:
        queue.put('saved')


def scan_worker(config_path, barrier, tag, queue):
    database = FleetDatabase(Path(config_path))
    barrier.wait(timeout=15)
    try:
        database.save_scan(snapshot(tag), revision({}))
    except FleetDatabaseConflict:
        queue.put('conflict')
    else:
        queue.put('staged')


def crash_editor_worker(config_path):
    database = FleetDatabase(Path(config_path))
    with database._transaction() as connection:
        connection.execute('PRAGMA cache_size=2')
        connection.execute('PRAGMA cache_spill=ON')
        for index in range(10000, 14000):
            database._set_progress(connection, str(index), {'owned': False}, source='crash fixture')
        connection.execute("UPDATE nation_technology SET level=99 WHERE nation_key='1'")
        os._exit(23)


def import_worker(config_path, barrier, key, queue):
    database = FleetDatabase(Path(config_path))
    barrier.wait(timeout=15)
    try:
        database.stage_legacy({'snapshot': snapshot(key), 'technology': {
            'manual': {key: {'owned': True}}}}, revision({}))
    except FleetDatabaseAlreadyImported:
        queue.put('already_imported')
    else:
        queue.put('staged')


class FleetDatabaseTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = Path(self.temp.name) / 'pilot.json'
        self.db = FleetDatabase(self.config)

    def current_revision(self):
        return current_revision(self.db)

    def empty(self, include_import_status=False):
        value = dict(snapshot=None, technology={}, pending_revision=None, pending_changes=[])
        if include_import_status:
            value['legacy_imported'] = False
        return value

    def seed(self):
        self.db.patch_cards(snapshot()['ships'], self.current_revision())
        return self.db.load(include_pending=True)

    def assert_counts(self, **counts):
        with closing(sqlite3.connect(self.db.path)) as connection:
            for table, expected in counts.items():
                self.assertEqual(connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0],
                                 expected, table)

    def decide_all(self, accept):
        state = self.db.load(include_pending=True)
        self.db.review([dict(id=row['id'], accept=accept) for row in state['pending_changes']],
                       self.current_revision(), state['pending_revision'])

    def test_schema_has_typed_cards_technology_and_pending_tables_without_shadow_settings(self):
        self.seed()
        with closing(sqlite3.connect(self.db.path)) as connection:
            tables = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
            self.assertEqual(tables, {'ships', 'fleet_info', 'nation_technology',
                                     'pending_ships', 'pending_technology', 'pending_nations',
                                     'pending_targets', 'technology_progress'})
            columns = {row[1]: row for row in connection.execute('PRAGMA table_info(ships)')}
            self.assertEqual(set(columns), {'id', 'position', 'group_type', 'name', 'level',
                'rarity', 'base_rarity', 'extra_exp', 'review', 'source', 'full_star', 'form'})
            self.assertEqual(columns['id'][2], 'INTEGER')
            self.assertEqual(columns['id'][5], 1)
            sql = connection.execute("SELECT sql FROM sqlite_master WHERE name='ships'").fetchone()[0]
            self.assertIn('AUTOINCREMENT', sql.upper())
            for table in tables:
                for column in connection.execute(f'PRAGMA table_info({table})'):
                    self.assertNotIn(column[1], {'payload', 'metadata', 'json'})
                    self.assertNotIn('json', column[1].lower())
            self.assertEqual(connection.execute('PRAGMA user_version').fetchone()[0], FleetDatabase.SCHEMA_VERSION)

    def test_deleted_card_ids_are_not_reused_and_scan_does_not_replace_existing_ids(self):
        first = self.seed()['snapshot']['ships']
        self.db.patch_cards([dict(id=first[0]['id'], delete=True)], self.current_revision())
        self.db.patch_cards([dict(name='新舰船', level=100)], self.current_revision())
        cards = self.db.load()['snapshot']['ships']
        self.assertGreater(cards[-1]['id'], max(row['id'] for row in first))
        before = copy.deepcopy(cards)
        self.db.save_scan(snapshot('next'), self.current_revision())
        self.assertEqual(self.db.load()['snapshot']['ships'], before)

    def test_scan_stages_only_known_fields_and_rejecting_does_not_change_canonical_revision(self):
        active = self.seed()
        scan = snapshot('next')
        scan['ships'][0].update(level=120, recognition_debug=object(), slot={'page': 1})
        scan['raw_evidence'] = object()
        self.db.save_scan(scan, self.current_revision())
        with patch.object(self.db, '_differences', side_effect=AssertionError('unexpected pending projection')):
            confirmed = self.db.load()
        self.assertNotIn('pending_changes', confirmed)
        state = self.db.load(include_pending=True)
        self.assertEqual(confirmed['snapshot'], state['snapshot'])
        self.assertEqual(state['snapshot'], active['snapshot'])
        proposal = next(row for row in state['pending_changes'] if row['kind'] == 'ship')
        self.assertNotIn('recognition_debug', proposal['after'])
        self.assertNotIn('slot', proposal['after'])
        self.decide_all(False)
        self.assertEqual(self.db.load()['snapshot'], active['snapshot'])
        self.assertIsNone(self.db.load()['pending_revision'])

    def test_saved_milestones_and_nations_survive_unreviewed_scans(self):
        self.seed()
        options = {'progress': {'10102': {'owned': True, 'full_star': False, 'lv120': False,
                                        'awakening_pending': True}}, 'nations': {'1': 0, '3': None}}
        set_technology(self.db, options)
        saved = self.db.load()['technology']
        self.db.save_scan(snapshot('next'), self.current_revision())
        self.assertEqual(self.db.load()['technology'], saved)
        self.assertEqual(saved['nations'], options['nations'])
        self.assertTrue(saved['progress']['10102']['awakening_pending'])
        self.assertFalse(saved['progress']['10102']['full_star'])
        self.assert_counts(ships=3, nation_technology=2)

    def test_invalid_edits_roll_back_earlier_updates_in_the_same_batch(self):
        first = self.seed()['snapshot']['ships'][0]
        for invalid in (-1, 1.5, '100', True, object()):
            committed = self.db.load(include_pending=True)
            with self.subTest(level=repr(invalid)):
                with self.assertRaises((TypeError, ValueError, sqlite3.Error)):
                    self.db.patch_cards([dict(id=first['id'], level=90),
                        dict(name='invalid', level=invalid)], self.current_revision())
                self.assertEqual(self.db.load(include_pending=True), committed)

    def test_scan_proof_validation_is_strict_and_failed_stage_preserves_previous_candidates(self):
        self.db.save_scan(snapshot(), self.current_revision())
        committed = self.db.load(include_pending=True)
        invalid = {'physical_count': (None, -1, True, 1.0, '1'),
            'expected_count': (-1, True, 1.0, '1'), 'reached_bottom': (1, 'true'),
            'filters_clear': (1, 'true')}
        for field, values in invalid.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    scan = snapshot('broken')
                    scan[field] = value
                    with self.assertRaises(ValueError):
                        self.db.save_scan(scan, self.current_revision())
                    self.assertEqual(self.db.load(include_pending=True), committed)

    def test_partial_scan_never_proposes_retirement_and_complete_scan_requires_acceptance(self):
        before = self.seed()
        scan = snapshot('partial')
        scan.update(ships=[], physical_count=0, expected_count=0)
        self.db.save_scan(scan, self.current_revision())
        self.assertFalse(any(row['operation'] == 'remove' for row in self.db.load(include_pending=True)['pending_changes']))
        scan.update(reached_bottom=True, filters_clear=True)
        self.db.save_scan(scan, self.current_revision())
        self.assertEqual(self.db.load()['snapshot'], before['snapshot'])
        removals = [row for row in self.db.load(include_pending=True)['pending_changes'] if row['operation'] == 'remove']
        self.assertEqual(len(removals), 2)
        with self.assertRaisesRegex(ValueError, '单独确认'):
            self.decide_all(True)
        for row in removals:
            state = self.db.load(include_pending=True)
            self.db.review([dict(id=row['id'], accept=True)], self.current_revision(), state['pending_revision'])
        self.assertEqual([row['name'] for row in self.db.load()['snapshot']['ships']], ['未识别舰船'])
        self.assertTrue(self.db.load()['technology']['progress']['10102']['lv120'])

    def test_review_batch_failure_rolls_back_cards_and_pending_deletions(self):
        self.db.save_scan(snapshot(), self.current_revision())
        committed = self.db.load(include_pending=True)
        key = next(row['id'] for row in committed['pending_changes'] if row['kind'] == 'ship')
        with self.assertRaises(ValueError):
            self.db.review([dict(id=key, accept=True), dict(id='ship:missing', accept=True)],
                           self.current_revision(), committed['pending_revision'])
        self.assertEqual(self.db.load(include_pending=True), committed)
        with self.assertRaises(ValueError):
            self.db.review([dict(id=key, accept=False), dict(id=key, accept=False)],
                           self.current_revision(), committed['pending_revision'])
        self.assertEqual(self.db.load(include_pending=True), committed)

    def test_legacy_stage_is_once_only_and_does_not_apply_cards_or_technology(self):
        active = self.seed()
        converted = {'snapshot': snapshot('local'), 'mind': {'extra': [{'name': '本地', 'level': 100}]},
            'technology': {'manual': {'10102': {'owned': False}}, 'nations': {'1': 3}}}
        self.db.stage_legacy(converted, self.current_revision())
        staged = self.db.load(include_pending=True, include_import_status=True)
        self.assertEqual(staged['snapshot'], active['snapshot'])
        self.assertEqual(staged['technology'], active['technology'])
        self.assertTrue(staged['legacy_imported'])
        self.assertTrue(staged['pending_changes'])
        before = (self.db.path.read_bytes(), self.db.path.stat().st_mtime_ns)
        with self.assertRaises(FleetDatabaseAlreadyImported):
            self.db.stage_legacy(converted, self.current_revision())
        self.assertEqual((self.db.path.read_bytes(), self.db.path.stat().st_mtime_ns), before)

    def test_invalid_legacy_stage_rolls_back_candidates_and_import_marker(self):
        self.db.save_scan(snapshot(), self.current_revision())
        committed = self.db.load(include_pending=True, include_import_status=True)
        with self.assertRaises(ValueError):
            self.db.stage_legacy({'snapshot': snapshot('broken'),
                'technology': {'nations': {'1': 'invalid'}}}, self.current_revision())
        self.assertEqual(self.db.load(include_pending=True, include_import_status=True), committed)
        self.decide_all(False)
        self.db.stage_legacy({'snapshot': None, 'technology': {}}, self.current_revision())
        self.assertTrue(self.db.load(include_import_status=True)['legacy_imported'])

    def test_transaction_exception_rolls_back_partial_write(self):
        self.seed()
        committed = self.db.load(include_pending=True)
        with self.assertRaisesRegex(RuntimeError, 'cancelled'):
            with self.db._transaction() as connection:
                connection.execute("INSERT INTO nation_technology VALUES ('1', 3)")
                raise RuntimeError('cancelled')
        self.assertEqual(self.db.load(include_pending=True), committed)
        original = self.db._set_progress

        def fail_after_write(connection, gid, values, *, source):
            original(connection, gid, values, source=source)
            raise RuntimeError('storage failure')

        with patch.object(self.db, '_set_progress', side_effect=fail_after_write):
            with self.assertRaisesRegex(RuntimeError, 'storage failure'):
                set_technology(self.db, {'progress': {'10102': {'owned': False}}})
        self.assertEqual(self.db.load(include_pending=True), committed)

    def test_first_transaction_rollback_leaves_readable_empty_database(self):
        with self.assertRaisesRegex(RuntimeError, 'cancelled'):
            with self.db._transaction() as connection:
                connection.execute("INSERT INTO nation_technology VALUES ('1', 2)")
                raise RuntimeError('cancelled')
        self.assertEqual(self.db.load(include_pending=True), self.empty())
        self.assert_counts(ships=0, nation_technology=0)

    def test_read_recovers_hot_journal_after_crashed_editor(self):
        self.seed()
        set_technology(self.db, {'progress': {'10102': {'owned': True}}, 'nations': {'1': 2}})
        committed = self.db.load(include_pending=True)
        context = multiprocessing.get_context('spawn')
        process = context.Process(target=crash_editor_worker, args=(str(self.config),))
        process.start()
        self.addCleanup(lambda: process.terminate() if process.is_alive() else None)
        process.join(timeout=15)
        self.assertFalse(process.is_alive(), 'crashing editor deadlocked')
        self.assertEqual(process.exitcode, 23)
        journal = Path(str(self.db.path) + '-journal')
        self.assertTrue(journal.is_file())
        self.assertEqual(journal.read_bytes()[:8], bytes.fromhex('d9d505f920a163d7'))
        self.assertEqual(self.db.load(include_pending=True), committed)
        self.assertFalse(journal.exists())
        self.assert_counts(ships=3, nation_technology=1)

    def test_cross_process_editors_serialize_without_lost_updates(self):
        self.run_processes(increment_worker, [(15,), (15,), (15,)])
        self.assertEqual(self.db.load()['technology']['nations']['1'], 45)

    def test_cross_process_manual_updates_accept_only_one_expected_revision(self):
        context = multiprocessing.get_context('spawn')
        queue = context.Queue()
        self.addCleanup(queue.close)
        self.run_processes(patch_worker, [(revision({}), 'one', queue), (revision({}), 'two', queue)])
        self.assertEqual(sorted([queue.get(timeout=5), queue.get(timeout=5)]), ['conflict', 'saved'])
        self.assert_counts(ships=1)

    def test_cross_process_scans_only_replace_pending_reading_not_canonical_cards(self):
        context = multiprocessing.get_context('spawn')
        queue = context.Queue()
        self.addCleanup(queue.close)
        self.run_processes(scan_worker, [('one', queue), ('two', queue)])
        self.assertEqual(sorted([queue.get(timeout=5), queue.get(timeout=5)]), ['conflict', 'staged'])
        self.assertIsNone(self.db.load()['snapshot'])
        self.assertTrue(self.db.load(include_pending=True)['pending_changes'])
        self.assert_counts(ships=0)

    def test_cross_process_explicit_legacy_read_succeeds_only_once(self):
        context = multiprocessing.get_context('spawn')
        queue = context.Queue()
        self.addCleanup(queue.close)
        self.run_processes(import_worker, [('10102', queue), ('10103', queue)])
        self.assertEqual(sorted([queue.get(timeout=5), queue.get(timeout=5)]), ['already_imported', 'staged'])
        self.assertTrue(self.db.load(include_import_status=True)['legacy_imported'])
        self.assertIsNone(self.db.load()['snapshot'])
        self.assert_counts(ships=0)

    def test_missing_reads_ignore_local_json_and_create_nothing(self):
        self.config.write_text('{"DockScan":{"Dock":{"Result":{"ships":[1]}}}}')
        original = self.config.read_bytes()
        self.assertEqual(self.db.load(include_pending=True), self.empty())
        self.assertEqual(self.db.load(include_pending=True, include_import_status=True), self.empty(True))
        self.assertFalse(self.db.path.parent.exists())
        self.assertEqual(self.config.read_bytes(), original)
        self.assertEqual(self.db.path, self.config.parent / 'fleet' / 'pilot.sqlite3')

    def test_read_only_load_does_not_change_any_database_file(self):
        self.seed()
        self.db.save_scan(snapshot('next'), self.current_revision())
        before = {path.name: (path.read_bytes(), path.stat().st_mtime_ns)
                  for path in self.db.path.parent.iterdir()}
        for _ in range(3):
            self.db.load()
            self.assertFalse(self.db.load(include_pending=True, include_import_status=True)['legacy_imported'])
        after = {path.name: (path.read_bytes(), path.stat().st_mtime_ns)
                 for path in self.db.path.parent.iterdir()}
        self.assertEqual(before, after)

    def test_first_database_is_published_with_complete_empty_schema(self):
        original = os.link
        observed = []

        def publish(source, destination, **kwargs):
            observed.append(self.db.load(include_pending=True))
            original(source, destination, **kwargs)
            observed.append(self.db.load(include_pending=True))

        with patch('module.runtime.fleet_database.os.link', side_effect=publish):
            self.seed()
        self.assertEqual(observed, [self.empty()] * 2)
        self.assertEqual(len(self.db.load()['snapshot']['ships']), 3)
        self.assertEqual([path.name for path in self.db.path.parent.iterdir()], ['pilot.sqlite3'])

    def test_initial_schema_failure_never_publishes_incomplete_database(self):
        original = self.db._schema

        def fail_schema(connection, **kwargs):
            original(connection, **kwargs)
            raise RuntimeError('initialization failed')

        with patch.object(self.db, '_schema', side_effect=fail_schema):
            with self.assertRaisesRegex(RuntimeError, 'initialization failed'):
                with self.db._transaction():
                    pass
        self.assertFalse(self.db.path.exists())
        self.assertEqual(list(self.db.path.parent.iterdir()), [])
        self.assertEqual(self.db.load(include_pending=True), self.empty())

    def test_read_recovery_never_recreates_deleted_storage(self):
        error = sqlite3.OperationalError('attempt to write a readonly database')
        error.sqlite_errorcode = sqlite3.SQLITE_READONLY_ROLLBACK
        with patch.object(self.db, '_read_only', side_effect=[error, self.empty()]):
            self.assertEqual(self.db.load(include_pending=True), self.empty())
        self.assertFalse(self.db.path.parent.exists())

    def test_instances_have_separate_canonical_and_pending_data(self):
        other = FleetDatabase(self.config.with_name('other.json'))
        self.seed()
        self.assertEqual(other.load(include_pending=True), self.empty())
        other.save_scan(snapshot('other'), revision({}))
        self.assertFalse(self.db.load(include_pending=True)['pending_changes'])
        self.assertTrue(other.load(include_pending=True)['pending_changes'])
        self.assertIsNone(other.load()['snapshot'])
    def test_corrupt_and_unsupported_databases_are_not_reset(self):
        self.db.path.parent.mkdir()
        self.db.path.write_bytes(b'this is not sqlite')
        before = self.db.path.read_bytes()
        with self.assertRaises(sqlite3.DatabaseError):
            self.db.load()
        with self.assertRaises(sqlite3.DatabaseError):
            with self.db._transaction():
                pass
        self.assertEqual(self.db.path.read_bytes(), before)
        self.db.path.unlink()
        with closing(sqlite3.connect(self.db.path)) as connection, connection:
            connection.execute('PRAGMA user_version=999')
        before = self.db.path.read_bytes()
        with self.assertRaisesRegex(ValueError, '999'):
            self.db.load()
        with self.assertRaisesRegex(ValueError, '999'):
            self.seed()
        self.assertEqual(self.db.path.read_bytes(), before)


    def test_unversioned_existing_tables_are_not_overwritten(self):
        self.db.path.parent.mkdir()
        with closing(sqlite3.connect(self.db.path)) as connection, connection:
            connection.execute('CREATE TABLE existing (value TEXT)')
            connection.execute("INSERT INTO existing VALUES ('keep')")
        with self.assertRaisesRegex(ValueError, 'Unversioned|Unsupported.*0'):
            with self.db._transaction():
                pass
        with closing(sqlite3.connect(self.db.path)) as connection, connection:
            self.assertEqual(connection.execute('SELECT value FROM existing').fetchone()[0], 'keep')


    @unittest.skipUnless(supports_symlinks(), 'OS does not grant symbolic-link creation privileges')
    def test_refuses_directory_database_and_sidecar_symlinks(self):
        external = Path(self.temp.name) / 'external'
        external.mkdir()
        self.db.path.parent.symlink_to(external, target_is_directory=True)
        for action in (self.db.load, lambda: self.seed()):
            with self.assertRaisesRegex(ValueError, 'Unsafe'):
                action()
        self.assertEqual(list(external.iterdir()), [])
        self.db.path.parent.unlink()
        self.db.path.parent.mkdir()
        target = external / 'target.sqlite3'
        target.write_bytes(b'preserve')
        self.db.path.symlink_to(target)
        with self.assertRaisesRegex(ValueError, 'Unsafe'):
            self.db.load()
        with self.assertRaisesRegex(ValueError, 'Unsafe'):
            with self.db._transaction():
                pass
        self.db.path.unlink()
        self.seed()
        for suffix in ('-journal', '-wal', '-shm'):
            sidecar = Path(str(self.db.path) + suffix)
            sidecar.symlink_to(target)
            with self.assertRaisesRegex(ValueError, 'Unsafe'):
                self.db.load()
            with self.assertRaisesRegex(ValueError, 'Unsafe'):
                self.db.save_scan(snapshot('second'), self.current_revision())
            sidecar.unlink()
        self.assertEqual(target.read_bytes(), b'preserve')


    def test_refuses_windows_directory_junctions(self):
        self.db.path.parent.mkdir()
        # On Windows a junction's lstat mode is a directory. Simulate that
        # distinction so the rejection remains covered on POSIX CI too.
        with patch.object(Path, 'is_junction', return_value=True):
            with self.assertRaisesRegex(ValueError, 'Unsafe'):
                self.db.load()
            with self.assertRaisesRegex(ValueError, 'Unsafe'):
                self.seed()
            with self.assertRaisesRegex(ValueError, 'Unsafe'):
                with self.db._transaction():
                    pass
        self.assertEqual(list(self.db.path.parent.iterdir()), [])


    def run_processes(self, target, arguments):
        context = multiprocessing.get_context('spawn')
        barrier = context.Barrier(len(arguments))
        processes = [context.Process(target=target, args=(str(self.config), barrier, *args))
                     for args in arguments]
        for process in processes:
            process.start()
            self.addCleanup(lambda child=process: child.terminate() if child.is_alive() else None)
        for process in processes:
            process.join(timeout=30)
            self.assertFalse(process.is_alive(), 'database writer deadlocked')
            self.assertEqual(process.exitcode, 0)


if __name__ == '__main__':
    unittest.main()
