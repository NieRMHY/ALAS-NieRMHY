"""心智重名群组、原生卡片、人工确认及科技导入的离线回归。"""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image

from module.api.config_service import ConfigService
from module.api.dock_service import DockService
from module.api.mind_calculator_service import MindCalculatorService, import_ships
from module.runtime.mind_calculator import find_ship, find_ships, highest_ships
from module.runtime.mind_name import match_lua_name
from module.runtime.mind_recognition import _match_name, recognize_cards
from tests.test_api import fixture

FIXTURES = Path(__file__).parent / 'fixtures'


def ship(name, level=100, **values):
    return dict(name=name, level=level, rarity='SSR', **values)


class SameNameTests(unittest.TestCase):
    def test_catalog_preserves_every_same_name_group_and_original_rarity(self):
        for name, expected in [('天城', {30405: 'SSR', 30715: 'UR'}),
                               ('加贺', {30507: 'SSR', 30702: 'SSR'}),
                               ('约克', {20307: 'SR', 40311: 'SR'}),
                               ('新月', {20109: 'N', 30156: 'SR'}),
                               ('霞', {30181: 'SR', 1060003: 'SSR'})]:
            with self.subTest(name=name):
                self.assertIsNone(find_ship(name))
                self.assertEqual({row['group_type']: row['base_rarity'] for row in find_ships(name)}, expected)
                for row in find_ships(name):
                    self.assertEqual(find_ship(row['name']), row)

    def test_aircraft_and_surface_icons_distinguish_same_names_without_rarity_guessing(self):
        for name, aviation, surface in [('天城', 30715, 30405), ('加贺', 30702, 30507)]:
            for matcher in (_match_name, match_lua_name):
                with self.subTest(name=name, matcher=matcher.__name__):
                    self.assertIsNone(matcher([name] * 3, 'UR')[0])
                    self.assertEqual(matcher([name] * 3, 'SR', aviation=True)[0]['group_type'], aviation)
                    self.assertEqual(matcher([name] * 3, 'UR', surface=True)[0]['group_type'], surface)
                    self.assertIsNone(matcher([name] * 3, '', aviation=True, surface=True)[0])
                    self.assertIsNone(matcher([name], '', aviation=True)[0])

    def test_york_and_crescent_are_ambiguous_even_with_matching_rarity(self):
        for name in ('约克', '新月'):
            for rarity in ('N', 'SR', 'SSR', ''):
                for matcher in (_match_name, match_lua_name):
                    with self.subTest(name=name, rarity=rarity, matcher=matcher.__name__):
                        info, note = matcher([name] * 3, rarity)
                        self.assertIsNone(info)
                        self.assertIn('同名同舰种', note)
        self.assertEqual(find_ship('新月.改')['group_type'], 20109)
        self.assertEqual(find_ship('约克.改')['group_type'], 20307)

    def test_qualified_original_retrofit_and_meta_merge_only_the_same_identity(self):
        rows = [ship('天城（战巡）'), ship('天城（正航）'), ship('加贺（战列）'), ship('加贺（正航）'),
                ship('新月（皇家）'), ship('新月.改', 106), ship('新月（重樱）'),
                ship('约克（皇家）'), ship('约克.改', 106), ship('约克（铁血）')]
        highest = highest_ships(rows)
        self.assertEqual(len(highest), 8)

    def test_legacy_ambiguous_rows_remain_separate_unbilled_and_read_only(self):
        rows = [ship(name) for name in ('新月', '新月', '约克', '约克', '天城', '加贺')]
        before = copy.deepcopy(rows)
        self.assertEqual(len(highest_ships(rows)), len(rows))
        self.assertEqual(rows, before)
        with tempfile.TemporaryDirectory() as directory:
            configs = ConfigService(fixture(directory))
            dock = DockService(configs)
            path = configs.path('testpilot')
            data = json.loads(path.read_text())
            data['MindCalculatorScan'] = {'MindCalculator': {'Result': {'ships': rows}}}
            path.write_text(json.dumps(data), encoding='utf-8')
            saved = path.read_bytes()
            initial = dock.report('testpilot')
            self.assertEqual(initial['ships'], [])
            pending = dock.import_legacy('testpilot', initial['revision'])
            self.assertEqual(pending['ships'], [])
            self.assertEqual(len(pending['pending_changes']), 6)
            dock.review('testpilot', pending['revision'], pending['pending_revision'],
                        [dict(id=row['id'], accept=True) for row in pending['pending_changes']])
            report = dock.report('testpilot')
            self.assertEqual(sum(row['review'] for row in report['ships']), 6)
            plan = MindCalculatorService(configs).plan('testpilot', report['revision'],
                [row['id'] for row in report['ships']], 120)
            self.assertEqual((plan['unknown'], plan['mind'], plan['mind2'], plan['gold']), (6, 0, 0, 0))
            self.assertEqual(configs.path('testpilot').read_bytes(), saved)

    def test_qualified_names_keep_identity_through_import_and_dock_edits(self):
        import base64
        import json
        rows = [ship('新月（皇家）', 106), ship('新月（重樱）', 110),
                ship('约克（皇家）'), ship('约克（铁血）'),
                ship('加贺（战列）'), ship('加贺（正航）'), ship('约克', review=True)]
        imported = import_ships('ships.json', base64.b64encode(json.dumps(rows).encode()).decode())
        with tempfile.TemporaryDirectory() as directory:
            dock = DockService(ConfigService(fixture(directory)))
            saved = dock.patch('testpilot', dock.report('testpilot')['revision'], imported)
            self.assertEqual([row['name'] for row in saved['ships']], [row['name'] for row in rows])
            self.assertEqual({row['group_type']: row['level'] for row in saved['ships'] if not row['review']},
                             {20109: 106, 30156: 110, 20307: 100, 40311: 100, 30507: 100, 30702: 100})
            self.assertTrue(saved['ships'][-1]['review'])


class NativeSameNameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cards = {}
        for label, rows in [('amagi', [75]), ('kaga', [77]), ('york', None), ('crescent', None)]:
            cls.cards[label] = recognize_cards(Image.open(FIXTURES / f'fleet_tech_{label}.png'), row_origins=rows)

    def test_native_amagi_and_kaga_cards_keep_both_groups_and_original_rarity(self):
        for label, expected in [('amagi', {30715: 'UR', 30405: 'SSR'}), ('kaga', {30507: 'SSR', 30702: 'SSR'})]:
            cards = [card for card in self.cards[label] if find_ship(card.ship['name'])
                     and find_ship(card.ship['name'])['raw_name'] in ('天城', '加贺')]
            actual = {find_ship(card.ship['name'])['group_type']: card.ship['base_rarity'] for card in cards}
            self.assertEqual(actual, expected)
            self.assertFalse(any(card.ship['review'] for card in cards))

    def test_native_same_type_names_are_separate_reviews_without_candidate_guessing(self):
        for label, name in [('york', '约克'), ('crescent', '新月')]:
            cards = [card for card in self.cards[label] if card.ship['name'] == name]
            self.assertTrue(cards)
            self.assertTrue(all(card.ship['name'] == name and card.ship['review'] and card.identity_ambiguous for card in cards))


if __name__ == '__main__':
    unittest.main()
