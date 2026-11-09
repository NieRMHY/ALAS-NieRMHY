"""原生截图、触控与应用管理的离线回归，不连接模拟器或下载 atx-agent。"""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

import cv2
import numpy as np

# 先安装项目的 pkg_resources 兼容补丁，不构造设备或加载用户配置。
from module.device.device import Device  # noqa: F401
from module.daemon.benchmark import Benchmark
from module.device.app_control import AppControl
from requests.exceptions import HTTPError, ReadTimeout


class TestNativeAppControl(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch('module.device.app_control.logger'))
        self.enterContext(patch('module.device.method.adb.logger'))

    def device(self, method):
        device = AppControl.__new__(AppControl)
        device.config = SimpleNamespace(
            Emulator_ControlMethod=method, Emulator_Serial='127.0.0.1:16416',
        )
        device.serial = device.config.Emulator_Serial
        device.package = 'com.bilibili.azurlane'
        device.adb_shell = Mock()
        # ADB 应用管理不访问 u2；属于 u2 家族的方法应透传该错误。
        for action in ('app_current', 'app_start', 'app_stop', 'dump_hierarchy'):
            setattr(device, f'{action}_uiautomator2', Mock(side_effect=HTTPError('403 Forbidden')))
        return device

    def test_adb_foreground_check_works_without_atx_agent(self):
        for method in ('ADB',):
            with self.subTest(method=method):
                device = self.device(method)
                device.adb_shell.return_value = (
                    'mCurrentFocus=Window{123abc u0 '
                    'com.bilibili.azurlane/com.manjuu.azurlane.MainActivity}'
                )

                self.assertTrue(device.app_is_running())

                device.adb_shell.assert_called_once_with(['dumpsys', 'window', 'windows'])
                device.app_current_uiautomator2.assert_not_called()

    def test_adb_foreground_check_keeps_activity_fallback(self):
        for method in ('ADB',):
            with self.subTest(method=method):
                device = self.device(method)
                device.adb_shell.side_effect = [
                    'mCurrentFocus=null',
                    'ACTIVITY com.example.launcher/.MainActivity abc123 pid=10\n'
                    'ACTIVITY com.bilibili.azurlane/com.manjuu.azurlane.MainActivity def456 pid=20',
                ]

                self.assertTrue(device.app_is_running())

                self.assertEqual(device.adb_shell.call_args_list, [
                    call(['dumpsys', 'window', 'windows']), call(['dumpsys', 'activity', 'top']),
                ])
                device.app_current_uiautomator2.assert_not_called()

    def test_adb_foreground_check_does_not_assume_game_is_running(self):
        device = self.device('ADB')
        device.adb_shell.return_value = 'mCurrentFocus=Window{123abc u0 com.example.launcher/.MainActivity}'

        self.assertFalse(device.app_is_running())

    def test_adb_start_stop_and_hierarchy_do_not_require_atx_agent(self):
        for method in ('ADB',):
            with self.subTest(method=method):
                device = self.device(method)
                device.app_start_adb = Mock()
                device.dump_hierarchy_adb = Mock(return_value=object())
                device._hierarchy_interval = Mock()

                device.app_start()
                device.app_stop()
                hierarchy = device.dump_hierarchy()

                device.app_start_adb.assert_called_once_with()
                device.adb_shell.assert_called_once_with(['am', 'force-stop', device.package])
                self.assertIs(hierarchy, device.dump_hierarchy_adb.return_value)
                for action in ('app_current', 'app_start', 'app_stop', 'dump_hierarchy'):
                    getattr(device, f'{action}_uiautomator2').assert_not_called()

    def test_agent_based_controls_keep_existing_app_routing(self):
        for method in ('uiautomator2', 'minitouch', 'scrcpy', 'MaaTouch', 'nemu_ipc'):
            with self.subTest(method=method):
                device = self.device(method)
                for action in ('app_current', 'app_start', 'app_stop', 'dump_hierarchy'):
                    getattr(device, f'{action}_uiautomator2').side_effect = None
                device.app_current_uiautomator2.return_value = device.package
                device.app_start_adb = Mock()
                device.dump_hierarchy_adb = Mock()
                device._hierarchy_interval = Mock()

                self.assertTrue(device.app_is_running())
                device.app_start()
                device.app_stop()
                self.assertIs(device.dump_hierarchy(), device.dump_hierarchy_uiautomator2.return_value)

                for action in ('app_current', 'app_start', 'app_stop', 'dump_hierarchy'):
                    getattr(device, f'{action}_uiautomator2').assert_called_once_with()
                device.app_start_adb.assert_not_called()
                device.dump_hierarchy_adb.assert_not_called()
                device.adb_shell.assert_not_called()

    def test_native_control_app_query_preserves_u2_errors(self):
        for method in ('MaaTouch', 'nemu_ipc'):
            with self.subTest(method=method):
                device = self.device(method)
                with self.assertRaises(HTTPError):
                    device.app_current()
                device.app_current_uiautomator2.assert_called_once_with()
                device.adb_shell.assert_not_called()


class TestScreenshotBenchmarkCompatibility(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch('module.daemon.benchmark.logger'))
        self.bench = Benchmark.__new__(Benchmark)
        self.bench.config = SimpleNamespace(
            Benchmark_DeviceType='emulator', Benchmark_TestScene='screenshot',
            Emulator_ScreenshotMethod='auto', Emulator_ControlMethod='MaaTouch',
        )
        self.bench.device = SimpleNamespace(
            serial='127.0.0.1:16416', sdk_ver=35, is_mumu_family=True,
            is_chinac_phone_cloud=False, ldopengl_available=Mock(return_value=False),
        )

    def screenshot_methods(self, u2_error=None):
        self.clock = [0.0]

        def capture(name, cost):
            def screenshot():
                self.clock[0] += cost
            return Mock(__name__=name, side_effect=screenshot)

        methods = {
            'ADB': capture('screenshot_adb', 0.4),
            'ADB_nc': capture('screenshot_adb_nc', 0.1),
            'uiautomator2': Mock(side_effect=AssertionError('测速不应进入普通后端的多轮恢复')),
            'DroidCast': capture('screenshot_droidcast', 0.02),
            'DroidCast_raw': capture('screenshot_droidcast_raw', 0.01),
        }
        self.bench.device.screenshot_methods = methods
        self.bench._u2_benchmark_client = Mock()
        encoded = cv2.imencode('.png', np.zeros((2, 3, 3), dtype=np.uint8))[1].tobytes()
        reply = self.response(content=encoded)

        def get(*args, **kwargs):
            self.clock[0] += 0.05
            if u2_error is not None:
                raise u2_error
            return reply

        self.bench._u2_benchmark_client.http.get.side_effect = get
        self.enterContext(patch('module.daemon.benchmark.time.perf_counter', side_effect=lambda: self.clock[0]))
        return methods

    @staticmethod
    def response(content=b'', payload=None, status=200):
        reply = Mock(content=content, status_code=status)
        reply.__enter__ = Mock(return_value=reply)
        reply.__exit__ = Mock(return_value=False)
        reply.json.return_value = payload
        if status != 200:
            reply.raise_for_status.side_effect = HTTPError(status)
        return reply

    def test_mumu15_auto_tests_healthy_u2_and_can_select_it(self):
        methods = self.screenshot_methods()

        self.assertEqual(self.bench.run_simple_screenshot_benchmark(), 'uiautomator2')

        get = self.bench._u2_benchmark_client.http.get
        self.assertEqual(get.call_count, 3)
        get.assert_called_with('/screenshot/0', timeout=(3, 5), retry=False)
        methods['uiautomator2'].assert_not_called()

    def test_mumu15_auto_skips_u2_only_after_one_failed_attempt(self):
        for error in (HTTPError('403 Forbidden'), ReadTimeout('读取超时')):
            with self.subTest(error=type(error).__name__):
                methods = self.screenshot_methods(u2_error=error)
                self.assertEqual(self.bench.run_simple_screenshot_benchmark(), 'ADB_nc')
                get = self.bench._u2_benchmark_client.http.get
                get.assert_called_once_with('/screenshot/0', timeout=(3, 5), retry=False)
                self.assertEqual(methods['ADB'].call_count, 3)
                self.assertEqual(methods['ADB_nc'].call_count, 3)
                for method in ('uiautomator2', 'DroidCast', 'DroidCast_raw'):
                    methods[method].assert_not_called()
                self.assertEqual(self.bench.config.Emulator_ControlMethod, 'MaaTouch')

    def test_invalid_u2_image_is_failed_and_other_candidates_continue(self):
        self.screenshot_methods()
        self.bench._u2_benchmark_client.http.get.side_effect = None
        self.bench._u2_benchmark_client.http.get.return_value = self.response(content=b'not an image')

        self.assertEqual(self.bench.run_simple_screenshot_benchmark(), 'ADB_nc')

        self.bench._u2_benchmark_client.http.get.assert_called_once()

    def test_full_benchmark_u2_click_failure_is_not_retried(self):
        for error in (ReadTimeout('读取超时'), None):
            with self.subTest(error=error):
                self.bench.TEST_TOTAL = 3
                self.bench.TEST_BEST = 1
                self.bench.device.click_methods = {
                    'uiautomator2': Mock(side_effect=AssertionError('测速不应进入普通点击恢复')),
                    'MaaTouch': Mock(__name__='click_maatouch'),
                }
                self.bench.__dict__.pop('_u2_benchmark_click_client', None)
                self.bench._u2_benchmark_client = Mock()
                self.bench._u2_benchmark_client.http.get.return_value = self.response(payload={'running': True})
                post = self.bench._u2_benchmark_client.http.post
                post.side_effect = error
                post.return_value = self.response(payload={'error': {'code': -32000, 'message': 'service unavailable'}})

                _, fastest = self.bench.benchmark(click=('uiautomator2', 'MaaTouch'), quiet=True)

                self.assertEqual(fastest, 'MaaTouch')
                post.assert_called_once()
                self.assertEqual(post.call_args.kwargs['timeout'], (3, 5))
                self.assertFalse(post.call_args.kwargs['retry'])
                self.bench.device.click_methods['uiautomator2'].assert_not_called()
                self.assertEqual(self.bench.device.click_methods['MaaTouch'].call_count, 3)

    def test_healthy_u2_click_uses_bounded_rpc(self):
        self.bench._u2_benchmark_client = Mock()
        self.bench._u2_benchmark_client.http.get.return_value = self.response(payload={'running': True})
        self.bench._u2_benchmark_client.http.post.return_value = self.response(payload={'result': True})

        self.assertTrue(self.bench._benchmark_u2_click(100, 50))

        self.bench._u2_benchmark_client.http.post.assert_called_once_with(
            '/jsonrpc/0', json={'jsonrpc': '2.0', 'id': 1, 'method': 'click', 'params': [100, 50]},
            timeout=(3, 5), retry=False,
        )

    def test_u2_click_starts_stopped_service_once_and_waits_for_readiness(self):
        self.bench.TEST_TOTAL = 3
        self.bench.TEST_BEST = 1
        client = self.bench._u2_benchmark_client = Mock()
        client.http.get.return_value = self.response(payload={'running': False})
        state = {'starts': 0, 'probes': 0, 'clicks': 0}

        def post(path, **kwargs):
            self.assertFalse(kwargs['retry'])
            if path == '/services/uiautomator':
                state['starts'] += 1
                return self.response(payload={'success': True})
            if kwargs['json']['method'] == 'deviceInfo':
                state['probes'] += 1
                if state['probes'] == 1:
                    return self.response(status=502)
                return self.response(payload={'result': {'sdkInt': 32}})
            state['clicks'] += 1
            if not state['starts'] or state['probes'] < 2:
                return self.response(status=502)
            return self.response(payload={'result': True})

        client.http.post.side_effect = post
        with patch('module.daemon.benchmark.time.sleep'):
            result = self.bench.benchmark_test(self.bench._benchmark_u2_click, 100, 50)

        self.assertIsInstance(result, float)
        self.assertEqual(state, {'starts': 1, 'probes': 2, 'clicks': 3})
        client.http.get.assert_called_once_with('/services/uiautomator', timeout=(3, 5), retry=False)
        client._prepare_atx_agent.assert_not_called()

    def test_u2_click_service_start_timeout_continues_other_candidates(self):
        self.bench.TEST_TOTAL = 3
        self.bench.TEST_BEST = 1
        client = self.bench._u2_benchmark_client = Mock()
        client.http.get.return_value = self.response(payload={'running': False})
        client.http.post.side_effect = [self.response(), self.response(status=502)]
        self.bench.device.click_methods = {
            'uiautomator2': Mock(side_effect=AssertionError('不应进入普通点击恢复')),
            'MaaTouch': Mock(__name__='click_maatouch'),
        }

        with patch('module.daemon.benchmark.time.monotonic', side_effect=[0, 0, 6]), \
                patch('module.daemon.benchmark.time.sleep'):
            _, fastest = self.bench.benchmark(click=('uiautomator2', 'MaaTouch'), quiet=True)

        self.assertEqual(fastest, 'MaaTouch')
        self.assertEqual(client.http.post.call_count, 2)
        self.assertEqual(client.http.post.call_args.kwargs['json']['method'], 'deviceInfo')
        self.assertEqual(self.bench.device.click_methods['MaaTouch'].call_count, 3)
        client._prepare_atx_agent.assert_not_called()

    def test_u2_click_service_start_failure_is_not_retried(self):
        client = self.bench._u2_benchmark_client = Mock()
        client.http.get.return_value = self.response(payload={'running': False})
        client.http.post.return_value = self.response(status=403)

        self.assertEqual(self.bench.benchmark_test(self.bench._benchmark_u2_click, 100, 50), 'Failed')

        client.http.post.assert_called_once_with('/services/uiautomator', timeout=(3, 5), retry=False)
        client._prepare_atx_agent.assert_not_called()

    def test_probe_client_does_not_initialize_keepalive_or_install_agent(self):
        client = Mock()
        with patch('module.daemon.benchmark.u2.connect_usb', return_value=client) as connect:
            self.assertIs(self.bench._u2_benchmark_client, client)
            self.assertIs(self.bench._u2_benchmark_client, client)

        connect.assert_called_once_with(self.bench.device.serial)
        client.set_new_command_timeout.assert_not_called()

    def test_auto_respects_droidcast_sdk_boundaries(self):
        self.bench.benchmark = Mock(return_value=('ADB_nc', 'minitouch'))
        for sdk, supported in ((22, False), (23, True), (32, True), (33, False), (35, False)):
            with self.subTest(sdk=sdk):
                self.bench.device.sdk_ver = sdk
                self.bench.run_simple_screenshot_benchmark()
                candidates = self.bench.benchmark.call_args.args[0]
                self.assertEqual('DroidCast' in candidates, supported)
                self.assertEqual('DroidCast_raw' in candidates, supported)

    def test_older_mumu_and_other_emulators_keep_u2_auto_candidate(self):
        self.bench.benchmark = Mock(return_value=('ADB_nc', 'minitouch'))
        for sdk, is_mumu in ((32, True), (35, False)):
            with self.subTest(sdk=sdk, is_mumu=is_mumu):
                self.bench.device.sdk_ver = sdk
                self.bench.device.is_mumu_family = is_mumu
                self.bench.run_simple_screenshot_benchmark()
                self.assertIn('uiautomator2', self.bench.benchmark.call_args.args[0])


if __name__ == '__main__':
    unittest.main()
