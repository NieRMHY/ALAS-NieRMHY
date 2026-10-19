"""notify_api（任务推送通知本地路由）的端点契约单元测试。"""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from starlette.testclient import TestClient

from module.api import notify_api
from module.api.app import create_app

ROOT = Path(__file__).resolve().parents[1]


class FakeRequest:
    """最小可用的 Starlette 请求替身：只需要处理器真正读取的那几个属性。"""

    def __init__(self, *, body=None, host='127.0.0.1', content_type='application/json'):
        self.client = SimpleNamespace(host=host)
        self.headers = {'host': '127.0.0.1:25548', 'content-type': content_type}
        self._body = body

    async def json(self):
        """返回预置请求体；None 表示非法 JSON。"""
        if self._body is None:
            raise ValueError('not json')
        return self._body

    async def is_disconnected(self):
        """通知流处理器会轮询它，这里恒定未断开。"""
        return False


class TestNotifyRoutes(unittest.TestCase):
    def test_route_paths_match_legacy_contract(self):
        """端点路径是外部启动器写死的对接面（旧版 WebUI 传下来），改名即断连。"""
        paths = {route.path for route in notify_api.routes()}
        self.assertEqual(paths, {'/api/notify', '/api/notify_stream'})


class TestNotifyEndpoint(unittest.TestCase):
    def setUp(self):
        notify_api._notification_queue = asyncio.Queue(maxsize=notify_api._NOTIFICATION_QUEUE_MAXSIZE)

    def test_local_post_queues_payload(self):
        """本机 POST 成功入队，且只保留 instance/title/content 三个字段。"""
        response = asyncio.run(notify_api.notify(FakeRequest(
            body={'instance': 'alas', 'title': '标题', 'content': '内容', 'extra': '多余'})))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(bytes(response.body)), {'success': True})
        notification = notify_api._notification_queue.get_nowait()
        self.assertEqual(notification, {'instance': 'alas', 'title': '标题', 'content': '内容'})

    def test_cross_site_content_type_rejected(self):
        """跨站表单只能发 text/plain 类请求体：非 application/json 一律 400，不入队。"""
        response = asyncio.run(notify_api.notify(FakeRequest(
            body={'instance': 'alas', 'title': '伪造', 'content': '钓鱼'},
            content_type='text/plain')))
        self.assertEqual(response.status_code, 400)
        self.assertTrue(notify_api._notification_queue.empty())

    def test_queue_overflow_drops_oldest(self):
        """队列满时挤掉最旧一条再入队，无人消费也不会无限堆积。"""
        queue = asyncio.Queue(maxsize=2)
        notify_api._notification_queue = queue
        for title in ('旧1', '旧2'):
            asyncio.run(notify_api.notify(FakeRequest(body={'instance': 'alas', 'title': title, 'content': ''})))
        asyncio.run(notify_api.notify(FakeRequest(body={'instance': 'alas', 'title': '新', 'content': ''})))
        self.assertEqual(queue.get_nowait()['title'], '旧2')
        self.assertEqual(queue.get_nowait()['title'], '新')
        self.assertTrue(queue.empty())

    def test_remote_post_rejected(self):
        """非本机请求 403，且不入队。"""
        response = asyncio.run(notify_api.notify(FakeRequest(body={'instance': 'alas'}, host='example.com')))
        self.assertEqual(response.status_code, 403)
        self.assertTrue(notify_api._notification_queue.empty())

    def test_invalid_body_rejected(self):
        """非法 JSON 与非对象请求体一律 400，不入队。"""
        invalid = asyncio.run(notify_api.notify(FakeRequest(body=None)))
        not_object = asyncio.run(notify_api.notify(FakeRequest(body=['alas'])))
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(not_object.status_code, 400)
        self.assertTrue(notify_api._notification_queue.empty())


class TestNotifyStreamEndpoint(unittest.TestCase):
    def test_remote_stream_rejected(self):
        """通知流只允许本机订阅：远端连接直接 403。"""
        response = asyncio.run(notify_api.notify_stream(FakeRequest(host='example.com')))
        self.assertEqual(response.status_code, 403)


class TestWebSocketNotification(unittest.TestCase):
    WS_HEADERS = {'host': '127.0.0.1:25548'}
    """TestClient 的 WS 握手 Host 写死 testserver，会误判为远程客户端，这里显式覆盖。"""
    def setUp(self):
        """按 test_api 的隔离模式构造应用：临时配置目录、不启真实进程。"""
        notify_api._notification_queue = asyncio.Queue(maxsize=notify_api._NOTIFICATION_QUEUE_MAXSIZE)
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        (root / 'config').mkdir()
        (root / 'module/config/argument').mkdir(parents=True)
        (root / 'module/config/i18n').mkdir(parents=True)
        for relative in ['module/config/argument/args.json', 'module/config/argument/menu.json',
                         'module/config/i18n/zh-CN.json', 'module/config/i18n/en-US.json', 'config/template.json']:
            (root / relative).parent.mkdir(parents=True, exist_ok=True)
            (root / relative).write_bytes((ROOT / relative).read_bytes())
        self.app = create_app(root=root, password='test', manage_runtime=False, mount_mcp=False)
        # Host 头决定本机判定，默认 testserver 会被当成远程客户端。
        self.client = TestClient(self.app, base_url='http://127.0.0.1:25548', client=('127.0.0.1', 50000))

    def tearDown(self):
        self.temp.cleanup()

    def test_post_broadcasts_to_websocket(self):
        """本机 POST 通知后，已订阅 notifications 的 WS 会话实时收到事件。"""
        with self.client.websocket_connect('/api/v1/ws', headers=self.WS_HEADERS) as ws:
            session = ws.receive_json()
            self.assertEqual(session['topic'], 'session')
            ws.send_json({'v': 1, 'type': 'request', 'id': '1', 'method': 'events.subscribe',
                          'params': {'instance': None, 'topics': ['notifications', 'instances']}})
            reply = ws.receive_json()
            self.assertTrue(reply['ok'], reply)
            response = self.client.post('/api/notify', json={'instance': 'alas', 'title': '标题', 'content': '正文'})
            self.assertEqual(response.status_code, 200)
            event = ws.receive_json()
            self.assertEqual(event['type'], 'event')
            self.assertEqual(event['topic'], 'notifications')
            self.assertEqual(event['data'], {'instance': 'alas', 'title': '标题', 'content': '正文'})

    def test_unsubscribed_session_not_disturbed(self):
        """未订阅 notifications 的会话不受广播影响，POST 仍成功。"""
        with self.client.websocket_connect('/api/v1/ws', headers=self.WS_HEADERS) as ws:
            ws.receive_json()
            response = self.client.post('/api/notify', json={'instance': 'alas', 'title': '标题', 'content': '正文'})
            self.assertEqual(response.status_code, 200)
            self.assertFalse(notify_api._notification_queue.empty())


if __name__ == '__main__':
    unittest.main()
