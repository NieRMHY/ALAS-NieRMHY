"""仓库灰度字形：独立原生失败帧与未收录采样相位，不连接模拟器。"""

import json
from pathlib import Path
import unittest

import cv2
import numpy as np

from module.base.utils import load_image
from module.storage.statistics_recognition import StorageCatalog, recognize_rows

FIXTURES = Path(__file__).parent / 'fixtures/storage_statistics'


class GrayAmountTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = StorageCatalog()

    def test_independent_native_failure_frame_uses_item_templates_and_reads_all_counts(self):
        # 本帧未参与 amount_glyphs 模板生成；旧版在同一帧持续拒绝读取 20。
        rows = recognize_rows(load_image(str(FIXTURES / 'live_unseen_amounts.png')), self.catalog)
        self.assertEqual([(card.identifier, card.amount) for row in rows for card in row if card.identifier],
                         [('PrototypeGearPartsT5', 153), ('GearDesignPlanGunT5', 46),
                          ('GearDesignPlanTorpedoT5', 20), ('GearDesignPlanAntiAirT5', 46),
                          ('GearDesignPlanPlaneT5', 58)])

    def test_subpixel_sampling_preserves_all_digits(self):
        # 这是合成相位回归，不能代替上面的独立原生帧或整仓实机验收。
        samples = load_image(str(FIXTURES / 'live_digits.png'))
        cases = json.loads((FIXTURES / 'live_digits.json').read_text(encoding='utf-8'))
        for case in cases[:6] + cases[85:87]:
            start = case['row'] * 27
            crop = samples[start:start + 27]
            for dx in np.arange(0, 1, .125):
                for dy in np.arange(0, 1, .125):
                    with self.subTest(item=case['id'], amount=case['amount'], dx=dx, dy=dy):
                        shifted = cv2.warpAffine(crop, np.array([[1, 0, dx], [0, 1, dy]], dtype=np.float32),
                                                 (102, 27), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
                        icon = np.zeros((128, 128, 3), dtype=np.uint8)
                        icon[99:126, 25:127] = shifted
                        self.assertEqual(self.catalog.read_amount(icon), case['amount'])

    def test_unseen_metal_frame_reads_zero_without_training_on_this_failure(self):
        rows = recognize_rows(load_image(str(FIXTURES / 'live_unseen_metals.png')), self.catalog)
        self.assertEqual([(card.identifier, card.amount) for row in rows for card in row if card.identifier],
                         [('PlateGunT4', 497), ('PlateTorpedoT4', 1659), ('PlateAntiAirT4', 1269),
                          ('PlatePlaneT4', 1629), ('PrototypeGearPartsT4', 745),
                          ('Ultra_High_Purity_Metals', 5016), ('Military_Grade_Electronic_Components', 3585),
                          ('HBX_Blend_Gunpowder', 3785), ('High_Durability_Elastomers', 5635),
                          ('Superconductive_Metals', 4230)])

    def test_empty_and_unrelated_gray_shapes_are_not_forced_into_digits(self):
        for fill in (0, 128, 255):
            with self.subTest(fill=fill):
                self.assertIsNone(self.catalog.gray_digits.classify(np.full((24, 20), fill, dtype=np.uint8)))


if __name__ == '__main__':
    unittest.main()
