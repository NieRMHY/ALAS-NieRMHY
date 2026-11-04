"""ATX 下载回归测试：隔离网络、缓存目录和设备，不操作真实模拟器。"""

import io
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

# 先加载项目设备兼容层，不构造设备或读取用户配置。
from module.device.device import Device  # noqa: F401
from module.device.method import utils
# Modify by MHY, 本地设备资源下载沿用 requests。
import requests
import uiautomator2 as u2


def agent_archive(payload=b'\x7fELFtest-agent'):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w:gz') as archive:
        member = tarfile.TarInfo('atx-agent')
        member.size = len(payload)
        archive.addfile(member, io.BytesIO(payload))
    return buffer.getvalue()


def response(content, status=200, content_length=True):
    result = Mock()
    result.__enter__ = Mock(return_value=result)
    result.__exit__ = Mock(return_value=False)
    result.headers = {'Content-Length': str(len(content))} if content_length else {}
    result.iter_content.return_value = iter([content])
    if status >= 400:
        result.raise_for_status.side_effect = requests.HTTPError(f'{status} Forbidden')
    return result


class TestAtxAgentDownload(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(u2.init, 'appdir', str(self.directory)))
        self.init = u2.init.Initer.__new__(u2.init.Initer)
        self.init.abis = ['x86_64', 'arm64-v8a']
        self.init.logger = Mock()
        self.init._device = Mock()
        self.payload = b'\x7fELFtest-agent'
        self.content = agent_archive(self.payload)
        self.url = self.init.atx_agent_url
        self.cache = Path(u2.init.gen_cachepath(self.url))

    def install_agent(self):
        return self.init.push_url(self.url, tgz=True, extract_name='atx-agent')

    def assert_agent_pushed(self):
        args, kwargs = self.init._device.sync.push.call_args
        self.assertEqual(Path(args[0]).read_bytes(), self.payload)
        self.assertEqual(args[1], '/data/local/tmp/atx-agent')
        self.assertEqual(kwargs, {'mode': 0o755})

    def test_mirror_download_omits_cross_origin_header_and_has_timeout(self):
        def download(url, **kwargs):
            headers = {key.lower(): value for key, value in kwargs.get('headers', {}).items()}
            # 复现 CNB 对下载器旧请求头的拒绝。
            return response(self.content, status=403 if 'origin' in headers else 200)

        with patch('module.device.method.utils.requests.get', side_effect=download) as get:
            self.install_agent()

        get.assert_called_once()
        self.assertEqual(get.call_args.args[0], self.url)
        self.assertEqual(get.call_args.kwargs['timeout'], (5, 30))
        self.assertTrue(get.call_args.kwargs['stream'])
        self.assertEqual(self.cache.read_bytes(), self.content)
        self.assert_agent_pushed()

    def test_mirror_failure_falls_back_to_matching_official_release(self):
        with patch('module.device.method.utils.requests.get', side_effect=[response(b'Forbidden', 403), response(self.content)]) as get:
            self.install_agent()

        self.assertEqual([item.args[0] for item in get.call_args_list], [
            self.url,
            f'https://github.com/openatx/atx-agent/releases/download/{u2.version.__atx_agent_version__}/'
            f'atx-agent_{u2.version.__atx_agent_version__}_linux_386.tar.gz',
        ])
        self.assert_agent_pushed()

    def test_read_timeout_also_uses_official_fallback(self):
        with patch('module.device.method.utils.requests.get', side_effect=[requests.ReadTimeout('下载超时'), response(self.content)]) as get:
            self.install_agent()

        self.assertEqual(get.call_count, 2)
        self.assert_agent_pushed()

    def test_valid_cache_is_reused_without_network(self):
        self.cache.parent.mkdir(parents=True)
        self.cache.write_bytes(self.content)
        with patch('module.device.method.utils.requests.get', side_effect=AssertionError('不应访问网络')) as get:
            self.install_agent()

        get.assert_not_called()
        self.assert_agent_pushed()

    def test_invalid_cache_is_replaced_only_after_valid_download(self):
        self.cache.parent.mkdir(parents=True)
        self.cache.write_bytes(b'Forbidden')
        with patch('module.device.method.utils.requests.get', return_value=response(self.content)) as get:
            self.install_agent()

        get.assert_called_once()
        self.assertEqual(self.cache.read_bytes(), self.content)
        self.assert_agent_pushed()

    def test_html_response_is_rejected_before_fallback_and_push(self):
        with patch('module.device.method.utils.requests.get', side_effect=[response(b'<html>error</html>'), response(self.content)]):
            self.install_agent()

        self.assertEqual(self.cache.read_bytes(), self.content)
        self.assert_agent_pushed()

    def test_truncated_response_is_not_cached_or_pushed(self):
        with patch('module.device.method.utils.requests.get', side_effect=[response(self.content[:20]), response(b'Forbidden', 403)]) as get:
            with self.assertRaises(requests.HTTPError):
                self.install_agent()

        self.assertEqual(get.call_count, 2)
        self.assertFalse(self.cache.exists())
        self.assertFalse(list(self.directory.rglob('*.part')))
        self.init._device.sync.push.assert_not_called()

    def test_stream_failure_closes_response_and_cleans_partial_file(self):
        failed = response(self.content)
        failed.iter_content.side_effect = requests.ConnectionError('传输中断')
        with patch('module.device.method.utils.requests.get', side_effect=[failed, response(b'Forbidden', 403)]):
            with self.assertRaises(requests.HTTPError):
                self.install_agent()

        failed.__exit__.assert_called_once()
        self.assertFalse(list(self.directory.rglob('*.part')))
        self.init._device.sync.push.assert_not_called()

    def test_download_without_content_length_is_supported(self):
        with patch('module.device.method.utils.requests.get', return_value=response(self.content, content_length=False)):
            self.install_agent()

        self.assert_agent_pushed()

    def test_other_resources_keep_upstream_push_implementation(self):
        original = utils.PatchedIniter.__mro__[1]
        with patch.object(original, 'push_url', return_value='pushed') as push:
            self.assertEqual(self.init.push_url('https://example.test/minitouch', mode=0o644), 'pushed')

        push.assert_called_once_with(
            'https://example.test/minitouch', dest=None, mode=0o644, tgz=False, extract_name=None,
        )

    def test_existing_abi_selection_and_minicap_patch_are_preserved(self):
        self.assertIsInstance(self.init, utils.PatchedIniter)
        self.init.abis = ['arm64-v8a', 'armeabi-v7a']
        self.assertTrue(self.init.atx_agent_url.endswith('_linux_arm64.tar.gz'))
        self.assertEqual(self.init.minicap_urls, [])


if __name__ == '__main__':
    unittest.main()
