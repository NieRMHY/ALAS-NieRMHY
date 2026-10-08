"""控制台日志开关：WebUI 子进程只把日志写文件，任务子进程照常继承控制台。"""
import contextlib
import io
import unittest

from module.logger import logger, set_console_logger


class ConsoleLoggerTests(unittest.TestCase):
    def tearDown(self):
        set_console_logger(True)

    def test_toggle_console_output(self):
        """关闭后不再写 stdout，重新开启后恢复。"""
        set_console_logger(False)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            logger.info('MARKOFF')
        self.assertNotIn('MARKOFF', buffer.getvalue())

        set_console_logger(True)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            logger.info('MARKON')
        self.assertIn('MARKON', buffer.getvalue())
