"""前端构建启动链路的回归测试。"""
import subprocess
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from deploy.frontend import ensure_frontend, npm_command, source_fingerprint


class FrontendBuildTests(unittest.TestCase):
    def test_matching_artifact_does_not_require_node(self):
        with tempfile.TemporaryDirectory() as directory:
            frontend = Path(directory) / 'frontend'
            (frontend / 'dist').mkdir(parents=True)
            (frontend / 'dist/index.html').write_text('页面')
            (frontend / 'package.json').write_text('{}')
            (frontend / 'dist/.source-fingerprint').write_text(source_fingerprint(frontend))
            with patch('deploy.frontend.npm_command') as command:
                ensure_frontend(directory)
                command.assert_not_called()

    def test_failed_build_does_not_mark_artifact_current(self):
        with tempfile.TemporaryDirectory() as directory:
            frontend = Path(directory) / 'frontend'
            frontend.mkdir()
            with patch('deploy.frontend.npm_command', return_value=['npm']), patch(
                'deploy.frontend.subprocess.run', side_effect=subprocess.CalledProcessError(1, 'npm')
            ), self.assertRaises(subprocess.CalledProcessError):
                ensure_frontend(directory)
            self.assertFalse((frontend / 'dist/.source-fingerprint').exists())

    @unittest.skipUnless(os.name == 'nt', '仅验证 Windows 的 npm 启动方式')
    def test_windows_launches_npm_javascript_with_node(self):
        with patch('deploy.frontend.os.name', 'nt'), patch(
            'deploy.frontend.shutil.which', side_effect=lambda name: f'C:/node/{name}.exe'
        ), patch('deploy.frontend.Path.is_file', return_value=True):
            command = npm_command()
            self.assertTrue(command[0].endswith('node.exe'))
            self.assertTrue(command[1].endswith('npm-cli.js'))


if __name__ == '__main__':
    unittest.main()
