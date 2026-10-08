"""托盘启动器的单实例判定与日志落盘的回归测试。

pystray 只在 Windows 可导入，测试用替身注入 sys.modules 后加载模块。
"""
import importlib
import socket
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load_launcher():
    """加载 launcher_tray 模块，pystray 用替身顶替。

    Returns:
        module: 已加载的 launcher_tray 模块。
    """
    if 'pystray' not in sys.modules:
        stub = types.ModuleType('pystray')
        stub.Menu = lambda *items: items
        stub.MenuItem = lambda *args, **kwargs: args
        stub.Icon = lambda *args, **kwargs: None
        sys.modules['pystray'] = stub
    sys.path.insert(0, str(ROOT))
    try:
        return importlib.import_module('launcher_tray')
    finally:
        sys.path.remove(str(ROOT))


class WebuiAliveTests(unittest.TestCase):
    """互斥量之外还要探测端口，否则会把已死的 WebUI 误判成在运行。"""

    def setUp(self):
        self.launcher = load_launcher()

    def test_detects_listening_port(self):
        server = socket.socket()
        server.bind(('127.0.0.1', 0))
        server.listen(1)
        self.addCleanup(server.close)
        url = f'http://127.0.0.1:{server.getsockname()[1]}'
        with patch.object(self.launcher, 'WEBUI_URL', url):
            self.assertTrue(self.launcher.webui_alive())

    def test_reports_closed_port_as_dead(self):
        server = socket.socket()
        server.bind(('127.0.0.1', 0))
        port = server.getsockname()[1]
        server.close()
        with patch.object(self.launcher, 'WEBUI_URL', f'http://127.0.0.1:{port}'):
            self.assertFalse(self.launcher.webui_alive())


class LauncherLogTests(unittest.TestCase):
    """pythonw 无控制台，日志是唯一的排查线索。"""

    def setUp(self):
        self.launcher = load_launcher()

    def test_writes_timestamped_line(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(self.launcher, 'ROOT', directory):
                self.launcher.log('测试消息')
            text = (Path(directory) / 'log' / 'launcher.txt').read_text(encoding='utf-8')
        self.assertIn('测试消息', text)
        self.assertRegex(text, r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} ')

    def test_log_failure_is_swallowed(self):
        # 日志写不进去也不能影响启动
        with patch.object(self.launcher, 'ROOT', '/proc/definitely/not/writable'):
            self.launcher.log('不该抛错')


if __name__ == '__main__':
    unittest.main()
