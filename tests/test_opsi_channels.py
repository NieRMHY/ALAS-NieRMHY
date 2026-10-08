"""日志不输出堆栈局部变量。

Modify by MHY, 上游原文件还测了遥测接口（module.base.api_client +
module.statistics.cl1_data_submitter），这两个模块本地已剔除，相关用例一并移除。
"""
import unittest

from module.logger import console_hdlr


class ChannelTests(unittest.TestCase):
    def test_exception_locals_are_not_logged(self):
        self.assertFalse(console_hdlr.tracebacks_show_locals)
