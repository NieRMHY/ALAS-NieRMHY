"""Account milestones survive retirement, migration and unconfirmed readings."""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from module.runtime import dock_data, fleet_tech as tech
from module.runtime.fleet_database import FleetDatabase, FleetDatabaseConflict


class AccountProgressTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.database = FleetDatabase(Path(temporary.name) / 'pilot.json')

    def revision(self):
        return dock_data.read_snapshot(self.database.load())['revision']

    def record(self):
        return dock_data.technology_record(self.database.load())

    def patch_tech(self, changes):
        self.database.patch_technology(changes, {}, tech.revision(self.record()))

    def row(self, gid=10102):
        return tech.progress(self.record(), gid)

    def v3(self, cards, legacy=()):
        self.database.path.parent.mkdir()
        with closing(sqlite3.connect(self.database.path)) as connection, connection:
            connection.executescript(Path(__file__).with_name('fixtures').joinpath('fleet_schema_v3.sql').read_text())
            connection.execute("INSERT INTO fleet_info (id, revision, updated_at) VALUES (1, ?, 'before')", ('a' * 64,))
            for index, (gid, level) in enumerate(cards):
                connection.execute('INSERT INTO ships (position, group_type, name, level, rarity, base_rarity, '
                    'extra_exp, excluded, review, source) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                    (index, gid, 'migration copy', level, 'R', 'R', None if index % 2 else index,
                     index % 2, 0, f'original:{index}'))
            for values in legacy:
                connection.execute('INSERT INTO technology (group_type, max_observed_level, manual_fields, full_star) '
                                   'VALUES (?, ?, ?, ?)', values)
            connection.execute('PRAGMA user_version=3')
            return connection.execute('SELECT * FROM ships ORDER BY id').fetchall()

    def test_old_sqlite_versions_are_rejected_without_modifying_data(self):
        self.v3([(10102, 120)])
        for version in (3, 4, 5, 6, 7, 8):
            with self.subTest(version=version):
                with closing(sqlite3.connect(self.database.path)) as connection, connection:
                    connection.execute(f'PRAGMA user_version={version}')
                before = self.database.path.read_bytes()
                with self.assertRaisesRegex(ValueError, f'version: {version}'):
                    self.database.load()
                with self.assertRaisesRegex(ValueError, f'version: {version}'):
                    with self.database._transaction():
                        pass
                self.assertEqual(self.database.path.read_bytes(), before)

    def test_research_and_meta_levels_do_not_prove_full_stars(self):
        self.database.patch_cards([dict(group_type=29901, name='海王星', level=125),
                                   dict(group_type=970101, name='猎人·META', level=125),
                                   dict(group_type=10517, name='新泽西', level=125)], self.revision())
        for gid in (29901, 970101, 10517):
            self.assertFalse(self.row(gid)['full_star'])
            self.assertTrue(self.row(gid)['lv120'])
            self.assertEqual(self.row(gid)['status'], 'unfinished')
        cards = self.database.load()['snapshot']['ships']
        self.database.patch_cards([dict(id=row['id'], full_star=True) for row in cards], self.revision())
        for gid in (29901, 970101, 10517):
            self.assertFalse(self.row(gid)['full_star'])
        self.patch_tech([dict(group_type=gid, lv120=True) for gid in (29901, 970101, 10517)])
        for gid in (29901, 970101, 10517):
            self.assertFalse(self.row(gid)['full_star'])
        self.patch_tech([dict(group_type=gid, full_star=True) for gid in (29901, 970101, 10517)])
        for gid in (29901, 970101, 10517):
            self.assertTrue(self.row(gid)['full_star'])

    def test_manual_positive_milestones_fill_only_omitted_prerequisites(self):
        self.patch_tech([dict(group_type=10102, full_star=True)])
        self.assertEqual([self.row()[key] for key in tech.MILESTONES], [True, True, False])
        self.patch_tech([dict(group_type=10102, full_star=False, owned=False)])
        self.patch_tech([dict(group_type=10102, lv120=True)])
        self.assertEqual([self.row()[key] for key in tech.MILESTONES], [True, True, True])
        self.patch_tech([dict(group_type=10102, owned=False)])
        self.assertEqual([self.row()[key] for key in tech.MILESTONES], [False, False, False])
        self.patch_tech([dict(group_type=10102, lv120=False)])
        self.assertEqual([self.row()[key] for key in tech.MILESTONES], [False, False, False])
        self.patch_tech([dict(group_type=10102, owned=False, full_star=False, lv120=True)])
        self.assertEqual([self.row()[key] for key in tech.MILESTONES], [False, False, False])

    def test_manual_final_milestones_survive_reload_and_dependency_cancellations(self):
        for mask in range(8):
            values = {key: bool(mask & (1 << index)) for index, key in enumerate(tech.MILESTONES)}
            with self.subTest(values=values):
                self.patch_tech([dict(group_type=10102, **values)])
                if not values['owned']:
                    values.update(full_star=False, lv120=False)
                elif not values['full_star']:
                    values['lv120'] = False
                self.assertEqual({key: self.row()[key] for key in tech.MILESTONES}, values)
                report = tech.report(self.record())
                self.assertEqual(report['milestone_counts'], {key: int(value) for key, value in values.items()})
                self.assertEqual(report['confirmed_points'],
                                 3 * values['owned'] + 7 * values['full_star'] + 5 * values['lv120'])
                bonus = int(values['owned']) + int(values['lv120'])
                self.assertEqual(report['ship_bonuses'], {'1': {'1': bonus}} if bonus else {})
                for key in tech.MILESTONES:
                    self.patch_tech([dict(group_type=10102, **values)])
                    self.patch_tech([dict(group_type=10102, **{key: False})])
                    self.assertEqual({field: self.row()[field] for field in tech.MILESTONES},
                                     {field: False for field in tech.MILESTONES} if key == 'owned'
                                     else dict(values, full_star=False, lv120=False) if key == 'full_star'
                                     else dict(values, **{key: False}))

    def test_card_full_star_changes_do_not_override_independent_correction(self):
        self.database.patch_cards([dict(group_type=10102, name='杜威', level=99, full_star=True)], self.revision())
        self.assertTrue(self.row()['full_star'])
        self.database.patch_cards([dict(id=1, full_star=False)], self.revision())
        self.assertEqual(self.row()['evidence']['full_star'], [])
        self.assertTrue(self.row()['full_star'])
        self.patch_tech([dict(group_type=10102, full_star=False)])
        self.database.patch_cards([dict(id=1, full_star=True)], self.revision())
        self.assertFalse(self.row()['full_star'])
        self.assertEqual(self.row()['evidence']['full_star'], [1])
        self.patch_tech([dict(group_type=10102, full_star=True)])
        self.assertTrue(self.row()['full_star'])

    def test_常规舰船满星包含100级且保留其他等级与特殊舰规则(self):
        for level, expected in [(0, None), (69, False), (70, None), (99, None), (100, True), (101, True)]:
            with self.subTest(level=level):
                self.assertIs(tech.full_star_state(dict(group_type=10102, level=level)), expected)
        self.assertTrue(tech.full_star_state(dict(group_type=10102, level=100, full_star=False)))
        self.assertIsNone(tech.full_star_state(dict(group_type=10102, level=100, review=True)))
        for gid in (29901, 970101, 10517):
            with self.subTest(group_type=gid):
                self.assertIsNone(tech.full_star_state(dict(group_type=gid, level=100)))
        self.database.patch_cards([dict(group_type=10102, name='杜威', level=100)], self.revision())
        self.assertTrue(self.database.load()['snapshot']['ships'][0]['full_star'])

    def test_retirement_preserves_progress_and_manual_correction_stays_corrected(self):
        self.database.patch_cards([dict(group_type=10102, name='杜威', level=120)], self.revision())
        card_id = self.database.load()['snapshot']['ships'][0]['id']
        self.patch_tech([dict(group_type=10102, lv120=False)])
        self.assertFalse(self.row()['lv120'])
        self.database.patch_cards([dict(id=card_id, delete=True)], self.revision())
        self.assertFalse(self.row()['lv120'])
        self.assertEqual(self.row()['current_count'], 0)
        self.patch_tech([dict(group_type=10102, lv120=False)])
        self.database.patch_cards([dict(group_type=10103, name='卡辛', level=125)], self.revision())
        self.assertFalse(self.row()['lv120'])

    def test_identity_correction_leaves_new_type_incomplete_and_retains_old_history(self):
        self.database.patch_cards([dict(group_type=10102, name='杜威', level=120)], self.revision())
        self.database.patch_cards([dict(id=1, group_type=10103, name='卡辛')], self.revision())
        self.assertFalse(self.row(10103)['lv120'])
        self.assertFalse(self.row(10103)['owned'])
        self.assertTrue(self.row(10102)['lv120'])
        self.assertEqual(self.row(10102)['current_count'], 0)

    def test_unconfirmed_import_does_not_change_stats_or_overwrite_existing_pending(self):
        before = tech.report(self.record())
        self.database.stage_import([dict(name='杜威', level=120)], self.revision())
        staged = self.database.load(include_pending=True)
        self.assertEqual(tech.report(self.record()), before)
        with self.assertRaises(FleetDatabaseConflict):
            self.database.stage_import([dict(name='卡辛', level=125)], self.revision())
        self.assertEqual(self.database.load(include_pending=True), staged)
        self.database.review([dict(id=row['id'], accept=False) for row in staged['pending_changes']],
                             self.revision(), staged['pending_revision'])
        self.assertEqual(tech.report(self.record()), before)

    def test_count_mismatch_and_partial_read_cannot_propose_removals(self):
        self.database.patch_cards([dict(group_type=10102, name='杜威', level=100),
                                   dict(group_type=10103, name='卡辛', level=120)], self.revision())
        for proof in (dict(physical_count=2, expected_count=2),
                      dict(physical_count=1, expected_count=1, min_level=100)):
            metadata = dict(min_level=1, max_level=125, reached_bottom=True, filters_clear=True,
                            physical_count=1, expected_count=1, updated_at='proof')
            metadata.update(proof)
            snapshot = dock_data.build_snapshot([dict(group_type=10102, name='杜威', level=101)], **metadata)
            self.database.save_scan(snapshot, self.revision())
            state = self.database.load(include_pending=True)
            self.assertFalse(any(row['operation'] == 'remove' for row in state['pending_changes']))
            self.assertFalse(state['pending_read']['complete'])
            self.database.review([dict(id=row['id'], accept=False) for row in state['pending_changes']],
                                 self.revision(), state['pending_revision'])


    def test_initial_seed_only_confirms_positive_facts_and_never_reseeds(self):
        self.database.patch_cards([dict(group_type=10102, name='杜威', level=50)], self.revision())
        self.assertTrue(self.row()['owned'])
        self.assertFalse(self.row()['full_star'])
        self.assertFalse(self.row()['lv120'])
        self.database.patch_cards([dict(id=1, level=120),
                                   dict(group_type=10103, name='卡辛', level=120)], self.revision())
        self.assertFalse(self.row()['full_star'])
        self.assertFalse(self.row()['lv120'])
        self.assertFalse(self.row(10103)['owned'])

    def test_manual_milestones_before_first_ledger_prevent_automatic_seeding(self):
        self.patch_tech([dict(group_type=10102, owned=False, full_star=False, lv120=False)])
        self.database.patch_cards([dict(group_type=10102, name='杜威', level=120),
                                   dict(group_type=10103, name='卡辛', level=120)], self.revision())
        for gid in (10102, 10103):
            self.assertTrue(all(self.row(gid)[key] is False for key in tech.MILESTONES))

    def test_confirming_dock_scan_changes_cards_without_proposing_or_updating_milestones(self):
        self.database.patch_cards([dict(group_type=10102, name='杜威', level=100)], self.revision())
        before = self.record()['progress']
        snapshot = dock_data.build_snapshot([dict(group_type=10102, name='杜威', level=120)],
            min_level=1, max_level=125, physical_count=1, expected_count=None,
            reached_bottom=False, filters_clear=False, updated_at='scan')
        self.database.save_scan(snapshot, self.revision())
        state = self.database.load(include_pending=True)
        self.assertTrue(all(row['kind'] == 'ship' for row in state['pending_changes']))
        self.database.review([dict(id=row['id'], accept=True) for row in state['pending_changes']],
                             self.revision(), state['pending_revision'])
        self.assertEqual(self.database.load()['snapshot']['ships'][0]['level'], 120)
        self.assertEqual(self.record()['progress'], before)

    def test_explicit_technology_confirmation_ignores_current_card_conflicts(self):
        self.database.patch_cards([dict(group_type=10102, name='杜威', level=120)], self.revision())
        self.database.stage_legacy(dict(snapshot=None, technology=dict(manual={
            '10102': dict(owned=False)})), self.revision())
        state = self.database.load(include_pending=True)
        self.assertEqual([row['kind'] for row in state['pending_changes']], ['technology'])
        self.database.review([dict(id=row['id'], accept=True) for row in state['pending_changes']],
                             self.revision(), state['pending_revision'])
        self.assertTrue(all(self.row()[key] is False for key in tech.MILESTONES))

    def test_explicit_union_only_adds_confirmed_current_facts_and_is_idempotent(self):
        self.patch_tech([dict(group_type=10102, owned=False),
                         dict(group_type=10103, full_star=True),
                         dict(group_type=10104, owned=False)])
        self.database.patch_cards([
            dict(group_type=10102, name='杜威', level=120),
            dict(group_type=10104, name='麦考尔', level=120, review=True),
            dict(name='未识别舰船', level=120, review=True),
            dict(group_type=10105, name='格里德利', level=50)], self.revision())
        self.database.merge_ship_technology(tech.revision(self.record()))
        self.assertTrue(all(self.row()[key] is True for key in tech.MILESTONES))
        self.assertTrue(self.row(10103)['full_star'])
        self.assertFalse(self.row(10104)['owned'])
        self.assertTrue(self.row(10105)['owned'])
        self.assertFalse(self.row(10105)['full_star'])
        self.assertFalse(self.row(10105)['lv120'])
        before = self.database.load(include_pending=True)
        self.database.merge_ship_technology(tech.revision(self.record()))
        self.assertEqual(self.database.load(include_pending=True), before)

    def test_explicit_union_rejects_stale_ship_or_technology_revision(self):
        stale = tech.revision(self.record())
        self.database.patch_cards([dict(group_type=10102, name='杜威', level=120)], self.revision())
        before = self.database.load(include_pending=True)
        with self.assertRaises(FleetDatabaseConflict):
            self.database.merge_ship_technology(stale)
        self.assertEqual(self.database.load(include_pending=True), before)
        stale = tech.revision(self.record())
        self.patch_tech([dict(group_type=10102, lv120=False)])
        with self.assertRaises(FleetDatabaseConflict):
            self.database.merge_ship_technology(stale)


if __name__ == '__main__':
    unittest.main()
