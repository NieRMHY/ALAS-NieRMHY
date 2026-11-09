"""屏幕采集工具回归：使用内存图像和临时目录，不初始化设备或实例配置。"""

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from dev_tools import uiautomator2_screenshot as screenshot


class CaptureFinished(Exception):
    """模拟截图序列结束。"""


class TestWatchScreen(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rng = np.random.default_rng(20261022)
        cls.image = rng.integers(0, 256, size=(720, 1280, 3), dtype=np.uint8)
        cls.changed = rng.integers(0, 256, size=(720, 1280, 3), dtype=np.uint8)

    def capture(self, frames, similarity):
        """运行真实截图循环，替换设备读取和文件写入。"""
        watcher = object.__new__(screenshot.WatchScreen)
        images = iter(frames)

        def take_screenshot():
            try:
                image = next(images)
            except StopIteration:
                raise CaptureFinished from None
            watcher.device.image = image
            return image

        watcher.device = SimpleNamespace(image=None, screenshot=take_screenshot)
        with patch.object(screenshot, 'image_save') as save, \
                patch.object(screenshot.cv2, 'matchTemplate', wraps=cv2.matchTemplate) as matching, \
                patch.object(screenshot, 'logger'):
            with self.assertRaises(CaptureFinished):
                watcher.watch(similarity=similarity)
            return save.call_args_list, matching.call_count

    def test_webp_file_preserves_rgb_pixels(self):
        with TemporaryDirectory(prefix='watch-screen-') as directory:
            file = Path(directory) / 'frame.webp'
            screenshot.image_save(self.image, str(file))
            encoded = np.frombuffer(file.read_bytes(), dtype=np.uint8)
            decoded = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
        decoded = cv2.cvtColor(decoded, cv2.COLOR_BGR2RGB)
        np.testing.assert_array_equal(decoded, self.image)

    def test_png_encoding_stays_lossless(self):
        encoded = screenshot.image_encode(self.image, ext='png')
        decoded = cv2.cvtColor(cv2.imdecode(encoded, cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
        np.testing.assert_array_equal(decoded, self.image)

    def test_default_filter_saves_only_changed_frames(self):
        saved, matches = self.capture([self.image, self.image.copy(), self.changed], 0.98)
        self.assertEqual(len(saved), 2)
        self.assertEqual(matches, 2)
        np.testing.assert_array_equal(saved[0].args[0], self.image)
        np.testing.assert_array_equal(saved[1].args[0], self.changed)
        self.assertTrue(all(Path(call.args[1]).suffix == '.webp' for call in saved))

    def test_save_all_skips_matching_and_does_not_duplicate_initial_frame(self):
        for similarity in (1, 1.5):
            with self.subTest(similarity=similarity):
                frames = [self.image, self.image.copy(), self.changed]
                saved, matches = self.capture(frames, similarity)
                self.assertEqual(len(saved), len(frames))
                self.assertEqual(matches, 0)
                for call, expected in zip(saved, frames):
                    np.testing.assert_array_equal(call.args[0], expected)
                    self.assertEqual(Path(call.args[1]).suffix, '.webp')
