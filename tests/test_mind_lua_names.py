"""以国服 Lua 身份及真实待核对卡片回归名称补全。"""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image

from module.runtime.mind_calculator import calculate, find_ship, highest_ships
from module.runtime.mind_name import match_lua_name
from module.runtime.mind_recognition import _match_name, aircraft_icon, meta_frame, recognize_cards

FIXTURES = Path(__file__).parent / 'fixtures'


class LuaNameMatchingTests(unittest.TestCase):
    def test_missing_long_tail_and_close_characters_match_the_shipped_lua_catalog(self):
        for raw, rarity, expected in [('纳希莫夫海军上', '', '纳希莫夫海军上将'),
                                      ('布曾克林', 'R', '布鲁克林')]:
            with self.subTest(raw=raw):
                info, _ = match_lua_name([raw] * 3, rarity)
                self.assertIsNotNone(info)
                self.assertEqual(info['name'], expected)

    def test_carrier_icon_distinguishes_two_same_rarity_child_names(self):
        self.assertIsNone(match_lua_name(['小天凤'] * 3, 'SR')[0])
        info, _ = match_lua_name(['小天凤', '小尖岚', '小天凤', '类岚', '类岚'], 'SR', aviation=True)
        self.assertEqual(info['name'], '小大凤')
        self.assertEqual(info['type'], '正航')

    def test_shared_truncated_name_uses_positive_frame_evidence_for_distinct_identities(self):
        reads = ['安德烈亚·多利..', '安德烈亚·多利...', '安德烈亚·多利..']
        ordinary = match_lua_name(reads, 'SR')[0]
        meta = match_lua_name(reads, meta_frame=True)[0]
        self.assertEqual(ordinary['name'], '安德烈亚·多利亚')
        self.assertEqual(meta['name'], '安德烈亚·多利亚·META')
        self.assertEqual((ordinary['base_rarity'], meta['base_rarity']), ('SR', 'SSR'))
        self.assertIsNone(match_lua_name(reads)[0])

    def test_truncated_near_characters_compare_visible_prefix_without_missing_tail_penalty(self):
        reads = ['拉菈·撒塔琳·..', '拉拉·撒塔琳·', '拉拉·撒塔琳·..']
        info, _ = match_lua_name(reads, 'SSR')
        self.assertEqual(info['name'], '菈菈·撒塔琳·戴比路克')
        self.assertEqual(info['group'], '联动')

    def test_fuzzy_base_spelling_does_not_turn_one_roman_stroke_into_two(self):
        self.assertIsNone(match_lua_name(['约克成I'] * 3, 'UR')[0])
        info, _ = match_lua_name(['约克成II'] * 3, 'UR')
        self.assertEqual(info['name'], '约克城II')

    def test_single_glyph_garbage_and_low_similarity_keep_the_raw_review(self):
        for reads in (['乘'] * 3, [''] * 3, ['???'] * 3, ['不存在的舰船'] * 3,
                      ['未知的舰船', '完全陌生'], ['乘', 'Φ', '乘', '雫', '乘']):
            with self.subTest(reads=reads):
                self.assertIsNone(match_lua_name(reads, 'SSR')[0])

    def test_conflicting_identities_and_literal_suffix_do_not_disappear(self):
        for reads in (['拉菲', '标枪'], ['皇家方舟·META', '皇家方舟'], ['华甲改', '华甲'],
                      ['列克星敦I'] * 3, ['约克城', '约克城I', '约克城'], ['皇家方舟·M'] * 3):
            with self.subTest(reads=reads):
                self.assertIsNone(match_lua_name(reads, 'SSR')[0])

    def test_fuzzy_matching_does_not_change_the_strict_public_identity_lookup(self):
        self.assertIsNone(find_ship('布曾克林'))
        self.assertIsNone(find_ship('小天凤'))
        self.assertIsNone(find_ship('安德烈亚·多利..'))

    def test_frame_context_cannot_replace_weak_name_evidence(self):
        self.assertIsNone(match_lua_name(['陌生未见测试舰船'] * 3, 'SR', meta_frame=True)[0])

    def test_aviation_context_keeps_the_other_aircraft_icon_families(self):
        for raw, expected in [('奇尔沙冶', '奇尔沙治'), ('扶乘改', '扶桑.改'), ('伊404', '伊404')]:
            with self.subTest(raw=raw):
                info, _ = match_lua_name([raw] * 3, aviation=True)
                self.assertIsNotNone(info)
                self.assertEqual(info['name'], expected)


class RealLuaCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.labels = json.loads((FIXTURES / 'mind_lua_names.json').read_text(encoding='utf-8'))
        atlas = np.array(Image.open(FIXTURES / 'mind_lua_names.png').convert('RGB'))
        pixels = np.array(Image.open(FIXTURES / 'mind_dock_stuck.png').convert('RGB'))
        from module.retire.dock import CARD_GRIDS
        for col in range(len(cls.labels)):
            x = round(float(CARD_GRIDS.origin[0] + col * CARD_GRIDS.delta[0]))
            pixels[75:270, x-10:x+145] = atlas[col*195:(col+1)*195]
        cls.image = Image.fromarray(pixels)
        cls.cards = recognize_cards(cls.image, row_origins=[75])

    def test_real_pending_and_meta_prefix_cards_are_confirmed_without_mocking_ocr(self):
        for card, label in zip(self.cards, self.labels):
            with self.subTest(name=label['name'], reads=card.name_reads):
                self.assertEqual(card.ship['name'], label['name'])
                self.assertEqual(card.ship['level'], label['level'])
                self.assertEqual(card.ship['base_rarity'], label['rarity'])
                self.assertTrue(card.level_reliable)
                self.assertFalse(card.ship['review'])

    def test_meta_print_is_positive_and_other_real_card_frames_are_negative(self):
        pixels = np.array(self.image)
        self.assertEqual([meta_frame(pixels, card.x, card.y) for card in self.cards[:5]],
                         [False, True, False, False, False])
        self.assertEqual([aircraft_icon(pixels, card.x, card.y) for card in self.cards[:5]],
                         [True, False, False, False, True])

    def test_meta_frame_corrects_a_truncated_name_that_exactly_matches_the_base_ship(self):
        for card in self.cards[5:]:
            with self.subTest(name=card.ship['name']):
                old, _ = _match_name([card.name_reads[0]], '')
                self.assertIsNotNone(old)
                self.assertNotEqual(old['group'], 'META')
                self.assertEqual(card.ship['name'], old['name'] + '·META')
                self.assertFalse(card.ship['review'])

    def test_real_truncated_near_characters_confirm_a_collaboration_ship_outside_the_range(self):
        pixels = np.array(self.image)
        pixels[75:270, 83:238] = np.array(Image.open(FIXTURES / 'mind_lala_truncated.png').convert('RGB'))
        card = recognize_cards(Image.fromarray(pixels), row_origins=[75])[0]
        self.assertEqual(card.ship['name'], '菈菈·撒塔琳·戴比路克')
        self.assertEqual(card.ship['level'], 76)
        self.assertFalse(card.ship['review'])
        self.assertEqual(calculate([card.ship])['ships'][0]['status'], 'excluded')

    def test_lua_matching_keeps_meta_separate_and_excludes_the_child(self):
        ships = highest_ships([copy.deepcopy(card.ship) for card in self.cards[:5]])
        self.assertEqual(len(ships), 5)
        report = calculate(ships)
        self.assertEqual(report['included'], 4)
        self.assertEqual(report['excluded'], 1)
        child = next(ship for ship in report['ships'] if ship['name'] == '小大凤')
        self.assertEqual(child['group'], '幼体')
        self.assertEqual(child['mind'], 0)

    def test_confirmed_names_do_not_charge_unreadable_levels(self):
        reader = Mock()
        reader.prepare.return_value = ([], np.ones((19, 32), np.uint8), np.ones((19, 32), np.uint8))
        reader.read.return_value = 0
        ocr = Mock()
        ocr.ocr_for_single_lines.side_effect = lambda images: ['???'] * len(images)
        with patch('module.runtime.mind_level.dock_level_reader', return_value=reader):
            cards = recognize_cards(self.image, row_origins=[75], level_ocr=ocr)
        self.assertEqual([card.ship['name'] for card in cards], [label['name'] for label in self.labels])
        self.assertTrue(all(card.ship['review'] and card.ship['level'] == 0 for card in cards))
        self.assertEqual(calculate([card.ship for card in cards])['mind'], 0)


if __name__ == '__main__':
    unittest.main()
