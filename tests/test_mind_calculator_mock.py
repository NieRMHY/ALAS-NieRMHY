"""Browser mock helpers exercise the independent database used by real services."""
import unittest

from dev_tools.mind_calculator_mock import dispatch
from module.runtime import dock_data
from module.api.protocol import ApiError


class MindCalculatorMockTest(unittest.TestCase):
    def test_technology_patch_roundtrip_is_independent_of_mind_list(self):
        request = dict(instance='fixture', record={}, ships=[dict(name='杜威', level=125)])
        initial = dispatch(dict(request, action='tech.report'))
        self.assertFalse(next(row for row in initial['result']['ships'] if row['group_type'] == 10102)['owned'])
        saved = dispatch(dict(request, action='tech.patch', revision=initial['result']['revision'],
                              changes=[dict(group_type=10102, owned=True, full_star=False)], nations={'1': 2}))
        self.assertTrue(saved['record']['progress']['10102']['owned'])
        reloaded = dispatch(dict(request, action='tech.report', state=saved['state']))
        self.assertEqual(reloaded['state']['_database'], saved['state']['_database'])
        self.assertEqual(reloaded['result']['nation_levels']['1'], 2)
        row = next(row for row in reloaded['result']['ships'] if row['group_type'] == 10102)
        self.assertIsNone(row['current_level'])
        self.assertEqual((row['owned'], row['full_star']), (True, False))

    def test_confirmed_fixture_keeps_manual_progress_independent_of_ledger_evidence(self):
        snapshot = dock_data.build_snapshot([dict(group_type=10102, name='杜威', level=125)],
            min_level=1, max_level=125, reached_bottom=True, filters_clear=True,
            physical_count=1, expected_count=1, updated_at='2026-10-25T12:00:00')
        output = dispatch(dict(action='tech.report', instance='fixture', snapshot=snapshot,
                               record={'progress': {'10102': {'owned': False, 'full_star': False, 'lv120': False}}}))
        row = next(row for row in output['result']['ships'] if row['group_type'] == 10102)
        self.assertFalse(row['owned'])
        self.assertNotIn('manual_state', row)
        self.assertEqual(row['current_level'], 125)
        self.assertEqual(row['evidence']['lv120'], [1])
        self.assertFalse(row['lv120'])

    def test_explicit_merge_roundtrips_database_and_preserves_retired_milestones(self):
        request = dict(instance='fixture')
        empty = dispatch(dict(request, action='dock.report'))
        seeded = dispatch(dict(request, action='dock.patch', state=empty['state'],
            revision=empty['result']['revision'], changes=[dict(name='杜威', group_type=10102,
                level=100, full_star=False, rarity='R', base_rarity='R')]))
        updated = dispatch(dict(request, action='dock.patch', state=seeded['state'],
            revision=seeded['result']['revision'], changes=[dict(id=seeded['result']['ships'][0]['id'],
                level=120, full_star=True)]))
        report = dispatch(dict(request, action='tech.report', state=updated['state']))
        row = next(row for row in report['result']['ships'] if row['group_type'] == 10102)
        self.assertFalse(row['lv120'])
        self.assertEqual(row['current_level'], 120)
        merged = dispatch(dict(request, action='tech.mergeShips', state=report['state'],
            revision=report['result']['revision']))
        reloaded = dispatch(dict(request, action='tech.report', state=merged['state']))
        self.assertEqual(reloaded['state']['_database'], merged['state']['_database'])
        row = next(row for row in reloaded['result']['ships'] if row['group_type'] == 10102)
        self.assertEqual((row['owned'], row['full_star'], row['lv120']), (True, True, True))
        dock = dispatch(dict(request, action='dock.report', state=reloaded['state']))
        retired = dispatch(dict(request, action='dock.patch', state=dock['state'],
            revision=dock['result']['revision'], changes=[dict(id=dock['result']['ships'][0]['id'], delete=True)]))
        final = dispatch(dict(request, action='tech.report', state=retired['state']))
        row = next(row for row in final['result']['ships'] if row['group_type'] == 10102)
        self.assertEqual((row['lv120'], row['current_count'], row['evidence']['lv120']), (True, 0, []))

    def test_explicit_local_read_roundtrips_pending_changes_until_individual_review(self):
        def snapshot(level):
            return dock_data.build_snapshot([dict(group_type=10102, name='杜威', level=level)],
                min_level=1, max_level=125, reached_bottom=True, filters_clear=True,
                physical_count=1, expected_count=1, updated_at='2026-10-25T12:00:00')

        local = {
            'DockScan': {'Dock': {'MinLevel': 1, 'MaxLevel': 125, 'Result': snapshot(125)}},
            'MindCalculatorScan': {'MindCalculator': {
                'Result': {'ships': [{'name': '杜威', 'level': 110}]},
                'Analysis': {'overrides': {'group:10102': {'excluded': True}}, 'removed': [], 'extra': []},
                'FleetTechRecord': {'observed': {'10103': 120}, 'manual': {'10103': {'full_star': False}}},
            }},
            'FleetTechScan': {'FleetTech': {'Record': {'observed': {'10104': 125},
                'manual': {'10102': {'owned': True}}, 'nations': {'1': 3}}}},
        }
        request = dict(instance='fixture', config=local)
        blank = dispatch(dict(request, action='dock.report'))
        self.assertEqual(blank['result']['ships'], [])
        self.assertFalse(blank['result']['legacy_imported'])
        self.assertEqual(blank['config'], local)
        current = dict(snapshot=snapshot(100), mind={'overrides': {'group:10102': {'level': 115}}},
                       technology={'progress': {'10102': {'owned': False, 'full_star': False, 'lv120': False}}, 'nations': {'1': 1}})
        report = dispatch(dict(request, action='dock.report', state=current))
        migrated = dispatch(dict(request, action='dock.importLegacy', state=report['state'],
                                 revision=report['result']['revision']))
        self.assertTrue(migrated['state']['legacy_imported'])
        self.assertEqual(migrated['result']['ships'], report['result']['ships'])
        self.assertEqual(migrated['result']['revision'], report['result']['revision'])
        self.assertEqual(migrated['state']['technology'], report['state']['technology'])
        self.assertEqual(migrated['config'], local)
        pending = migrated['result']['pending_changes']
        self.assertEqual({row['kind'] for row in pending}, {'ship', 'technology', 'nation'})
        persisted = dict(instance='fixture', config=migrated['config'], state=migrated['state'])
        reloaded = dispatch(dict(persisted, action='dock.report'))
        self.assertEqual(reloaded['state']['_database'], migrated['state']['_database'])
        self.assertEqual(reloaded['result']['pending_changes'], pending)
        before_review = dispatch(dict(persisted, action='dock.report'))['result']
        self.assertEqual(before_review['ships'][0]['level'], 100)
        # Accept the card and converted achievements, including old manual
        # corrections, while rejecting ownership and nation changes separately.
        decisions = [dict(id=row['id'], accept=row['id'] not in ('technology:10102', 'nation:1'))
                     for row in pending]
        reviewed = dispatch(dict(persisted, action='dock.review', revision=migrated['result']['revision'],
            pending_revision=migrated['result']['pending_revision'], decisions=decisions))
        self.assertEqual(reviewed['result']['pending_changes'], [])
        self.assertEqual(reviewed['config'], local)
        persisted['state'] = reviewed['state']
        mind = dispatch(dict(persisted, action='dock.report'))['result']
        self.assertEqual(mind['ships'][0]['level'], 125)
        tech = dispatch(dict(persisted, action='tech.report'))['result']
        rows = {row['group_type']: row for row in tech['ships']}
        self.assertFalse(rows[10102]['owned'])
        self.assertEqual(rows[10102]['current_level'], 125)
        self.assertTrue(rows[10103]['owned'])
        self.assertFalse(rows[10103]['full_star'])
        self.assertFalse(rows[10103]['lv120'])
        self.assertTrue(rows[10104]['lv120'])
        self.assertEqual(rows[10103]['current_count'], 0)
        self.assertEqual(tech['nation_levels']['1'], 1)
        with self.assertRaises(ApiError) as error:
            dispatch(dict(persisted, action='dock.importLegacy', revision=reviewed['result']['revision']))
        self.assertEqual(error.exception.code, 'ALREADY_IMPORTED')
