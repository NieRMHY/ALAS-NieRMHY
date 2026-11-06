"""启动阶段的程序路径与 Windows 命令引号回归。"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from deploy import config as deploy_config
from deploy.utils import poor_yaml_read


class DeployStartupTests(unittest.TestCase):
    def setUp(self):
        # 不初始化真实部署配置，避免读写用户文件或触发地区查询。
        self.config = deploy_config.DeployConfig.__new__(deploy_config.DeployConfig)
        self.config.show_error = Mock()
        logger_patch = patch.object(deploy_config, 'logger')
        logger_patch.start()
        self.addCleanup(logger_patch.stop)

    def test_relative_program_paths_accept_yaml_quotes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            program = root / 'runtime tools' / 'program.exe'
            program.parent.mkdir()
            program.touch()
            file = root / 'deploy.yaml'
            self.config.__dict__['root_filepath'] = root.as_posix()
            for quote in ('', "'", '"'):
                with self.subTest(quote=quote):
                    file.write_text(
                        ''.join(f'{key}: {quote}./runtime tools/program.exe{quote}\n'
                                for key in ('GitExecutable', 'AdbExecutable', 'PythonExecutable'))
                        + 'Run: ["alas"]\nPassword: "false"\nWebuiPort: 25548\n',
                        encoding='utf-8',
                    )
                    before = file.read_bytes()
                    self.config.config = poor_yaml_read(str(file))
                    values = self.config.config.copy()
                    for key in ('GitExecutable', 'AdbExecutable', 'PythonExecutable'):
                        self.assertEqual(self.config.filepath(key), program.as_posix())
                        self.assertTrue(Path(self.config.filepath(key)).is_file())
                    self.assertEqual(self.config.config, values)
                    self.assertEqual(file.read_bytes(), before)
                    self.assertEqual(values['Run'], '["alas"]')
                    self.assertEqual(values['Password'], '"false"')
                    self.assertEqual(values['WebuiPort'], 25548)

    def test_absolute_program_path_accepts_yaml_quotes(self):
        with tempfile.TemporaryDirectory() as directory:
            self.config.__dict__['root_filepath'] = directory
            program = Path(directory) / 'runtime tools' / 'git.exe'
            self.config.config = {'GitExecutable': f'"{program.as_posix()}"'}
            self.assertEqual(self.config.filepath('GitExecutable'), program.as_posix())

    @unittest.skipUnless(os.name == 'nt', '需要 Windows 命令解释器')
    def test_quoted_program_path_preserves_quoted_arguments(self):
        with tempfile.TemporaryDirectory() as directory:
            program = Path(directory) / 'tool with spaces.cmd'
            program.write_text(
                '@echo off\n'
                'if not "%~1"=="value with spaces" exit /b 7\n'
                'if not "%~2"=="https://example.invalid/" exit /b 8\n'
                'exit /b 0\n',
                encoding='ascii',
            )
            command = f'"{program.as_posix()}" "value with spaces" "https://example.invalid/"'
            self.assertTrue(self.config.execute(command, output=False))
            self.config.show_error.assert_not_called()

    @unittest.skipUnless(os.name == 'nt' and shutil.which('git'), '需要 Windows 和 Git')
    def test_git_version_with_browser_headers_runs_without_network(self):
        command = (
            '"git" -c "http.https://example.invalid/.version=HTTP/2" '
            '-c "http.https://example.invalid/.userAgent=Mozilla/5.0 '
            '(Windows NT 10.0; Win64; x64) Test/1.0" --version'
        )
        self.assertTrue(self.config.execute(command, output=False))

    @unittest.skipUnless(os.name == 'nt' and shutil.which('git'), '需要 Windows 和 Git')
    def test_legacy_git_command_still_runs(self):
        command = f'"{Path(shutil.which("git")).as_posix()}" -c http.userAgent=git/2.52.0 --version'
        self.assertTrue(self.config.execute(command, output=False))

    @unittest.skipUnless(os.name == 'nt', '需要 Windows 命令解释器')
    def test_allowed_command_failure_still_returns_false(self):
        command = f'"{Path(sys.executable).as_posix()}" -c "raise SystemExit(7)"'
        self.assertFalse(self.config.execute(command, allow_failure=True, output=False))
        self.config.show_error.assert_not_called()

    @unittest.skipUnless(os.name == 'nt', '需要 Windows 命令解释器')
    def test_command_failure_preserves_exit_code_and_original_command(self):
        command = f'"{Path(sys.executable).as_posix()}" -c "raise SystemExit(7)"'
        # Modify by MHY, 本地部署保留原有异常接口，不引入发行启动器错误码。
        with self.assertRaises(deploy_config.ExecutionError):
            self.config.execute(command)
        self.config.show_error.assert_called_once_with(command)

    def test_unquoted_command_keeps_output_redirection(self):
        system = Mock(return_value=0)
        with patch.object(deploy_config, 'os', SimpleNamespace(name='nt', system=system)):
            self.assertTrue(self.config.execute('echo ok', output=False))
        system.assert_called_once_with('echo ok >nul 2>nul')

    def test_non_windows_command_is_unchanged(self):
        system = Mock(return_value=0)
        command = '"git" -c "http.userAgent=value with spaces" --version'
        with patch.object(deploy_config, 'os', SimpleNamespace(name='posix', system=system)):
            self.assertTrue(self.config.execute(command))
        system.assert_called_once_with(command)


if __name__ == '__main__':
    unittest.main()
