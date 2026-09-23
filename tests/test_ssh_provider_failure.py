"""仅用假 SSH 进程验证失败回包的资源回收和外层重试。"""
import io
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.runtime import remote_access
from module.runtime.setting import State


class SshProviderFailureTests(unittest.TestCase):
    def process(self, response):
        process = Mock()
        process.stdout = io.BytesIO(response)
        process.stderr = io.BytesIO()
        process.poll.return_value = None
        process.wait.side_effect = lambda **kwargs: setattr(process.poll, 'return_value', -9)
        return process

    def test_failure_reaps_process_before_returning(self):
        for response in ('{"status":"fail","message":"稍后重试"}'.encode(), b'{}'):
            with self.subTest(response=response):
                provider = remote_access.SSHRemoteAccessProvider()
                process = self.process(response)
                provider.process = process
                provider.info.address = '旧地址'
                with patch.object(provider, '_start_ssh_process', return_value=process), \
                        patch.object(remote_access.threading, 'Thread'), \
                        patch.object(remote_access.time, 'sleep', side_effect=AssertionError('失败后不应进入存活监控')):
                    provider._run()
                process.kill.assert_called_once_with()
                process.wait.assert_called_once_with(timeout=3)
                self.assertIsNone(provider.info.address)
                self.assertEqual(provider.info.connection_state, 'stopped')
                self.assertTrue(provider.info.error)

    def test_failure_keeps_username_change_and_allows_outer_retry(self):
        provider = remote_access.SSHRemoteAccessProvider()
        first = self.process(b'{"status":"fail","change_username":"replacement"}')
        second = self.process(b'{"status":"success","address":"ready"}')
        attempts = []
        targets = []

        def start(**kwargs):
            process = (first, second)[len(attempts)]
            attempts.append(process)
            targets.append(kwargs)
            provider.process = process
            if process is second:
                provider.stop_event.set()
            return process

        settings = SimpleNamespace(SSHUser='original', SSHServer='primary.example:2022', WebuiPort=22267)
        with patch.object(provider, '_start_ssh_process', side_effect=start), \
                patch.object(provider.stop_event, 'wait', return_value=False) as retry_wait, \
                patch.object(remote_access.threading, 'Thread') as thread, \
                patch.object(remote_access, '_local_host', return_value='127.0.0.1'), \
                patch.object(State, '_deploy_config_', settings, create=True):
            provider.start()
            invocation = thread.call_args.kwargs
            invocation['target'](**invocation['kwargs'])
        self.assertEqual(settings.SSHUser, 'replacement')
        self.assertEqual(len(attempts), 2)
        self.assertEqual(targets, [
            dict(local_host='127.0.0.1', local_port=22267, server='original@primary.example',
                 server_port=2022, remote_port='/'),
            dict(local_host='127.0.0.1', local_port=22267, server='replacement@primary.example',
                 server_port=2022, remote_port='/'),
        ])
        first.kill.assert_called_once_with()
        first.wait.assert_called_once_with(timeout=3)
        retry_wait.assert_called_once_with(remote_access.SSH_RECONNECT_DELAY)
        self.assertEqual(provider.info.error, '')

    def test_explicit_server_survives_retry_without_a_valid_username_change(self):
        for change in (b'', b',"change_username":""', b',"change_username":123'):
            with self.subTest(change=change):
                provider = remote_access.SSHRemoteAccessProvider()
                first = self.process(b'{"status":"fail"' + change + b'}')
                second = self.process(b'{"status":"success","address":"ready"}')
                targets = []

                def start(**kwargs):
                    process = (first, second)[len(targets)]
                    targets.append(kwargs['server'])
                    provider.process = process
                    if process is second:
                        provider.stop_event.set()
                    return process

                settings = SimpleNamespace(SSHUser='unrelated-config-user')
                with patch.object(provider, '_start_ssh_process', side_effect=start), \
                        patch.object(provider.stop_event, 'wait', return_value=False), \
                        patch.object(remote_access.threading, 'Thread'), \
                        patch.object(State, '_deploy_config_', settings, create=True):
                    provider._thread_main(server='explicit@custom.example', server_port=2200)
                self.assertEqual(targets, ['explicit@custom.example', 'explicit@custom.example'])
                self.assertEqual(settings.SSHUser, 'unrelated-config-user')
