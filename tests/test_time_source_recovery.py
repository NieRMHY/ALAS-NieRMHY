"""后台校时在线程资源不足及 fork 后仍能读取时间，不访问真实网络。"""

import os
import subprocess
import sys
import textwrap
import time
import unittest
from unittest.mock import Mock, patch

from module.config.time_source import NetworkTimeSource


class TestNtpRecovery(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ, {
            'AZURPILOT_NTP_DISABLE': '0',
            'AZURPILOT_NTP_SERVERS': 'test.invalid',
        }))
        self.source = NetworkTimeSource()
        self.source._log_info = Mock()
        self.source._log_warning = Mock()
        self.source._query_server = Mock(return_value=2.5)
        self.addCleanup(self.finish)

    def finish(self):
        worker = self.source._refresh_thread
        if worker is not None and worker.ident is not None:
            worker.join(2)
            self.assertFalse(worker.is_alive(), '校时线程未结束')

    def assert_readers_available(self):
        self.assertAlmostEqual(self.source.timestamp(), time.time(), delta=1)
        self.assertAlmostEqual(self.source.now().timestamp(), time.time(), delta=1)
        self.assertFalse(self.source.status()['synced'])
        self.assertFalse(self.source.refresh(force=True))
        self.assertFalse(self.source._refreshing)
        self.assertIsNone(self.source._refresh_thread)

    def test_thread_constructor_failure_uses_local_time_and_backoff(self):
        with patch('module.config.time_source.threading.Thread',
                   side_effect=RuntimeError('无法创建线程')) as factory:
            self.assert_readers_available()
            self.assertEqual(factory.call_count, 2)  # 首次读取与显式强制刷新。
        self.source._query_server.assert_not_called()
        self.source._log_warning.assert_called_once()
        self.assertGreater(self.source.retry_after_monotonic, time.monotonic())

    def test_thread_start_failure_uses_local_time_and_backoff(self):
        with patch('module.config.time_source.threading.Thread.start',
                   side_effect=OSError('线程资源不足')) as start:
            self.assert_readers_available()
            self.assertEqual(start.call_count, 2)
        self.source._query_server.assert_not_called()
        self.source._log_warning.assert_called_once()

    def test_thread_start_failure_keeps_successful_cache(self):
        self.source.refresh()
        self.finish()
        baseline = (self.source.base_timestamp, self.source.base_monotonic)
        with patch('module.config.time_source.threading.Thread.start',
                   side_effect=RuntimeError('无法启动线程')):
            self.assertTrue(self.source.refresh(force=True))
            self.assertAlmostEqual(self.source.timestamp() - time.time(), 2.5, delta=1)
            self.assertEqual(self.source.status()['server'], 'test.invalid')
        self.assertEqual(baseline, (self.source.base_timestamp, self.source.base_monotonic))
        self.assertTrue(self.source.synced)
        self.assertFalse(self.source._refreshing)

    def test_thread_creation_retries_after_backoff(self):
        with patch('module.config.time_source.threading.Thread',
                   side_effect=RuntimeError('无法创建线程')):
            self.source.refresh()
        retry_at = self.source.retry_after_monotonic
        with patch('module.config.time_source.time_.monotonic', return_value=retry_at - 1):
            self.assertFalse(self.source.refresh())
        self.source._query_server.assert_not_called()
        with patch('module.config.time_source.time_.monotonic', return_value=retry_at + 1):
            self.source.refresh()
            self.finish()
        self.assertTrue(self.source.synced)
        self.assertEqual(self.source.retry_after_monotonic, 0)
        self.source._query_server.assert_called_once()

    def test_process_change_resets_inherited_state_even_when_disabled(self):
        inherited_lock = self.source._lock
        self.source._pid = -1
        self.source._refreshing = True
        self.source._refresh_thread = Mock()
        # fork 可以发生在父进程的缓存字段只更新了一部分时。
        self.source.synced = True
        self.source.offset = 900
        self.source.base_timestamp = time.time() + 900
        self.source.base_monotonic = time.monotonic()
        self.source.server = 'parent.invalid'
        self.source.retry_after_monotonic = float('inf')
        self.source._warned = True
        self.source.timeout = 0.25
        with patch.dict(os.environ, {'AZURPILOT_NTP_DISABLE': '1'}):
            self.assertAlmostEqual(self.source.timestamp(), time.time(), delta=1)
        self.assertIsNot(self.source._lock, inherited_lock)
        self.assertEqual(self.source._pid, os.getpid())
        self.assertFalse(self.source._refreshing)
        self.assertIsNone(self.source._refresh_thread)
        self.assertFalse(self.source.synced)
        self.assertIsNone(self.source.server)
        self.assertFalse(self.source._warned)
        self.assertEqual(self.source.retry_after_monotonic, 0)
        self.assertEqual(self.source.timeout, 0.25)
        self.source.refresh()
        self.finish()
        self.assertTrue(self.source.synced)
        self.source._query_server.assert_called_once()

    @unittest.skipUnless(hasattr(os, 'fork'), '仅在 POSIX 验证真实 fork')
    def test_fork_child_recovers_with_parent_refresh_lock_held(self):
        # 隔离 fork 子进程和超时信号，避免影响 unittest 宿主。
        script = textwrap.dedent('''
            import os
            import signal
            import threading
            import time
            import warnings
            from module.config.time_source import NetworkTimeSource

            source = NetworkTimeSource()
            source._log_info = lambda message: None
            source._log_warning = lambda message: None
            entered = threading.Event()
            release = threading.Event()

            def query(host):
                with source._lock:
                    entered.set()
                    if not release.wait(10):
                        raise OSError('parent query timed out')
                return 1

            source._query_server = query
            source.refresh()
            assert entered.wait(2), 'parent query did not start'
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore', DeprecationWarning)
                    child = os.fork()
                if child == 0:
                    # 原实现会卡在继承的锁上，SIGALRM 保证子进程能被回收。
                    signal.alarm(3)
                    try:
                        source._query_server = lambda host: 2.5
                        source.timestamp()
                        source._refresh_thread.join(2)
                        assert not source._refresh_thread.is_alive()
                        assert source.synced
                        assert abs(source.timestamp() - time.time() - 2.5) < 1
                    except BaseException:
                        os._exit(1)
                    os._exit(0)
                _, status = os.waitpid(child, 0)
                assert os.waitstatus_to_exitcode(status) == 0, status
            finally:
                release.set()
                source._refresh_thread.join(2)
                assert not source._refresh_thread.is_alive()
        ''')
        result = subprocess.run(
            [sys.executable, '-c', script],
            env=os.environ.copy(), capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
