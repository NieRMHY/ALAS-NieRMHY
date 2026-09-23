"""本机免密判定的单元测试。"""

import unittest

from module.runtime.password_utils import host_name, is_local_client


class HostNameTests(unittest.TestCase):
    def test_strips_scheme_port_and_brackets(self):
        self.assertEqual('127.0.0.1', host_name('127.0.0.1:22267'))
        self.assertEqual('127.0.0.1', host_name('http://127.0.0.1:22267'))
        self.assertEqual('::1', host_name('::1'))
        self.assertEqual('::1', host_name('[::1]:22267'))
        self.assertEqual('::1', host_name('http://[::1]:22267'))
        self.assertEqual('localhost', host_name('LOCALHOST'))

    def test_public_host(self):
        self.assertEqual('app.hk1.azurlane.cloud', host_name('https://app.hk1.azurlane.cloud/p2p/x?token=1'))

    def test_empty_value(self):
        self.assertEqual('', host_name(None))
        self.assertEqual('', host_name(''))


class LocalClientTests(unittest.TestCase):
    def test_local_browser_is_local(self):
        self.assertTrue(is_local_client('127.0.0.1', '127.0.0.1:22267', 'http://127.0.0.1:22267'))

    def test_local_browser_without_origin_is_local(self):
        # 启动器内嵌窗口与非浏览器客户端可能不带 Origin
        self.assertTrue(is_local_client('::1', '[::1]:22267'))
        self.assertTrue(is_local_client('127.0.0.1', 'localhost:22267'))

    def test_lan_client_requires_password(self):
        self.assertFalse(is_local_client('192.168.1.20', '192.168.1.5:22267', 'http://192.168.1.5:22267'))

    def test_remote_url_requires_password(self):
        self.assertFalse(is_local_client('127.0.0.1', 'app.hk1.azurlane.cloud', 'https://app.hk1.azurlane.cloud'))

    def test_external_page_cannot_borrow_localhost(self):
        # 外部网页脚本连本机地址时，Origin 仍指向外部站点
        self.assertFalse(is_local_client('127.0.0.1', '127.0.0.1:22267', 'https://evil.example'))

    def test_tunnel_forwarded_request_is_not_local(self):
        self.assertFalse(is_local_client('127.0.0.1', '127.0.0.1:22267', None, '1'))


if __name__ == '__main__':
    unittest.main()
