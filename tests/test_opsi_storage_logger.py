"""仓库记录仪使用流程：扫描与重扫按各模板原相似度匹配，失败点击沿用既有预算。"""

# Add by MHY, 2026-11-06: 覆盖记录仪重扫阈值回归（LOGGER 0.5 / UNLOCK 0.75）
import collections
import unittest
from unittest.mock import Mock, patch

import numpy as np

from module.base.button import Button
from module.base.utils import rgb2gray
from module.device.device import Device
from module.exception import GameTooManyClickError
from module.os_handler import storage
from module.os_handler.assets import STORAGE_CHECK, TEMPLATE_STORAGE_LOGGER, TEMPLATE_STORAGE_LOGGER_UNLOCK
from module.os_handler.storage import StorageHandler, storage_logger_match
from module.storage.assets import BOX_USE

# 两个记录仪模板的原相似度，与实现无关的独立期望值
LOGGER_SIMILARITY = 0.5
UNLOCK_SIMILARITY = 0.75


class FakeClock:
    """替代 module.base.timer 的 monotonic，让 Timer 走真实判定逻辑。"""

    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class FakeDevice:
    """只提供截图与点击记录，截图推进假时钟以驱动确认计时器。"""

    def __init__(self, clock):
        self.clock = clock
        self.image = np.zeros((720, 1280, 3), dtype=np.uint8)
        self.screenshots = 0
        self.clicks = []

    def screenshot(self):
        self.screenshots += 1
        self.clock.now += 0.5
        return self.image

    def click(self, button, control_check=True):
        self.clicks.append(button)


class BudgetDevice(FakeDevice):
    """点击接入真实 Device 点击预算：连续 50 次同按钮操作抛 GameTooManyClickError。"""

    def __init__(self, clock):
        super().__init__(clock)
        self.guard = Device.__new__(Device)
        self.guard.click_record = collections.deque(maxlen=50)

    def click(self, button, control_check=True):
        super().click(button)
        self.guard.click_record_add(button)
        self.guard.click_record_check()


class StorageLoggerTests(unittest.TestCase):
    def handler(self, device, gates=None):
        """构造只替换外部依赖的 StorageHandler，保留真实流程方法。"""
        handler = StorageHandler.__new__(StorageHandler)
        handler.device = device
        handler.interval_timer = {}
        handler.handle_story_skip = Mock(return_value=False)

        def appear(button, **kwargs):
            if button is not STORAGE_CHECK:
                return False
            if 'interval' not in kwargs:
                return True
            if gates is None:
                return True
            return gates.pop(0) if gates else False

        handler.appear = Mock(side_effect=appear)
        handler.appear_then_click = Mock(return_value=False)
        return handler

    def stub(self, template, items=None):
        """替换模板匹配并记录每次调用的截图与相似度。"""
        calls = []
        pending = list(items or [])

        def match_multi(image, similarity=None):
            calls.append((image, similarity))
            return pending.pop(0) if pending else []

        return patch.object(template, 'match_multi', Mock(side_effect=match_multi)), calls

    def test_storage_logger_match_keeps_each_template_similarity(self):
        image = np.zeros((720, 1280), dtype=np.uint8)
        logger_button = Button((0, 0, 10, 10), (), (0, 0, 10, 10), name=TEMPLATE_STORAGE_LOGGER.name)
        unlock_button = Button((0, 0, 10, 10), (), (0, 0, 10, 10), name=TEMPLATE_STORAGE_LOGGER_UNLOCK.name)
        logger_match, logger_calls = self.stub(TEMPLATE_STORAGE_LOGGER, [[logger_button]])
        unlock_match, unlock_calls = self.stub(TEMPLATE_STORAGE_LOGGER_UNLOCK, [[unlock_button]])
        with logger_match, unlock_match:
            items = storage_logger_match(image)
        self.assertEqual(items, [logger_button, unlock_button])
        self.assertEqual([similarity for _, similarity in logger_calls], [LOGGER_SIMILARITY])
        self.assertEqual([similarity for _, similarity in unlock_calls], [UNLOCK_SIMILARITY])
        self.assertTrue(all(np.array_equal(arg, image) for arg, _ in logger_calls + unlock_calls))

    def test_rescan_uses_each_logger_template_original_similarity(self):
        for template, similarity in ((TEMPLATE_STORAGE_LOGGER, LOGGER_SIMILARITY),
                                     (TEMPLATE_STORAGE_LOGGER_UNLOCK, UNLOCK_SIMILARITY)):
            with self.subTest(template=template.name):
                device = FakeDevice(FakeClock())
                handler = self.handler(device)
                button = Button((0, 0, 10, 10), (), (0, 0, 10, 10), name=template.name)
                hit = Button((100, 200, 210, 240), (), (100, 200, 210, 240), name=template.name)
                other = (TEMPLATE_STORAGE_LOGGER_UNLOCK if template is TEMPLATE_STORAGE_LOGGER
                         else TEMPLATE_STORAGE_LOGGER)
                rescan, rescan_calls = self.stub(template, [[hit]])
                untouched, untouched_calls = self.stub(other)
                with patch('module.base.timer.time', device.clock), rescan, untouched:
                    handler._storage_item_use(button)
                # 重扫命中只点一次，随后按确认计时器退出，不再无意义重复截图
                self.assertEqual(device.clicks, [hit])
                self.assertGreaterEqual(device.screenshots, 3)
                # 每次重扫都用该模板原相似度，而不是被调用方的 0.5 覆盖
                self.assertEqual([similarity for _, similarity in rescan_calls],
                                 [similarity] * len(rescan_calls))
                self.assertTrue(all(np.array_equal(arg, rgb2gray(device.image))
                                    for arg, _ in rescan_calls))
                self.assertEqual(untouched_calls, [])

    def test_storage_logger_use_all_scans_with_per_template_similarity(self):
        device = FakeDevice(FakeClock())
        handler = self.handler(device)
        item = Button((100, 200, 210, 240), (), (100, 200, 210, 240), name=TEMPLATE_STORAGE_LOGGER.name)
        # 第一次是仓库扫描命中，第二次是 _storage_item_use 的重扫命中，之后记录仪已用掉
        logger_match, logger_calls = self.stub(TEMPLATE_STORAGE_LOGGER, [[item], [item]])
        unlock_match, unlock_calls = self.stub(TEMPLATE_STORAGE_LOGGER_UNLOCK)
        with patch('module.base.timer.time', device.clock), logger_match, unlock_match, \
                patch.object(storage, 'SCROLL_STORAGE') as scroll:
            scroll.appear.return_value = False
            handler.storage_logger_use_all()
        self.assertTrue(logger_calls)
        self.assertTrue(unlock_calls)
        self.assertEqual({similarity for _, similarity in logger_calls}, {LOGGER_SIMILARITY})
        self.assertEqual({similarity for _, similarity in unlock_calls}, {UNLOCK_SIMILARITY})
        # 记录仪用掉后重扫无命中，外层扫描退出
        self.assertEqual(device.clicks, [item])
        scroll.set_bottom.assert_not_called()

    def test_storage_logger_use_all_stops_when_no_logger_matches(self):
        device = FakeDevice(FakeClock())
        handler = self.handler(device)
        handler._storage_item_use = Mock()
        logger_match, logger_calls = self.stub(TEMPLATE_STORAGE_LOGGER)
        unlock_match, unlock_calls = self.stub(TEMPLATE_STORAGE_LOGGER_UNLOCK)
        with logger_match, unlock_match, patch.object(storage, 'SCROLL_STORAGE') as scroll:
            scroll.appear.return_value = False
            handler.storage_logger_use_all()
        handler._storage_item_use.assert_not_called()
        self.assertEqual(device.clicks, [])
        self.assertEqual([similarity for _, similarity in logger_calls], [LOGGER_SIMILARITY])
        self.assertEqual([similarity for _, similarity in unlock_calls], [UNLOCK_SIMILARITY])

    def test_failed_rescan_clicks_are_bounded_by_device_click_budget(self):
        device = BudgetDevice(FakeClock())
        handler = self.handler(device)
        button = Button((0, 0, 10, 10), (), (0, 0, 10, 10), name=TEMPLATE_STORAGE_LOGGER_UNLOCK.name)
        hit = Button((100, 200, 210, 240), (), (100, 200, 210, 240),
                     name=TEMPLATE_STORAGE_LOGGER_UNLOCK.name)
        rescan, rescan_calls = self.stub(TEMPLATE_STORAGE_LOGGER_UNLOCK, [[hit]] * 60)
        with patch('module.base.timer.time', device.clock), rescan:
            with self.assertRaises(GameTooManyClickError):
                handler._storage_item_use(button)
        # 点不动的重扫由既有全局点击预算收口，而不是静默返回
        self.assertEqual(len(device.clicks), 50)
        self.assertEqual(len(rescan_calls), 50)

    def test_sample_item_keeps_direct_click_path(self):
        device = FakeDevice(FakeClock())
        handler = self.handler(device, gates=[True])
        sample = Button((0, 0, 10, 10), (), (0, 0, 10, 10), name='TEMPLATE_STORAGE_OFFENSE')
        boxes = [False, True]
        handler.appear_then_click = Mock(
            side_effect=lambda button, **kwargs: boxes.pop(0) if button is BOX_USE and boxes else False)
        logger_match, logger_calls = self.stub(TEMPLATE_STORAGE_LOGGER)
        unlock_match, unlock_calls = self.stub(TEMPLATE_STORAGE_LOGGER_UNLOCK)
        with patch('module.base.timer.time', device.clock), logger_match, unlock_match:
            handler._storage_item_use(sample)
        self.assertEqual(device.clicks, [sample])
        self.assertEqual(logger_calls, [])
        self.assertEqual(unlock_calls, [])


if __name__ == '__main__':
    unittest.main()
