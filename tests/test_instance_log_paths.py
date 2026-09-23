"""使用临时目录验证完整实例名的日志写入与 MCP 读取归属。"""
import datetime
from contextlib import contextmanager
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import module.logger as logging_module
from module.mcp.tools import Tools


class InstanceLogPathTests(unittest.TestCase):
    def test_log_writers_keep_full_instance_names(self):
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            os.chdir(directory)
            try:
                for writer in (logging_module.set_file_logger, logging_module._set_file_logger):
                    for name in ('account_a', 'account_b', '账号 一.二'):
                        with self.subTest(writer=writer.__name__, name=name), \
                                patch.object(logging_module.logger, 'handlers', []), \
                                patch.object(logging_module.logger, 'log_file', None):
                            try:
                                writer(name)
                                logging_module.logger.info('实例标识: %s', name)
                                path = logging_module.get_log_file_path(name)
                                self.assertEqual(Path(logging_module.logger.log_file).resolve(), path.resolve())
                                self.assertIn(name, path.read_text(encoding='utf-8'))
                            finally:
                                for handler in logging_module.logger.handlers:
                                    if isinstance(handler, logging_module.RichTimedRotatingHandler):
                                        handler.richd.console.file.close()
                                    handler.close()
                self.assertFalse(logging_module.get_log_file_path('account').exists())
            finally:
                os.chdir(original)

    def test_missing_instance_log_never_uses_another_instance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            default = logging_module.get_log_file_path('alas', root)
            default.parent.mkdir()
            default.write_text('默认实例私有日志', encoding='utf-8')
            configs = SimpleNamespace(root=root, path=lambda name: root / 'config' / f'{name}.json')
            tools = Tools(configs=configs)
            missing = tools.log_path('account_b')
            self.assertFalse(missing.exists())
            self.assertEqual(missing.name, f'{datetime.date.today()}_account_b.txt')
            self.assertEqual(tools.log_path('alas'), default)
            missing.write_text('B 的日志', encoding='utf-8')
            self.assertEqual(tools.log_path('account_b').read_text(encoding='utf-8'), 'B 的日志')


    @contextmanager
    def windows_logging(self, process_name='MainProcess'):
        """只替换待测模块的 os 引用，保留 pathlib 使用的宿主平台。"""
        original = Path.cwd()
        fake_os = SimpleNamespace(**{**vars(os), 'name': 'nt'})
        with tempfile.TemporaryDirectory() as directory:
            os.chdir(directory)
            try:
                with patch.object(logging_module, 'os', fake_os), \
                        patch.object(logging_module, 'pyw_name', 'gui'), \
                        patch.object(logging_module.multiprocessing, 'current_process',
                                     return_value=SimpleNamespace(name=process_name)), \
                        patch.object(logging_module.logger, 'handlers', []), \
                        patch.object(logging_module.logger, 'log_file', None):
                    try:
                        yield Path(directory)
                    finally:
                        for handler in logging_module.logger.handlers:
                            if isinstance(handler, logging_module.RichTimedRotatingHandler):
                                handler.richd.console.file.close()
                            handler.close()
            finally:
                os.chdir(original)

    def test_windows_explicit_instance_names_are_not_filtered_as_process_names(self):
        with self.windows_logging():
            for name in ('account_MainProcess', 'account_Process-1', 'account_SyncManager-1', 'gui'):
                with self.subTest(name=name):
                    logging_module.set_file_logger(name)
                    logging_module.logger.info('实例标识: %s', name)
                    path = logging_module.get_log_file_path(name)
                    self.assertEqual(Path(logging_module.logger.log_file), path.resolve())
                    self.assertIn(name, path.read_text(encoding='utf-8'))
                    self.assertEqual(len(logging_module.logger.handlers), 1)

    def test_windows_automatic_gui_skips_only_background_processes(self):
        for process_name in ('MainProcess', 'Process-1', 'SyncManager-1:2'):
            with self.subTest(process=process_name), self.windows_logging(process_name):
                logging_module.set_file_logger()
                self.assertEqual(logging_module.logger.handlers, [])
                self.assertIsNone(logging_module.logger.log_file)
                logging_module.set_file_logger('account_a')
                logging_module.logger.info('实例日志')
                self.assertIn('实例日志', logging_module.get_log_file_path('account_a').read_text(encoding='utf-8'))
        with self.windows_logging('gui'):
            logging_module.set_file_logger()
            logging_module.logger.info('自动界面日志')
            self.assertIn('自动界面日志', logging_module.get_log_file_path('gui').read_text(encoding='utf-8'))

    def test_windows_can_switch_an_existing_automatic_handler_to_an_instance(self):
        with self.windows_logging('gui'):
            logging_module.set_file_logger()
            logging_module.logger.info('仅属于界面')
            old_handler = logging_module.logger.handlers[0]
            old_stream = old_handler.richd.console.file
            logging_module.set_file_logger('account_a')
            logging_module.logger.info('仅属于实例')
            self.assertTrue(old_stream.closed)
            self.assertNotIn('仅属于实例', logging_module.get_log_file_path('gui').read_text(encoding='utf-8'))
            self.assertIn('仅属于实例', logging_module.get_log_file_path('account_a').read_text(encoding='utf-8'))
            handler = logging_module.logger.handlers[0]
            logging_module.set_file_logger('account_a')
            self.assertEqual(logging_module.logger.handlers, [handler])
