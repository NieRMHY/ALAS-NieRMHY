"""仓库读数严格模式：识别失败与真实 0 分离，冬季配额未知即暂停。

Add by MHY, 2026-11-09：WarehouseOCR.ocr_item_quantity 旧调用仍返回 0 兜底；
strict=True 时只有可核验的非负整数才返回，其余（未命中模板、空识别、非数字）
返回 None，配额层据此暂停而不是按 0 补产。
"""

import unittest
from unittest.mock import Mock, patch

import numpy as np

import module.config.server as server

server.server = 'cn'

from module.island import island_manufacture as manufacture_module  # noqa: E402
from module.island import island_manufacture_quota as quota  # noqa: E402
from module.island.island_manufacture import IslandManufacture  # noqa: E402
from module.island.warehouse import WarehouseOCR, WarehouseQuantityDigit  # noqa: E402

IMAGE = np.zeros((720, 1280, 3), dtype=np.uint8)


class FakeTemplate:
    """模板桩：只在第 hit_index 个格子命中，其余返回未命中。"""

    def __init__(self, hit_index=None):
        self.hit_index = hit_index
        self.similarities = []

    def match(self, image, similarity=None):
        self.similarities.append(similarity)
        return len(self.similarities) - 1 == self.hit_index


class FakeConfig:
    """只实现 cross_get 的配置桩。"""

    def __init__(self, values=None):
        self.values = dict(values or {})

    def cross_get(self, path, default=None):
        return self.values.get(path, default)


def fake_ocr(text, records=None):
    """替换 OCR 模型调用：给定原文，仍走真实的 Digit 修正与校验。"""

    def ocr(self, image, direct_ocr=False):
        if records is not None:
            records.append(self.buttons[0])
        return self.after_process(text)

    return ocr


class WarehouseReadingsTest(unittest.TestCase):
    """WarehouseOCR.ocr_item_quantity 的默认/严格两条路径。"""

    def setUp(self):
        self.ocr = WarehouseOCR()
        self.cells = [button for _, _, button in self.ocr.warehouse_grid.generate()]

    def read(self, template, text, strict=None):
        kwargs = {} if strict is None else {'strict': strict}
        with patch.object(WarehouseQuantityDigit, 'ocr', fake_ocr(text)):
            return self.ocr.ocr_item_quantity(IMAGE, template, **kwargs)

    def test_missing_template_is_zero_by_default(self):
        """旧调用兼容：模板未命中仍返回 0。"""
        template = FakeTemplate()
        self.assertEqual(self.read(template, '9'), 0)
        self.assertEqual(len(template.similarities), len(self.cells))
        self.assertTrue(all(similarity == 0.85 for similarity in template.similarities))

    def test_missing_template_is_none_in_strict_mode(self):
        """strict：未命中当前 6x2 页是未知，不能猜成 0。"""
        self.assertIsNone(self.read(FakeTemplate(), '9', strict=True))

    def test_empty_reading_is_zero_by_default(self):
        self.assertEqual(self.read(FakeTemplate(hit_index=0), ''), 0)

    def test_empty_reading_is_none_in_strict_mode(self):
        self.assertIsNone(self.read(FakeTemplate(hit_index=0), '', strict=True))

    def test_non_digit_text_is_zero_by_default(self):
        """非数字原文在默认模式下不抛错，保持 0 兜底。"""
        self.assertEqual(self.read(FakeTemplate(hit_index=0), '12A'), 0)

    def test_non_digit_text_is_none_in_strict_mode(self):
        self.assertIsNone(self.read(FakeTemplate(hit_index=0), '12A', strict=True))

    def test_real_zero_stays_zero_in_strict_mode(self):
        """原文确实是 0：严格模式也必须返回 0，而不是和识别失败混为一谈。"""
        value = self.read(FakeTemplate(hit_index=0), '0', strict=True)
        self.assertEqual(value, 0)
        self.assertIsNotNone(value)

    def test_positive_number_in_both_modes(self):
        self.assertEqual(self.read(FakeTemplate(hit_index=0), '37'), 37)
        self.assertEqual(self.read(FakeTemplate(hit_index=0), '37', strict=True), 37)

    def test_explicit_false_keeps_legacy_behaviour(self):
        self.assertEqual(self.read(FakeTemplate(), '9', strict=False), 0)

    def test_strict_uses_matched_cell_number_area(self):
        """命中第二个格子时，数量区域要落在该格子的数字区上。"""
        records = []
        template = FakeTemplate(hit_index=1)
        with patch.object(WarehouseQuantityDigit, 'ocr', fake_ocr('5', records)):
            value = self.ocr.ocr_item_quantity(IMAGE, template, strict=True)
        self.assertEqual(value, 5)
        self.assertEqual(records, [self.ocr._get_number_area(self.cells[1])])

    def test_strict_keeps_digit_confusion_repair(self):
        """Digit 会把 I/D/S/B 修正成数字；严格模式沿用同一套修正后再校验。"""
        self.assertEqual(self.read(FakeTemplate(hit_index=0), 'I0', strict=True), 10)

    def test_digit_records_raw_text_and_quantity(self):
        digit = WarehouseQuantityDigit(None, alphabet='0123456789')
        self.assertEqual(digit.after_process(''), 0)
        self.assertEqual(digit.raw_text, '')
        self.assertIsNone(digit.quantity)
        self.assertEqual(digit.after_process('0'), 0)
        self.assertEqual(digit.raw_text, '0')
        self.assertEqual(digit.quantity, 0)
        self.assertEqual(digit.after_process('24'), 24)
        self.assertEqual(digit.quantity, 24)
        self.assertEqual(digit.after_process('2A'), 0)
        self.assertIsNone(digit.quantity)
        self.assertEqual(digit.after_process(None), 0)
        self.assertIsNone(digit.quantity)

    def test_validated_quantity_rejects_unknown_values(self):
        self.assertEqual(WarehouseOCR._validated_quantity(4), 4)
        self.assertEqual(WarehouseOCR._validated_quantity(0), 0)
        for value in (None, -1, True, 3.0, '5'):
            self.assertIsNone(WarehouseOCR._validated_quantity(value))


def make_factory(**attrs):
    """构造只用于配额状态计算的工厂，不跑 Island.__init__。"""
    with patch.object(IslandManufacture, '__init__', lambda self: None):
        factory = IslandManufacture()
    factory.post_items = {}
    factory.winter_quota_ordered = {}
    factory.warehouse_counts = {}
    factory._warehouse_scanned = True
    factory.name_to_config = {'cutlery': {'name': 'cutlery', 'template': object()}}
    factory.config = FakeConfig()
    factory.current_season = 'winter'
    factory.get_idle_posts_by_category = Mock(
        side_effect=lambda line: ['P1', 'P2'] if line == 'industrial_production' else [])
    for name, value in attrs.items():
        setattr(factory, name, value)
    return factory


def read_tasks():
    _, tasks = quota.read_winter_task_settings(FakeConfig())
    return tasks


def by_key(tasks, key):
    return next(task for task in tasks if task['key'] == key)


class WinterQuotaObservationTest(unittest.TestCase):
    """配额库存优先 strict 观测；未知读数暂停派产。"""

    def setUp(self):
        patcher = patch.object(manufacture_module, 'logger')
        self.logger = patcher.start()
        self.addCleanup(patcher.stop)

    def test_state_prefers_observations_over_counts(self):
        factory = make_factory(warehouse_observations={'cutlery': 4},
                               warehouse_counts={'cutlery': 0})
        state = factory._winter_quota_state(read_tasks())
        self.assertEqual(state['stock']['cutlery'], 4)

    def test_state_keeps_unknown_reading_as_none(self):
        """strict 读到 None 时不能被 warehouse_counts 的 0 兜底盖掉。"""
        factory = make_factory(warehouse_observations={'cutlery': None},
                               warehouse_counts={'cutlery': 0})
        state = factory._winter_quota_state(read_tasks())
        self.assertIsNone(state['stock']['cutlery'])

    def test_state_without_observations_uses_legacy_counts(self):
        """未设置 warehouse_observations 的旧夹具仍按 warehouse_counts 工作。"""
        factory = make_factory(warehouse_counts={'cutlery': 3})
        state = factory._winter_quota_state(read_tasks())
        self.assertEqual(state['stock']['cutlery'], 3)

    def test_state_missing_item_in_observations_is_unknown(self):
        factory = make_factory(warehouse_observations={}, warehouse_counts={'cutlery': 0})
        state = factory._winter_quota_state(read_tasks())
        self.assertIsNone(state['stock']['cutlery'])

    def test_dependency_stock_prefers_observations(self):
        factory = make_factory(
            warehouse_observations={'cloth': None},
            warehouse_counts={'cloth': 0})
        factory.name_to_config['cloth'] = {'name': 'cloth', 'template': object()}
        state = factory._winter_quota_state(read_tasks())
        self.assertIsNone(state['dependency_stock']['cloth'])

        legacy = make_factory(warehouse_counts={'cloth': 2})
        legacy.name_to_config['cloth'] = {'name': 'cloth', 'template': object()}
        self.assertEqual(legacy._winter_quota_state(read_tasks())['dependency_stock']['cloth'], 2)

    def test_unknown_reading_suspends_quota_instead_of_supplementing(self):
        factory = make_factory(warehouse_observations={'cutlery': None},
                               warehouse_counts={'cutlery': 0})
        plan = factory.prepare_winter_quota()
        cutlery = by_key(plan['items'], 'cutlery')
        self.assertEqual(cutlery['status'], 'suspended')
        self.assertEqual(cutlery['reason'], 'unknown_stock')
        self.assertEqual(cutlery['batches'], [])
        self.assertEqual(plan['batches'], {})

    def test_known_reading_dispatches_gap_from_observations(self):
        factory = make_factory(warehouse_observations={'cutlery': 4},
                               warehouse_counts={'cutlery': 0})
        plan = factory.prepare_winter_quota()
        cutlery = by_key(plan['items'], 'cutlery')
        self.assertEqual(cutlery['stock'], 4)
        self.assertEqual(cutlery['gap'], 6)
        self.assertEqual(cutlery['status'], 'dispatch')
        self.assertEqual(plan['batches'], {'cutlery': [5, 1]})

    def test_real_zero_reading_allows_full_gap(self):
        """严格模式读到真实 0 与识别失败不同：缺口按需求全额补齐。"""
        factory = make_factory(warehouse_observations={'cutlery': 0},
                               warehouse_counts={'cutlery': 0})
        plan = factory.prepare_winter_quota()
        cutlery = by_key(plan['items'], 'cutlery')
        self.assertEqual(cutlery['gap'], 10)
        self.assertEqual(plan['batches'], {'cutlery': [5, 5]})


if __name__ == '__main__':
    unittest.main()
