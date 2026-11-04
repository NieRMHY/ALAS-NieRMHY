"""Pure explicit import produces one ledger and preserves SQLite precedence."""
import copy
import unittest

from module.runtime import dock_data
from module.runtime.fleet_legacy import convert_legacy, sqlite_payload, _keyed, _mind_ships


def row(name='杜威', level=105, **kwargs):
    return dict(name=name, level=level, rarity='R', base_rarity='R', review=False, source='fixture', **kwargs)


def snapshot(level=105):
    return dock_data.build_snapshot([dict(row(level=level), group_type=10102)], min_level=1, max_level=125,
        reached_bottom=True, filters_clear=True, physical_count=1, expected_count=1, updated_at='2026-10-25T10:00:00')


class FleetLegacyTests(unittest.TestCase):
    def test_sources_merge_into_one_snapshot_with_dock_preferred_and_progress_retained(self):
        dock = snapshot()
        dock['ships'].append(dict(dock['ships'][0], slot=1))
        data = {'DockScan': {'Dock': {'Result': dock}}, 'MindCalculatorScan': {'MindCalculator': {
            'Result': {'ships': [row(level=110)], 'updated_at': '2026-10-25T11:00:00'},
            'FleetTechRecord': {'observed': {'10103': 125}, 'manual': {'10102': {'owned': True, 'level': 125}},
                                'nations': {'1': 3}, 'unrecognized': {'keep': True}}}},
            'FleetTechScan': {'FleetTech': {'Record': {'manual': {'10102': {'owned': False}},
                'current': {'10104': 120}, 'last_scan': {'ships': [[10104, 120]], 'complete': True,
                'reached_bottom': True, 'filters_clear': True, 'updated_at': '2026-10-25T12:00:00'}}}}}
        before = copy.deepcopy(data)
        result = convert_legacy(data)
        self.assertEqual(data, before)
        self.assertEqual(set(result), {'snapshot', 'mind', 'technology'})
        self.assertEqual(result['technology']['manual']['10102'], {'owned': False, 'level': 125})
        self.assertEqual(result['technology']['nations'], {'1': 3})
        active = result['snapshot']
        self.assertEqual(active['import_source'], 'legacy_dock')
        self.assertEqual(len(active['ships']), 2)
        self.assertEqual(active['history']['observed']['10103'], 125)
        self.assertEqual(active['history']['observed']['10104'], 120)
        payload = sqlite_payload(result)
        self.assertEqual(max(row['level'] for row in payload['ships']), 110)
        self.assertEqual(payload['technology']['10102'], dict(owned=False, full_star=False, lv120=False))
        self.assertTrue(payload['technology']['10103']['lv120'])
        self.assertEqual(payload['nations'], {'1': 3})

    def test_incomplete_full_stars_clear_only_dependent_ordinary_level_milestone(self):
        for gid, lv120 in [('10102', False), ('29901', True)]:
            with self.subTest(group_type=gid):
                payload = sqlite_payload({'technology': {'manual': {
                    gid: dict(level=120, full_star=False)}}})
                self.assertEqual(payload['technology'][gid], dict(owned=True, full_star=False, lv120=lv120))

    def test_explicit_mind_analysis_wins_over_legacy_result_derivation(self):
        original = snapshot()
        data = {'DockScan': {'Dock': {'Result': original}}, 'MindCalculatorScan': {'MindCalculator': {
            'Result': {'ships': [row(level=110)]},
            'Analysis': {'overrides': {'group:10102': {'excluded': True}}, 'removed': [],
                         'extra': [row(name='未知舰', level=0, excluded=False)],
                         'snapshot_revision': original['revision'], 'opaque_old_data': 'discard me'}}}}
        result = convert_legacy(data)
        rows = sqlite_payload(result)['ships']
        self.assertNotIn('opaque_old_data', result['mind'])
        self.assertEqual(rows[0]['level'], 105)
        self.assertNotIn('excluded', rows[0])
        self.assertEqual(rows[1]['name'], '未知舰')

    def test_newest_trustworthy_snapshot_is_preferred_without_dock(self):
        converted = convert_legacy({'MindCalculatorScan': {'MindCalculator': {'Result': {
            'ships': [row()], 'updated_at': 'invalid'}}}, 'FleetTechScan': {'FleetTech': {'Record': {
            'last_scan': {'ships': [[10103, 120]], 'updated_at': '2026-10-25T12:00:00'}}}}})
        self.assertEqual(converted['snapshot']['import_source'], 'legacy_technology')
        self.assertEqual(converted['snapshot']['ships'][0]['group_type'], 10103)

    def test_empty_and_malformed_inputs_are_rejected_without_mutation(self):
        cases = [{}, {'FleetTechScan': {'FleetTech': {'Record': {'manual': {'10102': {}}}}}}, {'DockScan': {'Dock': {'Result': {'ships': 'invalid'}}}},
                 {'FleetTechScan': {'FleetTech': {'Record': {'manual': {'10102': {'owned': 1}}}}}},
                 {'FleetTechScan': {'FleetTech': {'Record': {'observed': {'10102': 126}}}}},
                 {'MindCalculatorScan': {'MindCalculator': {'Analysis': {'overrides': {'x': {'level': True}}}}}}]
        for data in cases:
            before = copy.deepcopy(data)
            with self.subTest(data=data), self.assertRaises(ValueError):
                convert_legacy(data)
            self.assertEqual(data, before)

    def test_explicit_empty_saved_list_is_a_valid_current_snapshot(self):
        converted = convert_legacy({'MindCalculatorScan': {'MindCalculator': {'Result': {'ships': []}}}})
        self.assertEqual(converted['snapshot']['ships'], [])
        self.assertFalse(converted['snapshot']['complete'])

    def test_raw_positive_levels_cannot_be_lowered_by_old_history(self):
        dock = snapshot(125)
        dock['history'] = {'observed': {'10102': 100}}
        converted = convert_legacy({'DockScan': {'Dock': {'Result': dock}},
            'FleetTechScan': {'FleetTech': {'Record': {'observed': {'10103': 100},
                'last_scan': {'ships': [[10103, 125]]}}}}})
        self.assertEqual(converted['snapshot']['history']['observed']['10102'], 125)
        self.assertEqual(converted['snapshot']['history']['observed']['10103'], 125)

    def test_review_settings_stay_bound_to_their_original_snapshot(self):
        original = dock_data.build_snapshot([dict(row(name='未确认舰', level=0), review=True)],
            min_level=1, max_level=125, reached_bottom=True, filters_clear=True,
            physical_count=1, expected_count=1, updated_at='2026-10-25T10:00:00')
        key = next(_keyed(_mind_ships(original)))[0]
        data = {'DockScan': {'Dock': {'Result': original}}, 'MindCalculatorScan': {'MindCalculator': {
            'Analysis': {'overrides': {key: {'level': 105}}, 'snapshot_revision': 'stale'}}}}
        stale = sqlite_payload(convert_legacy(data))
        self.assertEqual(stale['ships'][0]['level'], 0)
        data['MindCalculatorScan']['MindCalculator']['Analysis']['snapshot_revision'] = original['revision']
        matching = sqlite_payload(convert_legacy(data))
        self.assertEqual(matching['ships'][0]['level'], 105)

    def test_numbered_review_overrides_bind_to_original_physical_cards(self):
        # The old calculator canonicalized both names to 杜威 and kept review copies
        # separately; its numbered keys must never be recomputed from edited rows.
        for raw_name in ('杜威', '未确认卡片'):
            with self.subTest(raw_name=raw_name):
                original = dock_data.build_snapshot([
                    dict(row(name=raw_name, level=0), group_type=10102, review=True),
                    dict(row(name='富特', level=50), group_type=10103),
                    dict(row(name=raw_name, level=80), group_type=10102, review=True)],
                    min_level=98, max_level=125, reached_bottom=True, filters_clear=True,
                    physical_count=3, expected_count=3, updated_at='2026-10-25T10:00:00')
                keys = [key for key, _ in _keyed(_mind_ships(original))]
                self.assertEqual(len(keys), 2)
                self.assertEqual(keys[1], keys[0] + ':1')
                data = {'DockScan': {'Dock': {'Result': original}}, 'MindCalculatorScan': {'MindCalculator': {
                    'Analysis': {'overrides': {keys[0]: {'name': '富特', 'level': 115, 'review': False},
                                               keys[1]: {'level': 95, 'source': '第二张的校正'}},
                                 'extra': [dict(row(name=raw_name, level=0), review=True)],
                                 'snapshot_revision': original['revision']}}}}
                before = copy.deepcopy(data)
                rows = sqlite_payload(convert_legacy(data))['ships']
                self.assertEqual([(item['name'], item['level']) for item in rows],
                                 [('富特', 115), ('富特', 50), (raw_name, 95), (raw_name, 0)])
                self.assertFalse(rows[0]['review'])
                self.assertEqual(rows[2]['source'], '第二张的校正')
                self.assertEqual(data, before)
                data['MindCalculatorScan']['MindCalculator']['Analysis']['snapshot_revision'] = 'stale'
                stale = sqlite_payload(convert_legacy(data))['ships']
                self.assertEqual([item['level'] for item in stale], [0, 50, 80, 0])

    def test_unknown_manual_extra_without_snapshots_remains_visible(self):
        data = {'MindCalculatorScan': {'MindCalculator': {'Analysis': {'extra': [
            dict(row(name='未确认的人工舰', level=0), review=True)]}}}}
        converted = convert_legacy(data)
        self.assertIsNone(converted['snapshot'])
        rows = sqlite_payload(converted)['ships']
        self.assertEqual(rows[0]['name'], '未确认的人工舰')
        self.assertTrue(rows[0]['review'])

    def test_empty_analysis_is_not_useful_import_data(self):
        with self.assertRaises(ValueError):
            convert_legacy({'MindCalculatorScan': {'MindCalculator': {'Analysis': {
                'overrides': {}, 'removed': [], 'extra': [], 'updated_at': '2026-10-25T12:00:00'}}}})


if __name__ == '__main__':
    unittest.main()
