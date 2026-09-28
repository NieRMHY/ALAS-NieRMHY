"""Android 桥协议和本机控制路由的离线回归。"""

import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
from starlette.applications import Starlette
from starlette.testclient import TestClient

from module.api.android import routes
from module.api.protocol import ApiError
from module.device.app_control import AppControl
from module.device.method.azurpilot_android import AzurPilotAndroid
from module.runtime.process_manager import ProcessManager


class FakeSocket:
    def __init__(self, response):
        self.response = bytearray(response)
        self.sent = bytearray()

    def sendall(self, data):
        self.sent.extend(data)

    def recv(self, length):
        chunk = self.response[:length]
        del self.response[:length]
        return bytes(chunk)

    def close(self):
        pass


class BridgeTests(unittest.TestCase):
    def tearDown(self):
        AzurPilotAndroid._azurpilot_android_sock = None

    def test_screenshot_converts_bridge_bgr_to_rgb_and_consumes_frame(self):
        pixels = bytes([1, 2, 3, 255, 4, 5, 6, 255])
        reply = json.dumps({'ok': True, 'length': len(pixels), 'width': 2, 'height': 1,
                            'channels': 4}).encode() + b'\n' + pixels
        socket = FakeSocket(reply)
        with patch.object(AzurPilotAndroid, '_azurpilot_android_connect', return_value=socket):
            image = AzurPilotAndroid().screenshot_azurpilot_android()
        np.testing.assert_array_equal(image, np.array([[[3, 2, 1], [6, 5, 4]]], dtype=np.uint8))
        self.assertEqual(json.loads(socket.sent)['method'], 'screencap')

    def test_bounded_foreground_check_uses_android_bridge(self):
        device = SimpleNamespace(
            config=SimpleNamespace(Emulator_ControlMethod='azurpilot_android'),
            package='com.bilibili.azurlane',
            app_current_azurpilot_android=Mock(return_value='com.bilibili.azurlane'),
            adb_shell=Mock(side_effect=AssertionError('ADB must not be used in Android bridge mode')),
        )

        self.assertTrue(AppControl.app_is_running_bounded(device, timeout=7))
        device.app_current_azurpilot_android.assert_called_once_with(timeout=7)
        device.adb_shell.assert_not_called()


class FakeConfigs:
    def path(self, name):
        if name != 'alas':
            raise ApiError('INVALID_PARAMS', '未知实例')
        return name

    def names(self):
        return ['alas']


class FakeRuntime:
    def __init__(self):
        self.processes = {}

    def start(self, name, task=None):
        proc = SimpleNamespace(alive=True, started_func=task or 'alas',
                               current_task=None, _process=SimpleNamespace(pid=123))
        proc.stop = lambda: setattr(proc, 'alive', False)
        self.processes[name] = proc

    def stop(self, name):
        self.processes[name].alive = False

    def logs(self, name):
        return {'entries': [{'text': 'AzurPilot task started'}]}


class AndroidApiTests(unittest.TestCase):
    def setUp(self):
        self.runtime = FakeRuntime()
        self.environment = patch.dict(os.environ, {'AZURPILOT_ANDROID': '1',
                                                   'AZURPILOT_ANDROID_TOKEN': 'secret'})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.processes = patch.object(ProcessManager, '_processes', self.runtime.processes)
        self.processes.start()
        self.addCleanup(self.processes.stop)
        self.manager = patch.object(ProcessManager, 'get_manager', side_effect=lambda name: self.runtime.processes[name])
        self.manager.start()
        self.addCleanup(self.manager.stop)
        app = Starlette(routes=routes(FakeConfigs(), self.runtime))
        self.client = TestClient(app, client=('127.0.0.1', 20000),
                                 headers={'X-AzurPilot-Android-Token': 'secret'})
        self.addCleanup(self.client.close)

    def test_start_switch_tool_logs_and_stop(self):
        self.assertEqual(self.client.get('/android/configs').json(), {'configs': ['alas']})
        self.assertTrue(self.client.post('/android/start').json()['runner_alive'])
        self.assertTrue(self.client.post('/android/start').json()['runner_alive'])
        tool = self.client.post('/android/tool/start?name=daemon').json()
        self.assertTrue(tool['tool_alive'])
        self.assertFalse(tool['runner_alive'])
        self.assertIn('AzurPilot task', self.client.get('/android/logs').text)
        self.assertFalse(self.client.post('/android/tool/stop').json()['tool_alive'])

    def test_rejects_other_clients_and_old_app_conflict(self):
        self.assertEqual(self.client.get('/android/status', headers={
            'X-AzurPilot-Android-Token': 'wrong'}).status_code, 403)
        with patch('module.api.android._legacy_app_running', return_value=True):
            response = self.client.post('/android/start')
        self.assertEqual(response.status_code, 400)
        self.assertIn('ALAS-AOS', response.json()['error'])


if __name__ == '__main__':
    unittest.main()
