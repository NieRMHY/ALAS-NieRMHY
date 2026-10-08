"""验证生产服务公开完整构建资源（含正确 MIME），且不会把缺失图片当作页面。"""
import mimetypes
import tempfile
import unittest

from starlette.testclient import TestClient

from module.api.app import create_app
from module.api.static import ensure_static_mime_types
from tests.test_api import fixture


class FrontendStaticTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = fixture(temporary.name)
        dist = root / 'frontend/dist'
        (dist / 'assets').mkdir(parents=True)
        (dist / 'icons').mkdir()
        (dist / 'index.html').write_text('<html>前端页面</html>', encoding='utf-8')
        (dist / '.source-fingerprint').write_text('internal')
        (dist / 'oil.webp').write_bytes(b'RIFF-test-image')
        (dist / 'icons/nested.svg').write_text('<svg/>')
        (dist / 'assets/app.css').write_text('body {color: red}')
        self.client = TestClient(create_app(root=root, password='', manage_runtime=False, mount_mcp=False))

    def test_public_resources_are_files(self):
        response = self.client.get('/oil.webp')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b'RIFF-test-image')
        self.assertEqual(response.headers['content-type'], 'image/webp')
        self.assertEqual(response.headers['cache-control'], 'no-cache')
        self.assertEqual(self.client.head('/oil.webp').content, b'')
        self.assertEqual(self.client.get('/icons/nested.svg').text, '<svg/>')
        self.assertIn('text/css', self.client.get('/assets/app.css').headers['content-type'])

    def test_navigation_and_api_keep_their_routes(self):
        for path in ['/', '/some/page']:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertIn('前端页面', response.text)
            self.assertEqual(response.headers['cache-control'], 'no-cache')
        self.assertEqual(self.client.get('/healthz').json()['status'], 'ok')

    def test_missing_and_private_resources_are_not_pages(self):
        for path in ['/missing.webp', '/assets/missing.js', '/.source-fingerprint',
                     '/%2e%2e/%2e%2e/config/testpilot.json']:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)


class ItemTemplateStaticTests(unittest.TestCase):
    """缺少专用图标时，领奖模板仍通过同一个资源地址提供。"""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = fixture(temporary.name)

    def write_template(self, directory, name, data):
        path = self.root / 'assets' / directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def client(self):
        return TestClient(create_app(root=self.root, password='', manage_runtime=False, mount_mcp=False))

    def test_opsi_popup_template_fills_missing_reward_icon(self):
        self.write_template('stats/opsi_items', 'GearDesignPlanT5.png', b'popup-template')
        response = self.client().get('/opsi-items/GearDesignPlanT5.png')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b'popup-template')
        self.assertEqual(response.headers['content-type'], 'image/png')

    def test_reward_icon_has_priority_over_popup_template(self):
        self.write_template('stats/opsi_reward_items', 'PlateGeneralT4.png', b'reward-template')
        self.write_template('stats/opsi_items', 'PlateGeneralT4.png', b'popup-template')
        self.assertEqual(self.client().get('/opsi-items/PlateGeneralT4.png').content, b'reward-template')

    def test_research_icon_uses_basic_template_when_missing(self):
        self.write_template('stats_basic', 'CognitiveChips.png', b'basic-template')
        self.assertEqual(self.client().get('/research-items/CognitiveChips.png').content, b'basic-template')

    def test_missing_or_outside_template_returns_404(self):
        self.write_template('stats/opsi_items', 'GearDesignPlanT5.png', b'popup-template')
        client = self.client()
        for path in ('/opsi-items/missing.png', '/opsi-items/..%2F..%2F..%2Fconfig/testpilot.json'):
            with self.subTest(path=path):
                self.assertEqual(client.get(path).status_code, 404)


class StaticMimeTypeTests(unittest.TestCase):
    """系统把 .js 关联成 text/plain 时，服务端必须自己写回标准 MIME。

    浏览器对 ES module 的 MIME 检查是强制的：资源带 text/plain 就直接拒绝执行，
    前端一个字节都跑不起来，界面整片空白（2026-09-20 实机白屏即此因）。
    Windows 上 Python 的 mimetypes 会读注册表的文件关联，而且是直接覆盖标准表，
    所以映射不能交给系统决定。
    """

    def setUp(self):
        self.addCleanup(self._restore_js_mapping)
        self.original = mimetypes.guess_type('probe.js')[0]

    def _restore_js_mapping(self):
        """还原测试前的映射，避免污染同一进程里后续的其他测试。"""
        if self.original:
            mimetypes.add_type(self.original, '.js')

    def test_polluted_system_mapping_is_overridden(self):
        # 模拟被改坏的注册表项：read_windows_registry 正是这样写进标准表的
        mimetypes.add_type('text/plain', '.js')
        self.assertEqual(mimetypes.guess_type('probe.js')[0], 'text/plain')

        ensure_static_mime_types()

        self.assertEqual(mimetypes.guess_type('probe.js')[0], 'text/javascript')

    def test_served_assets_keep_executable_mime(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = fixture(temporary.name)
        dist = root / 'frontend/dist'
        (dist / 'assets').mkdir(parents=True)
        (dist / 'index.html').write_text('<html>前端页面</html>', encoding='utf-8')
        (dist / 'assets/index.js').write_text('export const ok = 1')
        (dist / 'assets/app.css').write_text('body {color: red}')
        mimetypes.add_type('text/plain', '.js')
        ensure_static_mime_types()
        client = TestClient(create_app(root=root, password='', manage_runtime=False, mount_mcp=False))

        self.assertIn('text/javascript', client.get('/assets/index.js').headers['content-type'])
        self.assertIn('text/css', client.get('/assets/app.css').headers['content-type'])
