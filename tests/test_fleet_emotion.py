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

    def test_first_filter_combines_mood_and_vanguard_then_preserves_sort(self):
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
        runner._wait_dock_filter_loaded = Mock()
        runner._save_result = Mock()
        runner.dock_reset = Mock()
        events = []
        selected = {key: {value} for key, value in runner.dock_filter.settings_default.items()}
        selected['index'] = set(initial_indices)

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
        with patch('module.retire.fleet_management.FleetManagementScanner') as scanner:
            scanner.return_value.scan.return_value = {}
            runner.run()
        confirms = [event[1] for event in events if isinstance(event, tuple) and event[0] == 'confirm']
        self.assertEqual([c['index'] for c in confirms], [{'vanguard'}, {'main'}, {'ss'}])
        self.assertEqual([c['sort'] for c in confirms], [{'mood'}] * 3)
        for target in ('main', 'ss'):
            index = events.index(('index', target))
            self.assertEqual(events[index - 1], ('index', 'all'))
        first_confirm = events.index(('confirm', confirms[0]))
        self.assertLess(events.index(('sort', 'mood')), first_confirm)
        self.assertLess(events.index(('index', 'vanguard')), first_confirm)
        self.assertEqual(events.count('enter'), 3)
        self.assertEqual(events.count(('sort', 'mood')), 1)
        self.assertTrue(runner.dock_filter.reset_first)
        runner.dock_reset.assert_called_once()

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
        for name in ('ui_ensure', 'dock_favourite_set', 'dock_sort_method_dsc_set',
                     'dock_reset', '_save_result'):
            setattr(runner, name, Mock())
        runner.dock_filter_set = Mock(side_effect=RuntimeError('筛选失败'))
        with patch('module.retire.fleet_management.FleetManagementScanner'), self.assertRaises(RuntimeError):
            runner.run()
        self.assertTrue(runner.dock_filter.reset_first)
        runner.dock_reset.assert_called_once()
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


if __name__ == '__main__':
    unittest.main()
