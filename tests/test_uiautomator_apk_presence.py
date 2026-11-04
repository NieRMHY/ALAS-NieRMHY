"""uiautomator2 辅助 APK 存在性检查：不依赖可选的 versionName。"""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

# 先安装项目设备依赖兼容补丁，不连接设备或加载用户配置。
from module.device.device import Device  # noqa: F401
from module.device.method import utils
from requests.exceptions import ConnectionError


MAIN = 'com.github.uiautomator'
TEST = 'com.github.uiautomator.test'


class TestUiautomatorApkPresence(unittest.TestCase):
    def client(self, missing=None, empty_path=None, main_version='2.3.3'):
        client = utils.Device.__new__(utils.Device)

        def shell(command):
            if command[0:2] == ['pm', 'path']:
                package = command[2]
                if package == missing:
                    return SimpleNamespace(exit_code=1, output=f'Error: package {package} not found')
                return SimpleNamespace(
                    exit_code=0, output='' if package == empty_path else f'package:/data/app/{package}/base.apk\n',
                )
            if command[0:2] == ['dumpsys', 'package']:
                package = command[2]
                # 实际随库分发的测试 APK 未声明 versionName。
                output = f'Package [{package}]\n'
                if package == MAIN:
                    output += f'  versionName={main_version}\n'
                return SimpleNamespace(exit_code=0, output=output)
            raise AssertionError(f'非预期命令：{command}')

        client.shell = Mock(side_effect=shell)
        return client

    def test_installed_test_apk_without_version_name_is_accepted(self):
        client = self.client()

        self.assertFalse(client._is_apk_required())

        self.assertEqual([item.args[0] for item in client.shell.call_args_list], [
            ['pm', 'path', MAIN], ['pm', 'path', TEST],
        ])

    def test_absent_main_or_test_apk_still_requires_installation(self):
        for package in (MAIN, TEST):
            with self.subTest(package=package):
                self.assertTrue(self.client(missing=package)._is_apk_required())

    def test_success_exit_without_package_path_is_not_treated_as_installed(self):
        for package in (MAIN, TEST):
            with self.subTest(package=package):
                self.assertTrue(self.client(empty_path=package)._is_apk_required())

    def test_apk_presence_is_independent_of_version_format(self):
        self.assertFalse(self.client(main_version='custom-build')._is_apk_required())

    def test_transport_failure_preserves_original_exception(self):
        client = self.client()
        error = ConnectionError('agent 连接断开')
        client.shell.side_effect = error

        with self.assertRaises(ConnectionError) as caught:
            client._is_apk_required()

        self.assertIs(caught.exception, error)

    def test_reset_starts_existing_helpers_and_installs_only_missing_apks(self):
        for missing in (None, TEST):
            with self.subTest(missing=missing):
                client = self.client(missing=missing)

                def shell(command):
                    if command == 'getprop ro.product.brand':
                        return SimpleNamespace(output='MuMu')
                    return client.shell(command)

                recovery = SimpleNamespace(
                    shell=shell, logger=Mock(), uiautomator=Mock(),
                    _kill_process_by_name=Mock(), _is_apk_required=client._is_apk_required,
                    _setup_uiautomator=Mock(), _is_alive=Mock(return_value=True), show_float_window=Mock(),
                )
                with patch('uiautomator2.time.sleep'):
                    self.assertTrue(utils.Device._force_reset_uiautomator_v2(recovery))

                recovery.uiautomator.start.assert_called_once_with()
                self.assertEqual(recovery._setup_uiautomator.call_count, int(missing is not None))


if __name__ == '__main__':
    unittest.main()
