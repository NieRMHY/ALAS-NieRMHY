"""Per-copy projections do not merge cards or write confirmed facts."""
import copy
import unittest

from module.api.protocol import ApiError, CultivationParams
from module.runtime.fleet_cultivation import project, rules


def card(id=1, level=100, **values):
    return dict(id=id, group_type=10706, name='企业', level=level, rarity='SSR', base_rarity='SSR',
                review=False, **values)


class CultivationTests(unittest.TestCase):
    def test_duplicates_are_explicit_and_inputs_unchanged(self):
        cards = [card(), card(2)]
        before = copy.deepcopy(cards)
        result = project(cards, [1, 2])
        self.assertEqual(result['included'], 2)
        self.assertEqual(result['mind'], 4400)
        self.assertEqual([row['id'] for row in result['ships']], [1, 2])
        self.assertEqual(cards, before)

    def test_target_125_and_ur_costs_from_rules(self):
        self.assertEqual(rules()['awaken']['120']['SSR'], {'gold': 3000, 'mind': 300, 'mind2': 150})
        result = project([card(level=120)], [1], 125)
        self.assertEqual((result['mind'], result['mind2'], result['gold']), (300, 150, 3000))
        ur = card(level=120)
        ur.update(group_type=10517, name='新泽西', rarity='UR', base_rarity='UR')
        result = project([ur], [1], 125)
        self.assertEqual(result['mind2'], 225)

    def test_resource_only_calculation_uses_confirmed_boundary(self):
        row = project([card(level=120)], [1], 125)['ships'][0]
        self.assertNotIn('experience', row)
        self.assertNotIn('experience_upper', row)
        self.assertEqual((row['mind'], row['mind2'], row['gold']), (300, 150, 3000))
        self.assertEqual(row['status'], 'exact')

    def test_actual_level_and_fixed_boundary_cannot_mutate_input(self):
        cards = [card(level=100)]
        row = project(cards, [1], 120)['ships'][0]
        self.assertEqual((row['current_level'], row['level']), (100, 100))
        self.assertEqual((row['mind'], row['gold']), (2200, 22000))
        self.assertEqual(cards[0]['level'], 100)

    def test_bad_ids_and_removed_trial_params_rejected(self):
        for ids in ([1, 1], [2]):
            with self.assertRaises(ApiError):
                project([card()], ids)
        with self.assertRaises(ValueError):
            CultivationParams(instance='alas', revision='a' * 64, ship_ids=[1],
                              assumptions=[dict(ship_id=1, awakened_to=105)])

    def test_unknown_identity_and_completed_target(self):
        bad = card()
        bad['review'] = True
        result = project([bad, card(2, 125)], [1, 2], 125)
        self.assertEqual(result['unknown'], 1)
        self.assertEqual(result['ships'][1]['gold'], 0)
        self.assertEqual(result['mind'], 0)

    def test_unknown_identity_and_stale_rarity_do_not_produce_exact_totals(self):
        for change in (dict(name='未知舰', group_type=None), dict(group_type=10102), dict(base_rarity='N')):
            value = card()
            value.update(change)
            result = project([value], [1])
            self.assertEqual(result['unknown'], 1)
            self.assertEqual(result['mind'], 0)

    def test_resource_costs_use_confirmed_levels(self):
        result = project([card(level=119)], [1])
        self.assertEqual((result['mind'], result['gold']), (0, 0))
        self.assertEqual(result['mind_costs_100_to_120']['SSR'], 2200)
        self.assertEqual(result['ships'][0]['status'], 'exact')
        self.assertGreater(project([card(level=110)], [1])['mind'], 0)

    def test_confirmed_group_disambiguates_raw_names(self):
        from module.runtime.mind_calculator import find_ships
        matches = find_ships('约克')
        self.assertGreater(len(matches), 1)
        for info in matches:
            value = card()
            value.update(name='约克', group_type=info['group_type'], base_rarity=info['base_rarity'])
            self.assertEqual(project([value], [1])['unknown'], 0)

    def test_schema_bounds(self):
        CultivationParams(instance='alas', revision='a' * 64, ship_ids=[1], target_level=125)
        with self.assertRaises(ValueError):
            CultivationParams(instance='alas', revision='a' * 64, ship_ids=[1], target_level=126)
