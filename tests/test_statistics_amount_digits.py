"""真实数量切片回归：漏首位、重复数字丢位与图标残影。"""

import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import PropertyMock, patch

import numpy as np
from PIL import Image

from module.azur_stats.image.get_items import GetItems
from module.azur_stats.image.auto_search_reward import AutoSearchItemGrid
from module.azur_stats.scene.operation_siren import OPSI_AMOUNT_MAX, SceneOperationSiren
from module.statistics.amount_digits import read_amount_digits
from module.statistics.item import AmountOcr, ItemGrid

FIXTURES = Path(__file__).parent / 'fixtures/statistics_amounts'


class StrictAmount(AmountOcr):
    use_digit_templates = True
    strict_amount_max = True


class TestAmountDigits(unittest.TestCase):
    def test_real_quantity_crops(self):
        cases = json.loads((FIXTURES / 'cases.json').read_text(encoding='utf-8'))
        for case in cases:
            with self.subTest(file=case['file']):
                image = np.array(Image.open(FIXTURES / case['file']).convert('RGB'))
                self.assertEqual(read_amount_digits(image), case['amount'])

    def test_blank_and_non_color_images_need_ocr_fallback(self):
        self.assertIsNone(read_amount_digits(np.zeros((22, 54, 3), np.uint8)))
        self.assertIsNone(read_amount_digits(np.zeros((22, 54), np.uint8)))

    def test_cached_unknown_does_not_override_qualified_known_template(self):
        rng = np.random.default_rng(42)
        image = rng.integers(30, 225, (20, 20, 3), dtype=np.uint8)
        known = np.clip(image.astype(np.int16) + rng.integers(-12, 13, image.shape), 0, 255).astype(np.uint8)
        grid = ItemGrid(None, {}, template_area=(0, 0, 20, 20))
        grid.templates = {'KnownItem': known, '1': image.copy()}
        grid.colors = {name: tuple(template.mean(axis=(0, 1))) for name, template in grid.templates.items()}
        grid.templates_hit = {'KnownItem': 0, '1': 10}
        self.assertEqual(grid.match_template(image), 'KnownItem')
        self.assertEqual(grid.templates_hit['KnownItem'], 1)

    def test_unknown_template_is_used_when_known_template_fails_threshold(self):
        rng = np.random.default_rng(43)
        image = rng.integers(30, 225, (20, 20, 3), dtype=np.uint8)
        grid = ItemGrid(None, {}, template_area=(0, 0, 20, 20))
        grid.templates = {'KnownItem': rng.integers(30, 225, image.shape, dtype=np.uint8), '1': image.copy()}
        grid.colors = {name: tuple(template.mean(axis=(0, 1))) for name, template in grid.templates.items()}
        grid.templates_hit = {'KnownItem': 10, '1': 0}
        self.assertEqual(grid.match_template(image), '1')

    def test_confirmed_overflow_is_rejected_without_guessing_another_digit(self):
        image = np.array(Image.open(FIXTURES / 'commission_161.png').convert('RGB'))
        ocr = StrictAmount([], threshold=96)
        with patch.object(AmountOcr, 'cnocr', new_callable=PropertyMock) as model:
            self.assertEqual(ocr.ocr_with_validation(image, direct_ocr=True, amount_default_max=2), 0)
            model.assert_not_called()

    def test_uncertain_template_uses_existing_ocr_backend(self):
        ocr = StrictAmount([], threshold=96)
        model = SimpleNamespace(atomic_ocr_for_single_lines=lambda *_: ['17'])
        with patch('module.statistics.amount_digits.read_amount_digits', return_value=None), \
                patch.object(AmountOcr, 'cnocr', new_callable=PropertyMock, return_value=model):
            result = ocr.ocr_with_validation(np.zeros((22, 54, 3), np.uint8), direct_ocr=True,
                                             amount_default_max=50)
        self.assertEqual(result, 17)

    def test_ocr_overflow_is_not_truncated_into_a_plausible_amount(self):
        ocr = StrictAmount([], threshold=96)
        model = SimpleNamespace(atomic_ocr_for_single_lines=lambda *_: ['777'])
        with patch('module.statistics.amount_digits.read_amount_digits', return_value=None), \
                patch.object(AmountOcr, 'cnocr', new_callable=PropertyMock, return_value=model):
            result = ocr.ocr_with_validation(np.zeros((22, 54, 3), np.uint8), direct_ocr=True,
                                             amount_default_max=2)
        self.assertEqual(result, 0)

    def test_rainbow_limit_is_local_to_opsi_and_both_layouts(self):
        scene = SceneOperationSiren()
        for grid in (scene.item_grid, scene.auto_search_item_group):
            for name in OPSI_AMOUNT_MAX:
                self.assertEqual(grid.amount_max[name], 2)
        self.assertEqual(GetItems().item_grid.amount_max, {})

    def test_gold_paper_does_not_match_rainbow_or_lower_material_threshold(self):
        grid = AutoSearchItemGrid(None, {})
        with patch.object(grid, 'frame_color', return_value='gold'):
            names, threshold = grid.match_candidates(None, ['GearDesignPlanT5', 'GearDesignPlanT4',
                                                             'PlatePlaneT4'], .92)
        self.assertEqual(names, ['GearDesignPlanT4', 'PlatePlaneT4'])
        self.assertEqual(grid.template_similarity_for('GearDesignPlanT4', threshold), .6)
        self.assertEqual(grid.template_similarity_for('PlatePlaneT4', threshold), .92)

    def test_missing_gold_template_does_not_use_rainbow_candidate(self):
        grid = AutoSearchItemGrid(None, {})
        with patch.object(grid, 'frame_color', return_value='gold'):
            names, _ = grid.match_candidates(None, ['GearDesignPlanT5'], .92)
        self.assertEqual(names, [])

    def test_ten_is_preserved_with_a_ten_item_limit(self):
        image = np.array(Image.open(FIXTURES / 'opsi_prototype_20.png').convert('RGB'))
        ocr = StrictAmount([], threshold=96)
        self.assertEqual(ocr.ocr_with_validation(image, direct_ocr=True, amount_default_max=10), 10)

    def test_bad_quantity_does_not_discard_other_drops(self):
        parser = GetItems()
        good = SimpleNamespace(name='PlatePlaneT4', amount=2)
        bad = SimpleNamespace(name='GearDesignPlanPlaneT5', amount=0)
        grid = SimpleNamespace(grids=True, items=[bad, good], predict=lambda *_args, **_kwargs: None)
        parser.__dict__['item_grid'] = grid
        with patch.object(parser, '_get_items_load'):
            self.assertEqual(list(parser.parse_get_items(np.zeros((720, 1280, 3), np.uint8))), [good])


if __name__ == '__main__':
    unittest.main()
