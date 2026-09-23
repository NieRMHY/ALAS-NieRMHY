"""OCR RPC 故障回归：假客户端、假时钟与假本地模型，不连接网络。"""

import importlib.util
from pathlib import Path
import sys
import threading
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch


def stub_module(name, **attrs):
    module = ModuleType(name)
    module.__dict__.update(attrs)
    return module


class TestOcrRpcRecovery(unittest.TestCase):
    def setUp(self):
        self.local = Mock()
        self.local.ocr.return_value = '本地'
        self.local_models = SimpleNamespace(**{lang: self.local for lang in (
            'azur_lane', 'ppocr_v6', 'cnocr', 'jp', 'tw', 'azur_lane_jp')})
        self.client = Mock(return_value='远程')
        self.constructor = Mock(return_value=self.client)
        self.enterContext(patch.dict(sys.modules, {
            'module.logger': stub_module('module.logger', logger=Mock()),
            'module.runtime.setting': stub_module('module.runtime.setting', State=SimpleNamespace(
                deploy_config=SimpleNamespace(OcrClientAddress='fake:1234'))),
            'module.ocr.models': stub_module('module.ocr.models', OCR_MODEL=self.local_models),
            'zerorpc': stub_module('zerorpc', Client=self.constructor),
        }))
        path = Path(__file__).resolve().parents[1] / 'module/ocr/rpc.py'
        spec = importlib.util.spec_from_file_location('_ocr_rpc_recovery_test', path)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.proxy = self.module.ModelProxy
        self.factory = self.module.ModelProxyFactory()
        self.clock = self.enterContext(patch.object(self.module.time, 'monotonic', return_value=100.0))
        self.image = Mock()
        self.image.dumps.return_value = b'image'

    def test_runtime_failure_is_shared_and_reconnect_is_cooled_down(self):
        first = self.factory.azur_lane
        self.client.side_effect = TimeoutError('断线')
        self.assertEqual(first.ocr(self.image), '本地')
        self.assertFalse(self.proxy.online)
        self.assertIsNone(self.proxy.client)
        self.client.close.assert_called_once()
        for lang in ('azur_lane', 'cnocr', 'jp', 'tw'):
            self.assertEqual(getattr(self.factory, lang).ocr(self.image), '本地')
        self.client.assert_called_once()
        self.constructor.assert_called_once_with(timeout=5)
        self.clock.return_value = 129.9
        self.assertEqual(first.ocr(self.image), '本地')
        self.constructor.assert_called_once()
        replacement = Mock(return_value='恢复')
        self.constructor.return_value = replacement
        self.clock.return_value = 130.0
        self.assertEqual(first.ocr(self.image), '恢复')
        self.assertTrue(self.proxy.online)
        self.assertTrue(first.online)
        self.assertEqual(self.constructor.call_count, 2)
        replacement.connect.assert_called_once_with('tcp://fake:1234')

    def test_failed_handshake_retries_once_per_cooldown_and_recovers_explicitly(self):
        self.client.hello.side_effect = TimeoutError('握手失败')
        retained = self.factory.azur_lane
        for _ in range(3):
            self.assertEqual(self.factory.cnocr.ocr(self.image), '本地')
        self.assertEqual(self.constructor.call_count, 1)
        replacement = Mock()
        replacement.hello.side_effect = TimeoutError('仍不可用')
        self.constructor.return_value = replacement
        self.clock.return_value = 130.0
        self.assertEqual(retained.ocr(self.image), '本地')
        self.assertEqual(self.constructor.call_count, 2)
        replacement.close.assert_called_once()
        replacement.hello.side_effect = None
        replacement.return_value = '恢复'
        self.assertTrue(self.proxy.init('explicit:5678'))
        self.assertTrue(self.proxy.online)
        self.assertEqual(retained.ocr(self.image), '恢复')
        replacement.connect.assert_called_with('tcp://explicit:5678')

    def test_constructor_and_connect_failures_also_fall_back(self):
        self.constructor.side_effect = RuntimeError('创建失败')
        self.assertEqual(self.factory.azur_lane.ocr(self.image), '本地')
        self.assertIsNone(self.proxy.client)
        self.constructor.side_effect = None
        self.client.connect.side_effect = OSError('连接失败')
        self.clock.return_value = 130.0
        self.assertEqual(self.factory.azur_lane.ocr(self.image), '本地')
        self.client.close.assert_called_once()
        self.assertFalse(self.proxy.online)

    def test_all_public_methods_keep_wire_and_local_arguments(self):
        cases = [('ocr', (self.image,), (b'image',)),
                 ('ocr_for_single_line', (self.image,), (b'image',)),
                 ('ocr_for_single_lines', ([self.image],), ([b'image'],)),
                 ('set_cand_alphabet', ('123',), ('123',)),
                 ('atomic_ocr', (self.image, '123'), (b'image', '123')),
                 ('atomic_ocr_for_single_line', (self.image, None), (b'image', None)),
                 ('atomic_ocr_for_single_lines', ([self.image], '123'), ([b'image'], '123')),
                 ('debug', ([self.image],), ([b'image'],))]
        for method, args, wire in cases:
            with self.subTest(method=method):
                self.proxy.init('fake:1234')
                retained = self.factory.cnocr
                self.client.side_effect = None
                self.assertEqual(getattr(retained, method)(*args), '远程')
                self.client.assert_called_with(method, 'cnocr', *wire)
                self.client.side_effect = TimeoutError('断线')
                local_method = getattr(self.local, method)
                local_method.return_value = '本地结果'
                self.assertEqual(getattr(retained, method)(*args), '本地结果')
                local_method.assert_called_with(*args)
                self.assertNotIn('online', vars(retained))

    def test_close_clears_state_even_if_client_close_fails(self):
        self.factory.azur_lane
        self.client.close.side_effect = RuntimeError('关闭失败')
        self.assertTrue(self.proxy.close())
        self.assertFalse(self.proxy.online)
        self.assertIsNone(self.proxy.client)
        self.assertIsNone(self.proxy._owner_thread)
        replacement = Mock(return_value='新连接')
        self.constructor.return_value = replacement
        self.assertEqual(self.factory.jp.ocr(self.image), '新连接')

    def test_foreign_thread_uses_local_without_touching_gevent_client(self):
        retained = self.factory.azur_lane
        results = []

        def foreign_call():
            results.append(retained.ocr(self.image))
            results.append(self.proxy.init('other:1'))
            results.append(self.proxy.close())

        thread = threading.Thread(target=foreign_call)
        thread.start()
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(results, ['本地', False, False])
        self.client.assert_not_called()
        self.client.close.assert_not_called()
        self.constructor.assert_called_once()
        self.assertTrue(self.proxy.online)
        self.assertEqual(retained.ocr(self.image), '远程')

    def test_reentrant_call_does_not_block_or_invalidate_shared_client(self):
        retained = self.factory.azur_lane
        nested = []

        def remote_call(*args):
            nested.append(self.factory.cnocr.ocr(self.image))
            return '远程'

        self.client.side_effect = remote_call
        self.assertEqual(retained.ocr(self.image), '远程')
        self.assertEqual(nested, ['本地'])
        self.assertTrue(self.proxy.online)
        self.client.assert_called_once()


if __name__ == '__main__':
    unittest.main()
