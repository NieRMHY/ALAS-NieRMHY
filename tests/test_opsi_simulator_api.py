"""大世界模拟器的真实 WebSocket 接口、权限与只读配置回归。"""
import base64
import json
import tempfile
import threading
import unittest
from unittest.mock import patch

from starlette.testclient import TestClient

from module.api.app import create_app
from tests.test_api import fixture
from tests.test_os_simulator import simulation_data


class OpsiSimulatorApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = fixture(self.temp.name)
        self.path = self.root / 'config/testpilot.json'
        self.path.write_text(json.dumps(simulation_data(Deterministic=True, Draw='single_sample')),
                             encoding='utf-8')
        self.app = create_app(root=self.root, password='', manage_runtime=False, mount_mcp=False)
        self.client = self.enterContext(TestClient(self.app))
        self.router = self.app.state.gateway.router
        self.request_id = 0

    def request(self, ws, method, **params):
        self.request_id += 1
        request_id = str(self.request_id)
        ws.send_json({'v': 1, 'type': 'request', 'id': request_id, 'method': method, 'params': params})
        while True:
            result = ws.receive_json()
            if result.get('id') == request_id:
                return result

    def test_run_results_logs_and_figure_do_not_start_game_or_save_config(self):
        before = self.path.read_bytes(), self.path.stat().st_mtime_ns
        with patch.object(self.router.runtime, 'start') as game_start, \
                patch.object(self.router.runtime, 'stop') as game_stop, \
                self.client.websocket_connect('/api/v1/ws') as ws:
            ws.receive_json()
            idle = self.request(ws, 'opsi.simulator.status', instance='testpilot')
            self.assertTrue(idle['ok'])
            self.assertEqual('idle', idle['result']['state'])
            started = self.request(ws, 'opsi.simulator.start', instance='testpilot')
            self.assertTrue(started['ok'])
            simulator = self.router.opsi_simulator.manager.runs['testpilot'][0]
            simulator._thread.join(timeout=30)
            status = self.request(ws, 'opsi.simulator.status', instance='testpilot')['result']
            self.assertEqual('completed', status['state'], status['error'])
            self.assertEqual(1, status['completedSamples'])
            self.assertEqual(3, status['result']['cl1Count'])
            self.assertTrue(any('模拟结果' in entry['text'] for entry in status['logs']['entries']))
            self.assertNotIn(str(self.root), status['figure'])
            image = self.request(ws, 'opsi.simulator.figure', instance='testpilot')['result']['image']
            self.assertTrue(base64.b64decode(image.split(',', 1)[1]).startswith(b'\x89PNG\r\n\x1a\n'))
            delta = self.request(ws, 'opsi.simulator.status', instance='testpilot', after=status['logs']['cursor'])
            self.assertFalse(delta['result']['logs']['entries'])
            self.assertTrue(self.request(ws, 'opsi.simulator.stop', instance='testpilot')['ok'])
            game_start.assert_not_called()
            game_stop.assert_not_called()
        self.assertEqual(before, (self.path.read_bytes(), self.path.stat().st_mtime_ns))

    def test_demo_allows_status_but_rejects_start_and_stop(self):
        with patch.dict('os.environ', {'DEMO': '1'}), self.client.websocket_connect('/api/v1/ws') as ws:
            ws.receive_json()
            self.assertTrue(self.request(ws, 'opsi.simulator.status', instance='testpilot')['ok'])
            self.assertTrue(self.request(ws, 'opsi.simulator.figure', instance='testpilot')['ok'])
            for method in ('opsi.simulator.start', 'opsi.simulator.stop'):
                self.assertEqual('READ_ONLY', self.request(ws, method, instance='testpilot')['error']['code'])

    def test_instance_and_cursor_parameters_are_checked(self):
        with self.client.websocket_connect('/api/v1/ws') as ws:
            ws.receive_json()
            for method in ('status', 'start', 'stop', 'figure'):
                response = self.request(ws, f'opsi.simulator.{method}', instance='../private')
                self.assertEqual('INVALID_PARAMS', response['error']['code'])
            response = self.request(ws, 'opsi.simulator.status', instance='testpilot', after=-1)
            self.assertEqual('INVALID_PARAMS', response['error']['code'])
            response = self.request(ws, 'opsi.simulator.status', instance='missing')
            self.assertEqual('NOT_FOUND', response['error']['code'])

    def test_service_close_interrupts_threads(self):
        manager = self.router.opsi_simulator.manager
        entered = threading.Event()

        def wait_for_interrupt():
            entered.set()
            manager.runs['testpilot'][0]._stop_event.wait(timeout=5)

        with patch('module.os_simulator.simulator.OSSimulator.precompile', side_effect=wait_for_interrupt):
            self.router.opsi_simulator.start('testpilot')
            self.assertTrue(entered.wait(timeout=5))
            simulator = manager.runs['testpilot'][0]
            self.router.close()
        self.assertEqual('interrupted', simulator.state)
        self.assertFalse(simulator.is_running)
        self.assertTrue(manager.closed)
        self.assertFalse(manager.runs)

    def test_simulator_requires_authentication(self):
        app = create_app(root=self.root, password='secret', manage_runtime=False, mount_mcp=False)
        with TestClient(app) as client, client.websocket_connect('/api/v1/ws') as ws:
            ws.receive_json()
            for method in ('status', 'start', 'stop', 'figure'):
                response = self.request(ws, f'opsi.simulator.{method}', instance='testpilot')
                self.assertEqual('UNAUTHORIZED', response['error']['code'])
            self.assertIsNone(app.state.gateway.router._opsi_simulator)
            self.assertTrue(self.request(ws, 'auth.login', password='secret')['ok'])
            self.assertTrue(self.request(ws, 'opsi.simulator.status', instance='testpilot')['ok'])


if __name__ == '__main__':
    unittest.main()
