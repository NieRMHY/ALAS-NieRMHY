"""用原始掉落截图的图标裁图验证新增统计物品的识别与数量。"""

import json
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from module.azur_stats.scene.operation_siren import SceneOperationSiren
from module.base.button import ButtonGrid


FIXTURES = Path(__file__).parent / 'fixtures' / 'opsi_requested_items'


class TestRequestedItemRecognition(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = json.loads((FIXTURES / 'cases.json').read_text(encoding='utf-8'))
        cls.scene = SceneOperationSiren()
        cls.scene.server = 'cn'

    def test_native_items_and_amounts(self):
        """材料、金计划和彩突破部件使用真实数量，紫计划和金突破部件保留原稀有度。"""
        for case in self.cases:
            with self.subTest(file=case['file']):
                image = np.array(Image.open(FIXTURES / case['file']).convert('RGB'))
                grid = self.scene.item_grid if case['layout'] == 'popup' else self.scene.auto_search_item_group
                size = 96 if case['layout'] == 'popup' else 64
                grid.grids = ButtonGrid(origin=(0, 0), delta=(size, size),
                                        button_shape=(size, size), grid_shape=(1, 1))
                grid.predict(image, tag=False)
                self.assertEqual([(item.name, item.amount) for item in grid.items],
                                 [(case['item'], case['amount'])])

    def test_third_popup_layout_keeps_boss_upgrade_part(self):
        image = np.array(Image.open(FIXTURES / 'boss_get_items_3.png').convert('RGB'))
        scene = SceneOperationSiren()
        scene.server = 'cn'
        self.assertTrue(scene.is_get_items(image))
        scene.load_file([image])
        rows = list(scene.parse_scene())
        parts = [row for row in rows if row.item == 'PrototypeGearPartsT5']
        self.assertEqual([(row.zone_type, row.amount) for row in parts], [('UNKNOWN', 1)])

    def test_upgrade_parts_keep_strict_similarity(self):
        """按底色筛选突破部件时，不沿用纸类动画模板的宽松阈值。"""
        grid = SceneOperationSiren().item_grid
        grid._matching_tier = 'T5'
        self.assertEqual(grid.template_similarity_for('PrototypeGearPartsT5', 0.92), 0.92)
        self.assertEqual(grid.template_similarity_for('GearDesignPlanPlaneT5', 0.92), 0.6)
        self.assertEqual(grid.template_similarity_for('OrdnanceTestingReportT5', 0.92), 0.6)


if __name__ == '__main__':
    unittest.main()
