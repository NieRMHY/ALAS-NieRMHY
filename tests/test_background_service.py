"""背景图服务：SSRF 防护、JSON 取址、图库存取。不联网（抓取部分用桩替换）。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from module.api import background_service as service


class TestEnsurePublicUrl(unittest.TestCase):
    """地址白名单：这是服务端代抓的安全边界，必须逐条守住。"""

    def test_rejects_non_http_scheme(self):
        for url in ('file:///etc/passwd', 'ftp://example.com/a.jpg', 'gopher://x/1', 'data:image/png;base64,AAAA'):
            with self.assertRaises(service.BackgroundError):
                service.ensure_public_url(url)

    def test_rejects_private_loopback_and_link_local(self):
        for url in ('http://127.0.0.1/a.jpg', 'http://10.0.0.5/a.jpg', 'http://192.168.1.1/a.jpg',
                    'http://169.254.169.254/latest/meta-data', 'http://[::1]/a.jpg'):
            with self.assertRaises(service.BackgroundError):
                service.ensure_public_url(url)

    def test_allows_fake_ip_proxy_range(self):
        """198.18.0.0/15 是基准测试段、也是 fake-IP 代理的占位地址，不是内网服务，必须放行。"""
        self.assertEqual(service.ensure_public_url('http://198.18.0.97/api.php'), 'http://198.18.0.97/api.php')

    def test_rejects_cgnat_and_documentation_ranges_that_are_internal(self):
        for url in ('http://0.0.0.0/a.jpg', 'http://[::]/a.jpg'):
            with self.assertRaises(service.BackgroundError):
                service.ensure_public_url(url)

    def test_accepts_public_address(self):
        self.assertEqual(service.ensure_public_url('https://1.1.1.1/a.jpg'), 'https://1.1.1.1/a.jpg')

    def test_rejects_missing_host(self):
        with self.assertRaises(service.BackgroundError):
            service.ensure_public_url('https:///a.jpg')


class TestFirstImageUrl(unittest.TestCase):
    """JSON 型 API：从各种结构里取出图片地址。"""

    def test_lolicon_shape(self):
        payload = {'error': '', 'data': [{'pid': 1, 'url': {'original': 'https://i.pixiv.re/img/1_p0.jpg'}}]}
        self.assertEqual(service.first_image_url(payload), 'https://i.pixiv.re/img/1_p0.jpg')

    def test_flat_list_and_query_suffix(self):
        self.assertEqual(service.first_image_url(['https://cdn.test/a.webp?x=1']), 'https://cdn.test/a.webp?x=1')

    def test_returns_none_when_no_image(self):
        self.assertIsNone(service.first_image_url({'url': 'https://example.com/page.html'}))
        self.assertIsNone(service.first_image_url({'data': []}))


class TestGallery(unittest.TestCase):
    """图库存取：索引读写、删除、路径穿越防护。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.patches = [
            mock.patch.object(service, 'LIBRARY_DIR', self.dir),
            mock.patch.object(service, 'INDEX_FILE', self.dir / 'index.json'),
        ]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in self.patches:
            patch.stop()
        self.tmp.cleanup()

    def test_add_writes_file_and_index(self):
        with mock.patch.object(service, 'fetch_once', return_value={'final_url': 'https://cdn.test/pic.jpg', 'content_type': 'image/jpeg'}), \
             mock.patch.object(service.requests, 'get', return_value=mock.Mock(
                 __enter__=lambda self_: self_, __exit__=lambda *_: False,
                 iter_content=lambda size: [b'abc', b'def'])):
            entry = service.gallery_add('https://cdn.test/pic.jpg', '我的图')
        self.assertEqual(entry['name'], '我的图')
        self.assertEqual(entry['size'], 6)
        self.assertTrue((self.dir / entry['id']).exists())
        self.assertEqual(len(service.gallery_list()), 1)
        self.assertEqual(json.loads((self.dir / 'index.json').read_text(encoding='utf-8'))[0]['id'], entry['id'])

    def test_remove_drops_file_and_index(self):
        (self.dir / 'a.jpg').write_bytes(b'x')
        (self.dir / 'index.json').write_text(json.dumps([{'id': 'a.jpg', 'name': 'a', 'size': 1, 'added': 0, 'kind': 'image'}]), encoding='utf-8')
        self.assertTrue(service.gallery_remove('a.jpg'))
        self.assertFalse((self.dir / 'a.jpg').exists())
        self.assertEqual(service.gallery_list(), [])
        self.assertFalse(service.gallery_remove('a.jpg'))

    def test_list_drops_missing_files(self):
        (self.dir / 'index.json').write_text(json.dumps([
            {'id': 'gone.jpg', 'name': 'gone'}, {'id': 'here.jpg', 'name': 'here'},
        ]), encoding='utf-8')
        (self.dir / 'here.jpg').write_bytes(b'x')
        self.assertEqual([item['id'] for item in service.gallery_list()], ['here.jpg'])

    def test_path_guard_rejects_traversal(self):
        for identifier in ('../config/alas.json', '..\secret', '.hidden', '', 'a/b.jpg'):
            self.assertIsNone(service.gallery_path(identifier))
        (self.dir / 'ok.jpg').write_bytes(b'x')
        self.assertIsNotNone(service.gallery_path('ok.jpg'))

    def test_corrupt_index_reads_as_empty(self):
        (self.dir / 'index.json').write_text('{不是 JSON', encoding='utf-8')
        self.assertEqual(service.gallery_list(), [])


class TestPreference(unittest.TestCase):
    """背景记录（哪个材质铺哪一张）：跨浏览器共用的那份状态，读写与清洗都要稳。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.patch = mock.patch.object(service, 'PREFERENCE_FILE', self.dir / 'preference.json')
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_missing_file_reads_empty(self):
        """没有记录时返回空字典：老用户升级后前端沿用自身默认档，行为不变。"""
        self.assertEqual(service.load_preferences(), {})

    def test_round_trip_keeps_gallery_entry(self):
        stored = {'source': 'upload', 'kind': 'image', 'urls': [], 'active': 0, 'name': '壁纸', 'entry': 'abc.jpg'}
        service.save_preference('glass', stored)
        self.assertEqual(service.load_preferences()['glass'], stored)

    def test_save_keeps_other_material(self):
        service.save_preference('glass', {'source': 'off'})
        service.save_preference('plain', {'source': 'url', 'urls': ['https://a.test/1.jpg'], 'active': 0})
        preferences = service.load_preferences()
        self.assertEqual(preferences['glass']['source'], 'off')
        self.assertEqual(preferences['plain']['urls'], ['https://a.test/1.jpg'])

    def test_sanitize_drops_bad_values(self):
        cleaned = service.sanitize_preference({
            'source': 'hack', 'kind': 'gif',
            'urls': ['https://ok.test/a.jpg', 'file:///etc/passwd', 'javascript:alert(1)', 42, 'https://ok.test/a.jpg', '  '],
            'active': 99, 'name': 'x' * 200, 'entry': 5,
        })
        self.assertEqual(cleaned['source'], 'off')
        self.assertEqual(cleaned['kind'], 'image')
        self.assertEqual(cleaned['urls'], ['https://ok.test/a.jpg'])
        self.assertEqual(cleaned['active'], 0)
        self.assertEqual(len(cleaned['name']), 120)
        self.assertNotIn('entry', cleaned)

    def test_active_clamped_into_range(self):
        cleaned = service.sanitize_preference({'source': 'url', 'urls': ['https://a.test/1.jpg', 'https://b.test/2.jpg'], 'active': 1})
        self.assertEqual(cleaned['active'], 1)
        self.assertEqual(service.sanitize_preference({'source': 'url', 'active': 5})['active'], 0)

    def test_rejects_unknown_material(self):
        with self.assertRaises(service.BackgroundError):
            service.save_preference('metal', {'source': 'off'})

    def test_corrupt_file_reads_empty(self):
        (self.dir / 'preference.json').write_text('{不是 JSON', encoding='utf-8')
        self.assertEqual(service.load_preferences(), {})


class TestUploadLimit(unittest.TestCase):
    """本地上传与远程代抓的上限不同：界面承诺 200 MB，迁移旧浏览器图片时不能被 20 MB 卡住。"""

    def test_upload_limit_is_larger_than_fetch_limit(self):
        self.assertGreater(service.MAX_UPLOAD_BYTES, service.MAX_BYTES)

    def test_upload_accepts_file_over_fetch_limit(self):
        with tempfile.TemporaryDirectory() as folder:
            with mock.patch.object(service, 'LIBRARY_DIR', Path(folder)), \
                 mock.patch.object(service, 'INDEX_FILE', Path(folder) / 'index.json'), \
                 mock.patch.object(service, 'MAX_UPLOAD_BYTES', 4):
                with self.assertRaises(service.BackgroundError):
                    service.gallery_add_bytes(b'12345', 'big.jpg')
                self.assertEqual(service.gallery_add_bytes(b'123', 'small.jpg')['size'], 3)

    def test_params_accept_frontend_payload(self):
        """前端发来的就是这个形状；严格模型下也必须过。"""
        from module.api import protocol
        params = protocol.BackgroundPreferenceParams.model_validate(
            {'material': 'plain', 'preference': {'source': 'url', 'kind': 'image', 'urls': ['https://a.test/1.jpg'], 'active': 0, 'name': ''}}
        )
        self.assertEqual(params.material, 'plain')
        self.assertEqual(params.preference['urls'], ['https://a.test/1.jpg'])
        self.assertEqual(protocol.BackgroundPreferenceParams.model_validate({'material': 'glass'}).preference, {})


if __name__ == '__main__':
    unittest.main()
