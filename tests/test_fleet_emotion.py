"""舰队心情扫描、筛选顺序和配置落盘的定向回归测试。"""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from module.config.config import AzurLaneConfig
from module.retire.fleet_management import FleetManagement
from module.retire.scanner import FleetEmotionDigit, FleetEmotionScanner, FleetManagementScanner


class FleetEmotionTests(unittest.TestCase):
    def test_strict_emotion_and_unknown(self):
        ocr = FleetEmotionDigit((0, 0, 25, 23))
        for text, expected in [('0', 0), ('150', 150), ('119', 119), ('', None),
                               ('151', None), ('1504', None), ('044', None), ('D44', None), ('?', None)]:
            with self.subTest(text=text):
                self.assertEqual(ocr.after_process(text), expected)

    def test_grid_alignment_and_exclusions(self):
        scanner = FleetManagementScanner(excluded_positions=((1, 0),))
        self.assertEqual(len(scanner.emotion_scanner.ocr_model.buttons), 20)
        self.assertEqual(len(scanner.level_scanner.ocr_model.buttons), 20)
        self.assertEqual(scanner.emotion_scanner.ocr_model.buttons[0], (116, 105, 141, 128))
        self.assertEqual(scanner.emotion_scanner.ocr_model.buttons[-1], (1104, 559, 1129, 582))

    def test_failed_emotion_keeps_name_and_level(self):
        scanner = FleetManagementScanner()
        for child, values in [(scanner.fleet_scanner, [1, 1, 2]),
                              (scanner.name_scanner, ['甲', '乙', '丙']),
                              (scanner.level_scanner, [125, 100, 70]),
                              (scanner.emotion_scanner, [None, 0])]:
            child.scan = Mock(return_value=values)
        self.assertEqual(scanner.scan(None), {
            1: [{'name': '甲', 'level': 125, 'emotion': None},
                {'name': '乙', 'level': 100, 'emotion': 0}],
            2: [{'name': '丙', 'level': 70, 'emotion': None}],
        })

    def test_picker_filter_sets_level_and_all_types_together(self):
        self._check_filter_transitions({'all'})

    def test_existing_multiple_ship_types_are_cleared(self):
        self._check_filter_transitions({'vanguard', 'main', 'ss'})

    def _check_filter_transitions(self, initial_indices):
        # 使用真实 Setting 检测截图上的选中状态；虚拟面板记录操作，禁止设备连接。
        runner = FleetManagement.__new__(FleetManagement)
        runner.config = SimpleNamespace(SERVER='cn')
        runner.device = SimpleNamespace(image=None, screenshot=Mock())
        runner.ui_ensure = Mock()
        runner.dock_favourite_set = Mock()
        runner.dock_sort_method_dsc_set = Mock()
        runner._save_result = Mock()
        runner.dock_reset = Mock()
        runner.loop = lambda **kwargs: iter([None])
        runner.appear = Mock(return_value=True)
        events = []
        selected = {key: {value} for key, value in runner.dock_filter.settings_default.items()}
        selected['index'] = set(initial_indices)
        selected['sort'] = {'mood'}

        def active(button, **kwargs):
            return any(b is button and option in selected[key]
                       for (key, option), b in runner.dock_filter.settings.items())

        def click(button):
            key, option = next(k for k, b in runner.dock_filter.settings.items() if b is button)
            # 舰种为多选；“全部”清除各舰种，选择具体舰种只取消“全部”。
            if key == 'index' and option != 'all':
                selected[key].discard('all')
                if option in selected[key]:
                    selected[key].remove(option)
                else:
                    selected[key].add(option)
            else:
                selected[key] = {option}
            events.append((key, option))

        runner.image_color_count = active
        runner.device.click = click
        runner.dock_filter_enter = lambda: events.append('enter')
        runner.dock_filter_confirm = lambda **kwargs: events.append(('confirm', copy.deepcopy(selected)))
        runner.dock_filter.reset_first = False
        try:
            runner._prepare_dock()
        finally:
            runner.dock_filter.reset_first = True
        confirms = [event[1] for event in events if isinstance(event, tuple) and event[0] == 'confirm']
        self.assertEqual([c['index'] for c in confirms], [{'all'}])
        self.assertEqual([c['sort'] for c in confirms], [{'level'}])
        first_confirm = events.index(('confirm', confirms[0]))
        self.assertLess(events.index(('sort', 'level')), first_confirm)
        if initial_indices != {'all'}:
            self.assertLess(events.index(('index', 'all')), first_confirm)
        self.assertEqual(events.count('enter'), 1)
        self.assertTrue(runner.dock_filter.reset_first)

    def test_actual_multi_selected_filter_screenshot(self):
        from module.base.utils import load_image

        runner = FleetManagement.__new__(FleetManagement)
        runner.config = SimpleNamespace(SERVER='cn')
        runner.device = SimpleNamespace(image=load_image(str(Path(__file__).parent / 'fixtures/fleet_multi_filter.png')))
        active = {key for key, button in runner.dock_filter.settings.items()
                  if runner.dock_filter.is_option_active(button)}
        self.assertIn(('sort', 'mood'), active)
        self.assertEqual({option for key, option in active if key == 'index'}, {'vanguard', 'main', 'ss'})

    def test_cleanup_on_failure_does_not_save_partial_result(self):
        runner = FleetManagement.__new__(FleetManagement)
        runner.config = SimpleNamespace(SERVER='cn')
        runner.device = SimpleNamespace(has_cached_image=True)
        for name in ('ui_ensure', 'dock_favourite_set', 'dock_sort_method_dsc_set',
                     'dock_reset', '_save_result', 'fleet_enter', '_open_slot', '_close_picker'):
            setattr(runner, name, Mock())
        runner._prepare_dock = Mock(side_effect=RuntimeError('筛选失败'))
        runner._formation_visible = Mock(return_value=False)
        with self.assertRaises(RuntimeError):
            runner.run(update_emotion=False)
        self.assertTrue(runner.dock_filter.reset_first)
        runner.dock_reset.assert_not_called()
        runner._close_picker.assert_called_once()
        runner._save_result.assert_not_called()

    def test_real_config_save_and_api_read_preserve_null_and_zero(self):
        from module.api.config_service import ConfigService
        from tests.test_api import fixture

        with tempfile.TemporaryDirectory() as directory:
            service = ConfigService(fixture(directory))
            worker = AzurLaneConfig.__new__(AzurLaneConfig)
            worker.config_name = 'testpilot'
            worker.data = service.get('testpilot')['values']
            worker._loaded_data = copy.deepcopy(worker.data)
            worker.modified = {}
            worker.bound = {}
            runner = FleetManagement.__new__(FleetManagement)
            runner.config = worker
            ships = {1: [{'name': '甲', 'level': 125, 'emotion': 150},
                         {'name': '乙', 'level': 100, 'emotion': None},
                         {'name': '丙', 'level': 70, 'emotion': 0}]}
            result = {'vanguard': runner._normalize_result(ships), 'main': {}, 'submarine': {}}
            with patch('module.config.config.filepath_config', return_value=str(service.path('testpilot'))), \
                    patch('module.config.config_updater.filepath_config', return_value=str(service.path('testpilot'))):
                runner._save_result(result)
            saved = json.loads(service.path('testpilot').read_text(encoding='utf-8'))
            self.assertEqual(saved['FleetInfo']['FleetInfo']['Result'], result)
            self.assertEqual(service.get('testpilot')['values']['FleetInfo']['FleetInfo']['Result'], result)

    def test_real_ocr_anonymized_card_regions(self):
        from module.base.utils import load_image

        image = load_image(str(Path(__file__).parent / 'fixtures/fleet_emotion.png'))
        scanner = FleetEmotionScanner()
        expected = [150] * 8 + [134, 134, 131, 119, 119, 119, 119, 119] + [150] * 5
        self.assertEqual(scanner.scan(image), expected)
        blank = np.zeros_like(image)
        self.assertEqual(scanner.scan(blank), [None] * 21)

    def test_native_low_and_scrolled_morale_regions(self):
        from module.base.utils import load_image

        cases = {
            'low_main': [(74, [None, 148, 119, 150, 119, 150, 150]),
                         (301, [150, 12, 150, 148, 138, 150, 148])],
            'low_vanguard': [(75, [None, 119, 119, 119, 148, 138, 150]),
                             (302, [150, 150, 150, 138, 148, 150, 12])],
            'zero_vanguard': [(75, [None, 119, 119, 119, 148, 138, 150]),
                              (302, [150, 150, 150, 138, 148, 150, 0])],
            'scroll_1': [(60, [119, 148, 150, 138, 119, 138, 142]),
                         (287, [150, 120, 119, 142, 128, 150, 119])],
            'scroll_2': [(206, [119, 119, 119, 150, 119, 129, 150]),
                         (433, [150, 130, 119, 150, 150, 124, 150])],
            'scroll_3': [(213, [150, 150, 133, 150, 150, 150, 150])],
            'scroll_4': [(196, [119, 150, 119, 150, 150, 119, 150]),
                         (423, [150, 150, 150, 150, 150, 150, 150])],
        }
        scanner = FleetEmotionScanner(grid_shape=(7, 1))
        current_y = 76
        for name, rows in cases.items():
            image = load_image(str(Path(__file__).parent / f'fixtures/fleet_morale/{name}.png'))
            for y, expected in rows:
                with self.subTest(frame=name, row=y):
                    scanner.move((0, y - current_y))
                    current_y = y
                    self.assertEqual(scanner.scan(image), expected)

    def test_low_morale_digits_one_through_thirty_with_portrait_noise(self):
        from module.base.utils import load_image
        from module.retire.dock import CARD_GRIDS

        root = Path(__file__).parent / 'fixtures/fleet_morale'
        pages = {name: load_image(str(root / f'{name}.png'))
                 for name in ('low_main', 'low_vanguard', 'scroll_3')}
        # 从原图的心情数字截取0–9字形，组合所有低心情值，不重绘或缩放字体。
        cells = {0: ('low_main', 74, 3, 2), 1: ('low_vanguard', 75, 1, 0),
                 2: ('low_vanguard', 302, 6, 1), 3: ('low_vanguard', 302, 3, 1),
                 4: ('low_vanguard', 302, 4, 1), 5: ('low_vanguard', 302, 0, 1),
                 6: ('low_main', 528, 3, 2), 7: ('scroll_3', 440, 1, 2),
                 8: ('low_vanguard', 302, 3, 2), 9: ('low_vanguard', 75, 1, 2)}
        glyphs = {}
        for digit, (name, row, column, cell) in cells.items():
            x = round(float(CARD_GRIDS.origin[0] + column * CARD_GRIDS.delta[0])) + 23 + 8 * cell
            glyphs[str(digit)] = pages[name][row + 29:row + 49, x:x + 8]
        scanner = FleetEmotionScanner(grid_shape=(7, 1))
        scanner.move((0, 302 - 76))
        x, y = scanner.ocr_model.buttons[-1][:2]
        for value in range(1, 31):
            with self.subTest(value=value):
                image = pages['low_vanguard'].copy()
                image[y:y + 23, x:x + 17] = 0
                for index, char in enumerate(str(value)):
                    image[y:y + 20, x + index * 8:x + (index + 1) * 8] = glyphs[char]
                self.assertEqual(scanner.scan(image)[-1], value)

    def test_color_confirmation_preserves_unknown_and_rejects_impossible_low_value(self):
        from module.base.utils import load_image

        root = Path(__file__).parent / 'fixtures/fleet_morale'
        scanner = FleetEmotionScanner(grid_shape=(7, 1))
        scanner.move((0, 302 - 76))
        scanner.ocr_model.ocr = Mock(side_effect=lambda *args, **kwargs: [None] * 7)
        red = load_image(str(root / 'zero_vanguard.png'))
        self.assertEqual(scanner.scan(red), [None] * 6 + [0])
        # 只剩右侧红色图标不能把空白或立绘判为0。
        x, y = scanner.ocr_model.buttons[-1][:2]
        red[y - 2:y + 23, x - 25:x - 4] = 0
        self.assertEqual(scanner.scan(red), [None] * 7)
        yellow = load_image(str(root / 'low_vanguard.png'))
        scanner.ocr_model.ocr.side_effect = None
        for value in (0, 67, 150, None):
            with self.subTest(value=value):
                scanner.ocr_model.ocr.return_value = [None] * 6 + [value]
                self.assertIsNone(scanner.scan(yellow)[-1])

    def test_zero_reaches_morale_dock_card(self):
        from module.base.utils import load_image
        from module.runtime.fleet_formation import MoraleDockScanner
        from module.runtime.mind_recognition import grid_rows

        root = Path(__file__).parent / 'fixtures'
        image = load_image(str(root / 'fleet_formation/direct_vanguard.png'))
        red = load_image(str(root / 'fleet_morale/zero_vanguard.png'))
        y = grid_rows(image)[1]
        image[y + 27:y + 80, 1079:1219] = red[302 + 27:302 + 80, 1079:1219]
        cards = MoraleDockScanner().scan(image)
        zero = next(card for card in cards if card.y == y and card.col == 6)
        self.assertEqual(zero.fleet, 6)
        self.assertEqual(zero.ship['emotion'], 0)

    def test_japanese_morale_uses_existing_ocr_path(self):
        scanner = FleetEmotionScanner()
        image = np.zeros((720, 1280, 3), np.uint8)
        scanner.ocr_model.ocr = Mock(return_value=[None] * 21)
        with patch('module.retire.scanner.server.server', 'jp'):
            self.assertEqual(scanner.scan(image), [None] * 21)
        scanner.ocr_model.ocr.assert_called_once_with(image)


if __name__ == '__main__':
    unittest.main()
