"""前端构建启动链路的回归测试。"""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

from deploy.frontend import ensure_frontend, npm_command, source_fingerprint


class FrontendLockfileTests(unittest.TestCase):
    """安装依赖前检查锁文件，避免开发者的镜像配置被固化进仓库。"""

    def test_resolved_urls_use_official_registry(self):
        path = Path(__file__).resolve().parents[1] / 'frontend/package-lock.json'
        packages = json.loads(path.read_text(encoding='utf-8'))['packages']
        for name, package in packages.items():
            if 'resolved' not in package:
                continue
            resolved = package['resolved']
            with self.subTest(package=name, resolved=resolved):
                url = urlsplit(resolved)
                self.assertEqual((url.scheme, url.netloc), ('https', 'registry.npmjs.org'))


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


class FrontendInstallFallbackTests(unittest.TestCase):
    """验证换源次数、失败传播和编译完成后的摘要写入。"""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.frontend = self.root / 'frontend'
        (self.frontend / 'dist').mkdir(parents=True)
        (self.frontend / 'package.json').write_text('{}', encoding='utf-8')
        (self.frontend / 'dist/index.html').write_text('旧页面', encoding='utf-8')
        self.marker = self.frontend / 'dist/.source-fingerprint'
        self.marker.write_text('old\n', encoding='utf-8')
        for target, value in (
            ('deploy.frontend.npm_command', ['node', 'npm-cli.js']),
            ('deploy.frontend.subprocess.run', None),
        ):
            patcher = patch(target, return_value=value)
            mocked = patcher.start()
            self.addCleanup(patcher.stop)
            if target.endswith('subprocess.run'):
                self.subprocess_run = mocked
        environment = patch.dict(os.environ, {'AZURPILOT_ANDROID': '0'})
        environment.start()
        self.addCleanup(environment.stop)
        self.mirror = ['node', 'npm-cli.js', 'ci', '--no-audit', '--no-fund',
                       '--registry=https://registry.npmmirror.com']
        self.official = [*self.mirror[:-1], '--registry=https://registry.npmjs.org']
        self.build = ['node', 'npm-cli.js', 'run', 'build']

    def assert_commands(self, *commands):
        calls = self.subprocess_run.call_args_list
        self.assertEqual([call.args[0] for call in calls], list(commands))
        for call in calls:
            self.assertEqual(call.kwargs['cwd'], self.frontend)
            self.assertTrue(call.kwargs['check'])
            self.assertEqual(call.kwargs['timeout'], 600 if call.args[0][2] == 'ci' else 180)
            if hasattr(subprocess, 'CREATE_NO_WINDOW'):
                self.assertEqual(call.kwargs['creationflags'], subprocess.CREATE_NO_WINDOW)

    def assert_current_marker(self):
        self.assertEqual(self.marker.read_text(encoding='utf-8'), source_fingerprint(self.frontend) + '\n')

    def test_mirror_success_builds_once(self):
        ensure_frontend(self.root)
        self.assert_commands(self.mirror, self.build)
        self.assert_current_marker()

    def test_install_failure_retries_official_source(self):
        error = subprocess.CalledProcessError(1, self.mirror)
        self.subprocess_run.side_effect = [error, None, None]
        ensure_frontend(self.root)
        self.assert_commands(self.mirror, self.official, self.build)
        self.assert_current_marker()

    def test_install_failure_logs_stderr_and_eperm_hint(self):
        error = subprocess.CalledProcessError(
            4294963248, self.mirror,
            output='', stderr="npm error code EPERM\nnpm error syscall unlink\nfile in use"
        )
        self.subprocess_run.side_effect = [error, None, None]
        with patch('module.logger.logger.warning') as warning, patch('module.logger.logger.error') as error_log:
            ensure_frontend(self.root)
            warning.assert_any_call('npm ci 错误输出:\nnpm error code EPERM\nnpm error syscall unlink\nfile in use')
            error_log.assert_called_with('node_modules 中的文件被其他进程占用（如正在运行的 WebUI、Vite 或编辑器）。请先关闭占用进程后重新启动。')
        self.assert_commands(self.mirror, self.official, self.build)

    def test_install_timeout_retries_official_source(self):
        self.subprocess_run.side_effect = [subprocess.TimeoutExpired(self.mirror, 600), None, None]
        ensure_frontend(self.root)
        self.assert_commands(self.mirror, self.official, self.build)
        self.assert_current_marker()

    def test_both_installs_fail_without_building(self):
        last_error = subprocess.CalledProcessError(2, self.official)
        self.subprocess_run.side_effect = [subprocess.CalledProcessError(1, self.mirror), last_error]
        with self.assertRaises(subprocess.CalledProcessError) as raised:
            ensure_frontend(self.root)
        self.assertIs(raised.exception, last_error)
        self.assert_commands(self.mirror, self.official)
        self.assertEqual(self.marker.read_text(encoding='utf-8'), 'old\n')

    def test_official_timeout_is_propagated_without_building(self):
        last_error = subprocess.TimeoutExpired(self.official, 600)
        self.subprocess_run.side_effect = [subprocess.TimeoutExpired(self.mirror, 600), last_error]
        with self.assertRaises(subprocess.TimeoutExpired) as raised:
            ensure_frontend(self.root)
        self.assertIs(raised.exception, last_error)
        self.assert_commands(self.mirror, self.official)
        self.assertEqual(self.marker.read_text(encoding='utf-8'), 'old\n')

    def test_build_failure_does_not_retry_install_or_update_marker(self):
        error = subprocess.CalledProcessError(1, self.build)
        self.subprocess_run.side_effect = [None, error]
        with self.assertRaises(subprocess.CalledProcessError) as raised:
            ensure_frontend(self.root)
        self.assertIs(raised.exception, error)
        self.assert_commands(self.mirror, self.build)
        self.assertEqual(self.marker.read_text(encoding='utf-8'), 'old\n')

    def test_missing_npm_does_not_retry_or_update_marker(self):
        with patch('deploy.frontend.npm_command', side_effect=RuntimeError('缺少 npm')):
            with self.assertRaises(RuntimeError):
                ensure_frontend(self.root)
        self.subprocess_run.assert_not_called()
        self.assertEqual(self.marker.read_text(encoding='utf-8'), 'old\n')


if __name__ == '__main__':
    unittest.main()
