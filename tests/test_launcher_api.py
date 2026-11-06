"""launcher_api（启动器本地通道）的端点契约与限流单元测试。"""
import asyncio
import json
import time
import unittest
from types import SimpleNamespace

from module.api import launcher_api
from module.runtime import launcher_trust
from module.runtime.launcher import launcher_control


class FakeRequest:
    """最小可用的 Starlette 请求替身：只需要处理器真正读取的那几个属性。"""

    def __init__(self, *, body=None, headers=None, host='127.0.0.1', query=None):
        self.client = SimpleNamespace(host=host)
        self.headers = {'host': '127.0.0.1:27548', **(headers or {})}
        self.query_params = query or {}
        self._body = body

    async def json(self):
        """返回预置请求体；None 表示非法 JSON。"""
        if self._body is None:
            raise ValueError('not json')
        return self._body

    async def is_disconnected(self):
        """命令流处理器会轮询它，这里恒定未断开。"""
        return False


class TestLauncherRoutes(unittest.TestCase):
    def test_route_paths_match_launcher_contract(self):
        """端点路径是外部启动器二进制写死的对接面，改名即断连。"""
        paths = {route.path for route in launcher_api.routes()}
        self.assertEqual(paths, {'/api/launcher/status', '/api/launcher/startup', '/api/launcher/stream',
                                 '/api/launcher/report', '/api/launcher/trusted-login', '/launcher-login'})


class TestLocalOnlyEndpoints(unittest.TestCase):
    def setUp(self):
        launcher_api._secret_failures.clear()
        launcher_trust._reset()
        launcher_control.autostart_enabled = None

    def tearDown(self):
        launcher_api._secret_failures.clear()
        launcher_trust._reset()

    def test_remote_requests_are_rejected(self):
        """非本机请求一律 403：远程访问隧道下页面拿不到启动器通道。"""
        remote = {'host': 'example.com'}
        cases = [(launcher_api.status, FakeRequest(headers=remote)),
                 (launcher_api.startup, FakeRequest(headers=remote, body={'enabled': True})),
                 (launcher_api.stream, FakeRequest(headers=remote)),
                 (launcher_api.report, FakeRequest(headers=remote, body={})),
                 (launcher_api.trusted_login, FakeRequest(headers=remote)),
                 (launcher_api.login_seed, FakeRequest(headers=remote, query={'token': 'x'}))]
        for handler, request in cases:
            response = asyncio.run(handler(request))
            self.assertEqual(response.status_code, 403, handler.__name__)

    def test_startup_validates_body(self):
        """enabled 必须是布尔值，非法请求体不能落到启动器命令里。"""
        invalid = asyncio.run(launcher_api.startup(FakeRequest(body=None)))
        self.assertEqual(invalid.status_code, 400)
        wrong_type = asyncio.run(launcher_api.startup(FakeRequest(body={'enabled': 'yes'})))
        self.assertEqual(wrong_type.status_code, 400)

    def test_status_reports_this_request_as_local(self):
        """本机查询带 request_local=True；远端访问在端点层就被 403 挡住。"""
        response = asyncio.run(launcher_api.status(FakeRequest()))
        payload = json.loads(bytes(response.body))
        self.assertTrue(payload['success'])
        self.assertTrue(payload['request_local'])
        self.assertIn('autostart_supported', payload)


class TestTrustedLogin(unittest.TestCase):
    def setUp(self):
        launcher_api._secret_failures.clear()
        launcher_trust._reset()

    def tearDown(self):
        launcher_api._secret_failures.clear()
        launcher_trust._reset()

    def test_disabled_channel_and_bad_secret(self):
        """未由启动器拉起时通道关闭；密钥不对时拒绝并计入失败窗口。"""
        disabled = asyncio.run(launcher_api.trusted_login(FakeRequest(headers={'x-webui-launcher-secret': 'x'})))
        self.assertEqual(disabled.status_code, 403)

        launcher_trust.configure('s3cret', 'key')
        wrong = asyncio.run(launcher_api.trusted_login(FakeRequest(headers={'x-webui-launcher-secret': 'wrong'})))
        self.assertEqual(wrong.status_code, 403)
        self.assertEqual(len(launcher_api._secret_failures), 1)

    def test_rate_limit_blocks_repeated_failures(self):
        """窗口内失败超限后不再尝试校验，避免密钥被反复试探。"""
        launcher_trust.configure('s3cret', 'key')
        launcher_api._secret_failures.extend([time.time()] * launcher_api.SECRET_FAILURE_LIMIT)
        blocked = asyncio.run(launcher_api.trusted_login(FakeRequest(headers={'x-webui-launcher-secret': 's3cret'})))
        self.assertEqual(blocked.status_code, 429)

    def test_seed_page_writes_console_credential_key(self):
        """令牌有效时种子页写入控制台读取的凭据键并跳回首页。"""
        launcher_trust.configure('s3cret', 'k</script>y')
        issued = asyncio.run(launcher_api.trusted_login(FakeRequest(headers={'x-webui-launcher-secret': 's3cret'})))
        token = json.loads(bytes(issued.body))['token']

        page = asyncio.run(launcher_api.login_seed(FakeRequest(query={'token': token})))
        html = bytes(page.body).decode('utf-8')
        self.assertEqual(page.status_code, 200)
        self.assertIn("localStorage.setItem('azurpilot.access-password'", html)
        self.assertNotIn('</script>y', html)  # 密码里的 </script> 已被转义
        self.assertIn('location.replace', html)


if __name__ == '__main__':
    unittest.main()
