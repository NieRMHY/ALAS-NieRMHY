"""舰队名称名单、保守匹配、原彩色复识别与实际配置写入回归。"""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

from dev_tools.ship_data_extractor import extract_ship_names
from module.retire.ship_name import ShipNameMatcher
from module.retire.scanner import FleetManagementScanner, FleetNameScanner


class ShipNameTests(unittest.TestCase):
    @staticmethod
    def matcher(names):
        with patch.object(ShipNameMatcher, '_load_names', return_value=tuple(names)):
            return ShipNameMatcher('cn')

    def test_absent_names_never_forced_to_other_ships(self):
        matcher = self.matcher(['金伯利·META', '霞·META', '？？？？？', '热心'])
        for value in ('胜利·META', '灵敏·META', '匆忙', '热心.改', ''):
            self.assertEqual(matcher.correct(value), value)

    def test_unique_explicit_truncation_only(self):
        matcher = self.matcher(['松鲷', '松风', '阿尔弗雷多·奥里亚尼', '皇家方舟', '皇家方舟·META'])
        self.assertEqual(matcher.correct('阿尔弗雷多·奥..'), '阿尔弗雷多·奥里亚尼')
        self.assertEqual(matcher.correct('皇家方舟·MET…'), '皇家方舟·META')
        for value in ('松', '松..', '皇家方舟..', '阿尔弗雷多', '阿尔弗雷多·奥.'):
            self.assertEqual(matcher.correct(value), value)
        self.assertEqual(matcher.resolve('皇家方舟..')[1], 'ambiguous')

    def test_retry_must_be_exact_and_preserve_first_identity(self):
        matcher = self.matcher(['松鲷', '金伯利·META', '霞·META', '热心', '热心.改'])
        self.assertEqual(matcher.retry_candidate('松', '松鲷'), '松鲷')
        self.assertEqual(matcher.retry_candidate('', '松鲷'), '松鲷')
        for raw, retry in [('胜利·META', '金伯利·META'), ('灵敏·META', '霞·META'),
                           ('热心.改', '热心'), ('松', '松鲷Y'), ('松', '松..')]:
            self.assertIsNone(matcher.retry_candidate(raw, retry))

    def test_published_names_and_language_isolation(self):
        cn = ShipNameMatcher('cn')
        for value in ('胜利·META', '灵敏·META', '热心.改', '命运女神.改', '杓鹬.改', '松鲷'):
            self.assertEqual(cn.resolve(value), (value, 'exact'))
        data = json.loads(ShipNameMatcher.DATA_FILE.read_text(encoding='utf-8'))
        for language in ('cn', 'en', 'jp', 'tw'):
            self.assertTrue(data[language])
            self.assertEqual(data[language], sorted(set(data[language])))
            self.assertFalse(any('{namecode:' in name for name in data[language]))
        self.assertIsNone(ShipNameMatcher('en').exact('胜利·META'))

    def test_invalid_catalog_keeps_raw_without_cross_language_fallback(self):
        for content in ('bad json', '{}', '{"cn": [1]}', '{"en": ["Victory"]}'):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'names.json'
                path.write_text(content, encoding='utf-8')
                with patch.object(ShipNameMatcher, 'DATA_FILE', path):
                    ShipNameMatcher._load_names.cache_clear()
                    self.assertEqual(ShipNameMatcher('cn').correct('胜利·META'), '胜利·META')
        with patch.object(ShipNameMatcher, 'DATA_FILE', Path('missing-ship-names.json')):
            ShipNameMatcher._load_names.cache_clear()
            self.assertEqual(ShipNameMatcher('cn').correct('灵敏·META'), '灵敏·META')
        ShipNameMatcher._load_names.cache_clear()

    def test_color_retry_only_for_unconfirmed_and_once_per_batch(self):
        scanner = FleetNameScanner(grid_shape=(3, 1))
        scanner.name_matcher = self.matcher(['胜利·META', '松鲷', '阿尔弗雷多·奥里亚尼'])
        scanner.ocr_model.ocr = Mock(return_value=['胜利·META', '松', '阿尔弗雷多·奥..'])
        model = Mock()
        model.atomic_ocr_for_single_lines.return_value = ['松鲷']
        with patch.object(type(scanner.ocr_model), 'cnocr', model):
            self.assertEqual(scanner.scan(np.zeros((720, 1280, 3), dtype=np.uint8)),
                             ['胜利·META', '松鲷', '阿尔弗雷多·奥里亚尼'])
        self.assertEqual(model.atomic_ocr_for_single_lines.call_count, 1)
        self.assertEqual(len(model.atomic_ocr_for_single_lines.call_args.args[0]), 1)

    def test_confirmed_names_do_not_repeat_ocr(self):
        scanner = FleetNameScanner(grid_shape=(2, 1))
        scanner.ocr_model.ocr = Mock(return_value=['胜利·META', '灵敏·META'])
        model = Mock()
        with patch.object(type(scanner.ocr_model), 'cnocr', model):
            self.assertEqual(scanner.scan(None), ['胜利·META', '灵敏·META'])
        model.atomic_ocr_for_single_lines.assert_not_called()

    def test_failed_or_conflicting_color_result_keeps_raw(self):
        scanner = FleetNameScanner(grid_shape=(2, 1))
        scanner.name_matcher = self.matcher(['松鲷', '金伯利·META'])
        scanner.ocr_model.ocr = Mock(return_value=['松', '胜利·META'])
        model = Mock()
        model.atomic_ocr_for_single_lines.return_value = ['', '金伯利·META']
        with patch.object(type(scanner.ocr_model), 'cnocr', model):
            self.assertEqual(scanner.scan(np.zeros((720, 1280, 3), dtype=np.uint8)), ['松', '胜利·META'])
        scanner.name_matcher = self.matcher([])
        model.reset_mock()
        with patch.object(type(scanner.ocr_model), 'cnocr', model):
            self.assertEqual(scanner.scan(None), ['松', '胜利·META'])
        model.atomic_ocr_for_single_lines.assert_not_called()

    def test_normalized_collision_is_not_arbitrarily_selected(self):
        matcher = self.matcher(['A B', 'Ab'])
        self.assertIsNone(matcher.exact('a b'))
        self.assertEqual(matcher.correct('a b'), 'a b')

    def test_generator_resolves_references_and_excludes_regular_skins(self):
        with tempfile.TemporaryDirectory() as directory:
            for server in ('CN', 'EN', 'JP', 'TW'):
                root = Path(directory) / server
                (root / 'sharecfg').mkdir(parents=True)
                (root / 'sharecfgdata').mkdir()
                (root / 'sharecfg/ship_skin_template_sublist').mkdir()
                (root / 'sharecfg/name_code.lua').write_text('[1] = {\n name = "舰名",\n}\n', encoding='utf-8')
                (root / 'sharecfgdata/ship_data_statistics.lua').write_text(
                    '[11] = {\n name = "{namecode:1}",\n}\n', encoding='utf-8')
                (root / 'sharecfg/ship_skin_template.lua').write_text('', encoding='utf-8')
                (root / 'sharecfg/ship_skin_template_sublist/ship_skin_template_1.lua').write_text(
                    '[12] = {\n name = "普通皮肤标题",\n skin_type = 0,\n}\n'
                    '[19] = {\n name = "{namecode:1}.改",\n skin_type = 2,\n}\n', encoding='utf-8')
            output = extract_ship_names(directory)
            self.assertEqual(output, {server: ['舰名', '舰名.改'] for server in ('cn', 'en', 'jp', 'tw')})
            (Path(directory) / 'CN/sharecfg/name_code.lua').write_text('', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, '未解析的名称引用'):
                extract_ship_names(directory)

    def test_real_name_crops_and_final_config_write(self):
        from module.base.utils import load_image
        from module.config.config import AzurLaneConfig
        from module.api.config_service import ConfigService
        from module.retire.fleet_management import FleetManagement
        from tests.test_api import fixture

        scanner = FleetManagementScanner()
        # 夹具保留真实名称、舰队标识、等级和心情裁剪，四条识别链路全部实测。
        result = {}
        names = {}
        for category in ('vanguard', 'main', 'submarine'):
            image = load_image(str(Path(__file__).parent / f'fixtures/fleet_names_{category}.png'))
            names[category] = scanner.name_scanner.scan(image)
            result[category] = FleetManagement._normalize_result(scanner.scan(image))
        self.assertEqual(names['vanguard'][5], '灵敏·META')
        self.assertEqual(names['vanguard'][13], '热心.改')
        self.assertEqual(names['vanguard'][3], '命运女神.改')
        self.assertEqual(names['vanguard'][11], '匆忙')
        self.assertEqual(names['main'][12], '胜利·META')
        self.assertEqual(names['main'][15], '独角兽.改')
        self.assertEqual(names['submarine'][2], '松鲷')
        with tempfile.TemporaryDirectory() as directory:
            service = ConfigService(fixture(directory))
            worker = AzurLaneConfig.__new__(AzurLaneConfig)
            worker.config_name = 'testpilot'
            worker.data = service.get('testpilot')['values']
            worker._loaded_data = copy.deepcopy(worker.data)
            worker.modified, worker.bound = {}, {}
            runner = FleetManagement.__new__(FleetManagement)
            runner.config = worker
            path = str(service.path('testpilot'))
            with patch('module.config.config.filepath_config', return_value=path), \
                    patch('module.config.config_updater.filepath_config', return_value=path):
                runner._save_result(result)
            self.assertEqual(service.get('testpilot')['values']['FleetInfo']['FleetInfo']['Result'], result)
            victory = next(ship for ship in result['main']['1'] if ship['name'] == '胜利·META')
            self.assertEqual(victory, {'name': '胜利·META', 'level': 119, 'emotion': 150})


if __name__ == '__main__':
    unittest.main()
