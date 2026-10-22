"""真实船坞底部圆角及未对齐末页的循环回放，不连接账号。"""
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image

from module.retire.dock import DOCK_SCROLL
from module.retire.fleet_tech_scan import FleetTechScan
from module.retire.mind_scan import MindCalculatorScan
from module.runtime.mind_recognition import ScanPolicy, grid_rows, recognize_cards
from tests.test_mind_scan import cards_for_levels

FIXTURES = Path(__file__).parent / 'fixtures'


class NativeBottomTests(unittest.TestCase):
    def scanner(self, task=MindCalculatorScan, strip=None):
        scanner = task.__new__(task)
        pixels = np.array(Image.open(FIXTURES / 'mind_dock_bottom.png').convert('RGB'))
        if strip is not None:
            x1, y1, x2, y2 = DOCK_SCROLL.area
            pixels[y1:y2, x1:x2] = strip
        scanner.device = SimpleNamespace(image=pixels)
        return scanner

    def test_both_tasks_confirm_connected_native_bottom_cap_without_extending_thumb(self):
        for task in (MindCalculatorScan, FleetTechScan):
            scanner = self.scanner(task)
            thumb = scanner._dock_scroll_thumb()
            self.assertEqual((thumb[0], thumb[-1], DOCK_SCROLL.total), (488, 562, 565))
            self.assertTrue(scanner._dock_scroll_at_bottom(thumb))
            self.assertEqual(thumb[-1], 562)

    def test_near_bottom_dark_disconnected_or_wide_tail_is_not_bottom(self):
        scanner = self.scanner()
        x1, y1, x2, y2 = DOCK_SCROLL.area
        strip = scanner.device.image[y1:y2, x1:x2].copy()
        for kind in ('one_pixel_above', 'two_pixels_above', 'dark', 'disconnected', 'wide'):
            damaged = strip.copy()
            if kind.endswith('above'):
                shift = 1 if kind.startswith('one') else 2
                damaged[:-shift], damaged[-shift:] = strip[shift:], 0
            elif kind == 'dark':
                damaged[-2:] = 0
            elif kind == 'disconnected':
                damaged[-2] = 0
            else:
                damaged[-1] = strip[-2]
            current = self.scanner(strip=damaged)
            self.assertFalse(current._dock_scroll_at_bottom(current._dock_scroll_thumb()), kind)
        self.assertFalse(scanner._dock_scroll_at_bottom(None))

    def test_native_partial_top_row_is_not_read_as_new_or_missing_cards(self):
        scanner = self.scanner()
        self.assertEqual(grid_rows(scanner.device.image), [172, 399])
        cards = recognize_cards(Image.fromarray(scanner.device.image))
        scanner._check_scan_page(cards, True)
        self.assertEqual(len(cards), 14)
        self.assertEqual({card.y for card in cards}, {172, 399})
        self.assertTrue(all(card.level_reliable and card.ship['level'] == 1 for card in cards))
        self.assertFalse(any(card.ship['review'] for card in cards))
        with self.assertRaises(ValueError):
            scanner._check_scan_page(cards, False)

    def test_real_loop_reads_unaligned_last_two_rows_once_and_exits_without_extra_drag(self):
        scanner = self.scanner()
        scanner.config = SimpleNamespace(Emulator_ControlMethod='MaaTouch', config_name='testpilot')
        scanner._policy = ScanPolicy(1, 125, True)
        scanner.appear = Mock(return_value=True)
        scanner.handle_popup_confirm = Mock(return_value=False)
        scanner._save_scan_evidence = Mock(return_value='')
        bottom = scanner.device.image.copy()
        content = np.random.default_rng(20261016).integers(30, 230, (1160, 1140, 3), dtype=np.uint8)
        content[585:] = bottom[65:640, 85:1225]
        position, now, reads = 0, 1., []

        def screenshot():
            nonlocal now
            now += .25
            pixels = bottom.copy()
            pixels[65:640, 85:1225] = content[position:position + 575]
            if position != 585:
                x1, y1, x2, y2 = DOCK_SCROLL.area
                pixels[y1:y2, x1:x2] = 0
                start = 2 + round(position / 585 * 486)
                pixels[y1 + start:y1 + start + 75, x1:x2] = DOCK_SCROLL.color
            scanner.device.image = pixels

        def drag(start, end, **kwargs):
            nonlocal position
            position = min(585, position + start[1] - end[1])

        def read(image, *args):
            reads.append(position)
            if position == 585:
                return recognize_cards(image)
            cards = cards_for_levels([125] * 21)
            for index, card in enumerate(cards):
                card.y += 11
                card.ship['name'] = f'前页舰船{index}'
            return cards

        scanner.device = Mock()
        scanner.device.screenshot.side_effect = screenshot
        scanner.device.drag.side_effect = drag
        scanner._read_cards = read
        with patch('module.base.timer.time', side_effect=lambda: now), \
                patch('module.retire.mind_scan.grid_rows', side_effect=lambda _: [172, 399] if position == 585 else [76, 303, 530]):
            ships = scanner._scan_pages(Mock(), Mock())
        self.assertEqual(reads, [0, 585])
        self.assertEqual(scanner._scan_metadata, dict(reached_bottom=True, physical_count=35))
        self.assertEqual(scanner.device.drag.call_count, 3)
        self.assertEqual(len(ships), 29)
        self.assertTrue(any(ship['name'] == '科隆' for ship in ships))


if __name__ == '__main__':
    unittest.main()
