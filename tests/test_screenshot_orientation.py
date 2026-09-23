"""截图几何回归：隔离设备、配置和预览，仅处理内存中的四色图。"""

import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np


def load_screenshot():
    """加载真实截图实现，替换会触及设备、配置或日志的依赖。"""
    replacements = {}

    def module(name, **attrs):
        stub = ModuleType(name)
        stub.__dict__.update(attrs)
        replacements[name] = stub

    module('module.runtime.preview', publish=Mock())
    module('module.base.decorator', cached_property=property)
    module('module.base.timer', Timer=Mock())
    module('module.base.utils', get_color=lambda image, area: image.mean(axis=(0, 1)),
           image_size=lambda image: (image.shape[1], image.shape[0]),
           limit_in=Mock(), save_image=Mock(), set_template_match_non_native_720p=Mock())
    module('module.config.time_source', now=Mock())
    for name, cls in [('adb', 'Adb'), ('ascreencap', 'AScreenCap'), ('droidcast', 'DroidCast'),
                      ('ldopengl', 'LDOpenGL'), ('nemu_ipc', 'NemuIpc'), ('scrcpy', 'Scrcpy'), ('wsa', 'WSA')]:
        module(f'module.device.method.{name}', **{cls: type(cls, (), {})})
    module('module.exception', RequestHumanTakeover=type('RequestHumanTakeover', (Exception,), {}),
           ScriptError=type('ScriptError', (Exception,), {}))
    module('module.logger', logger=Mock())
    path = Path(__file__).resolve().parents[1] / 'module/device/screenshot.py'
    spec = importlib.util.spec_from_file_location('_screenshot_orientation_test', path)
    loaded = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, replacements):
        spec.loader.exec_module(loaded)
    return loaded


def color_image(width, height):
    image = np.empty((height, width, 3), dtype=np.uint8)
    image[:height // 2, :width // 2] = (255, 0, 0)
    image[:height // 2, width // 2:] = (0, 255, 0)
    image[height // 2:, :width // 2] = (0, 0, 255)
    image[height // 2:, width // 2:] = (255, 255, 255)
    return image


class TestScreenshotOrientation(unittest.TestCase):
    def setUp(self):
        self.module = load_screenshot()

    def device(self, image, orientation, method='ADB', override=''):
        class FakeScreenshot(self.module.Screenshot):
            screenshot_method_override = override

            @property
            def screenshot_methods(self):
                return {method: self.screenshot_adb, 'overridden': self.screenshot_adb}

        device = object.__new__(FakeScreenshot)
        device.config = SimpleNamespace(Emulator_ScreenshotMethod=method, Error_SaveError=False,
                                        Emulator_ScreenshotDedithering=False, Emulator_Serial='fake')
        device._screenshot_interval = Mock()
        device.screenshot_adb = Mock(side_effect=lambda: image.copy())
        device.orientation = 0
        device.get_orientation = Mock(side_effect=lambda: setattr(device, 'orientation', orientation))
        return device

    def test_portrait_rotation_precedes_resize_for_adb_and_u2(self):
        for method in ('ADB', 'ADB_nc', 'uiautomator2'):
            for width, height in ((720, 1280), (1080, 1920)):
                for orientation, rotation in ((1, cv2.ROTATE_90_COUNTERCLOCKWISE),
                                               (3, cv2.ROTATE_90_CLOCKWISE)):
                    with self.subTest(method=method, size=(width, height), orientation=orientation):
                        source = color_image(width, height)
                        device = self.device(source, orientation, method)
                        expected = cv2.rotate(source, rotation)
                        if width != 720:
                            expected = device.resize_screenshot_to_720p(expected)
                        actual = device.screenshot()
                        np.testing.assert_array_equal(actual, expected)
                        self.assertTrue(device._screen_size_checked)
                        device.get_orientation.assert_called_once()
                        self.module.set_template_match_non_native_720p.assert_called_with(
                            True, resolution=(width, height))

    def test_landscape_backends_are_not_rotated_again(self):
        for method in ('ADB', 'uiautomator2', 'DroidCast', 'DroidCast_raw', 'scrcpy', 'nemu_ipc', 'ldopengl'):
            for width, height in ((1280, 720), (1920, 1080)):
                for orientation in (0, 1, 2, 3):
                    with self.subTest(method=method, size=(width, height), orientation=orientation):
                        source = color_image(width, height)
                        device = self.device(source, orientation, method)
                        device.orientation = orientation
                        expected = source if width == 1280 else device.resize_screenshot_to_720p(source)
                        np.testing.assert_array_equal(device.screenshot(), expected)
                        device.get_orientation.assert_not_called()
                        self.module.set_template_match_non_native_720p.assert_called_with(
                            width != 1280, resolution=(width, height))

    def test_uncorrected_portrait_is_not_stretched_or_cached_as_landscape(self):
        for orientation in (0, 2):
            for width, height in ((720, 1280), (1080, 1920)):
                with self.subTest(orientation=orientation, size=(width, height)):
                    source = color_image(width, height)
                    device = self.device(source, orientation)
                    device._screen_size_checked = True
                    np.testing.assert_array_equal(device.screenshot(), source)
                    self.assertFalse(device._screen_size_checked)
                    device.screenshot_adb.side_effect = lambda: color_image(1280, 720)
                    self.assertEqual(device.screenshot().shape, (720, 1280, 3))
                    self.assertTrue(device._screen_size_checked)

    def test_orientation_helper_uses_argument_dimensions(self):
        source = color_image(720, 1280)
        device = self.device(source, 1)
        device.orientation = 1
        device.image = color_image(1280, 720)
        np.testing.assert_array_equal(device._handle_orientated_image(source),
                                      cv2.rotate(source, cv2.ROTATE_90_COUNTERCLOCKWISE))

    def test_override_uses_same_geometry_pipeline_and_publishes_final_image(self):
        device = self.device(color_image(720, 1280), 3, override='overridden')
        result = device.screenshot()
        self.assertEqual(result.shape, (720, 1280, 3))
        self.assertIs(self.module.publish.call_args.args[0], result)


if __name__ == '__main__':
    unittest.main()
