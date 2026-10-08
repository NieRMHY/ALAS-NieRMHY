"""茗交所跨部署密钥与旧版迁移回归；只使用临时文件和隔离身份。"""
import base64
import errno
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from module.api.protocol import ApiError
from module.api.stock_exchange_identity import binding_key, load_identity
from module.runtime.account_local import LocalProtector
from module.runtime.game_data import GameDataProtector, canonical


def make_directory_link(link, target):
    """建立目录链接：Windows 用 junction（免管理员权限），其余平台用符号链接。"""
    if os.name == 'nt':
        subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(target)], check=True, capture_output=True)
    else:
        Path(link).symlink_to(target, target_is_directory=True)


class GameDataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        # macOS 的 TMPDIR 可能经过 /var 等系统路径别名，夹具使用物理路径。
        self.root = (Path(self.temp.name) / 'project').resolve()
        (self.root / 'config').mkdir(parents=True)
        (self.root / 'config' / 'test.json').write_text(json.dumps({'Alas': {}}), encoding='utf-8')
        self.protection = GameDataProtector(self.root)
        self.keys = (Path(self.temp.name) / 'legacy-keys').resolve()
        context = patch.object(LocalProtector, 'key_directory', return_value=self.keys)
        context.start()
        self.addCleanup(context.stop)

    def make_legacy(self, native=False):
        identity, signing = load_identity(self.root, 'test')
        self.protection.write_file('bindings.json', {'fixture': '原玩家绑定'})
        self.protection.anchor('fixture/history', [3, 4, 'a' * 64], prepare=True)
        self.protection.anchor('fixture/history', [3, 4, 'a' * 64])
        protector = LocalProtector(self.root, 'stock-exchange-files-v1')
        with self.protection.transaction() as (data, key):
            original_context = self.protection.context
            for name in data['files']:
                path = self.protection.file_path(name)
                self.protection.context = original_context
                value = self.protection._decrypt(key, json.loads(path.read_bytes()), name)
                self.protection.context = protector.context
                raw = canonical(self.protection._encrypt(key, value, name))
                path.write_bytes(raw)
                data['files'][name] = {'head': hashlib.sha256(raw).hexdigest()}
            self.protection.context = protector.context
            if native:
                wrapped = protector.wrap(key.value)
            else:
                with patch.object(LocalProtector, 'host_identity', return_value='old-container'), \
                        patch.object(LocalProtector, 'prepare_directory', new=lambda _, path: path.mkdir(parents=True, exist_ok=True)), \
                        patch('module.runtime.account_local.dpapi', side_effect=lambda value, decrypt=False: bytes(value)):
                    wrapped = protector.wrap(key.value)
            envelope = self.protection._encrypt(key, data, 'registry')
            envelope['wrapped'] = base64.b64encode(wrapped).decode()
            state = self.keys / (protector.context + '.game')
            state.write_bytes(canonical(envelope))
        self.protection.state_path.unlink()
        self.protection.key_path.unlink()
        self.protection.marker.unlink()
        self.protection.legacy_marker.write_text('AzurPilot game protection v1\n', encoding='utf-8')
        return identity, binding_key(identity, signing), state

    def test_fresh_identity_without_host_user_or_os_protection(self):
        for platform in ('linux', 'darwin', 'win32'):
            with self.subTest(platform=platform), \
                    patch('module.runtime.account_local.sys.platform', platform), \
                    patch.object(LocalProtector, 'key_directory', side_effect=ApiError('LOCAL_KEY_UNAVAILABLE', '本机保护不可用')), \
                    patch.object(LocalProtector, 'host_identity', side_effect=AssertionError('不能依赖机器标识')), \
                    patch.object(LocalProtector, 'wrap', side_effect=AssertionError('不能依赖本机密钥封装')), \
                    patch('module.runtime.game_data.dpapi', side_effect=AssertionError('不能调用 DPAPI')):
                root = (Path(self.temp.name) / platform).resolve()
                (root / 'config').mkdir(parents=True)
                (root / 'config' / 'test.json').write_text(json.dumps({'Alas': {}}), encoding='utf-8')
                identity, key = load_identity(root, 'test')
                again, same = load_identity(root, 'test')
                self.assertEqual(binding_key(identity, key), binding_key(again, same))
                protection = GameDataProtector(root)
                self.assertTrue(protection.key_path.is_relative_to(root / 'config'))
                self.assertFalse(self.keys.exists())

    def test_failed_initial_write_can_retry_without_partial_identity(self):
        original = (self.root / 'config' / 'test.json').read_bytes()
        with patch.object(GameDataProtector, '_save_state', side_effect=OSError('隔离写入失败')):
            with self.assertRaises(ApiError):
                load_identity(self.root, 'test')
        self.assertFalse(self.protection.key_path.exists())
        self.assertFalse(self.protection.state_path.exists())
        self.assertEqual(original, (self.root / 'config' / 'test.json').read_bytes())
        identity, _ = load_identity(self.root, 'test')
        self.assertEqual(identity, json.loads((self.root / 'config' / 'test.json').read_bytes())['_stockInstance'])

    def test_initialization_with_only_committed_key_can_resume(self):
        # 模拟进程在原子保存密钥后、首次空登记落盘前退出。
        self.protection.key_path.parent.mkdir(mode=0o700)
        original = os.urandom(32)
        self.protection.key_path.write_bytes(original)
        load_identity(self.root, 'test')
        self.assertEqual(original, self.protection.key_path.read_bytes())
        self.assertTrue(self.protection.state_path.exists())

    def test_unregistered_existing_identity_cannot_resume_empty_registry(self):
        load_identity(self.root, 'test')
        self.protection.state_path.unlink()
        self.protection.marker.unlink()
        original = self.protection.key_path.read_bytes()
        with self.assertRaises(ApiError):
            load_identity(self.root, 'test')
        self.assertEqual(original, self.protection.key_path.read_bytes())
        self.assertFalse(self.protection.state_path.exists())

    def test_config_mount_survives_new_process_and_project_path(self):
        identity, key = load_identity(self.root, 'test')
        self.protection.write_file('bindings.json', {'fixture': '原玩家绑定'})
        self.protection.anchor('fixture/history', [3, 4, 'a' * 64], prepare=True)
        self.protection.anchor('fixture/history', [3, 4, 'a' * 64])
        # 只携带配置目录，不携带 cache、HOME、本机目录或旧项目路径。
        moved = Path(self.temp.name) / 'new-installation'
        shutil.copytree(self.root / 'config', moved / 'config')
        script = '''
import sys
from unittest.mock import patch
from module.api.stock_exchange_identity import load_identity, binding_key
from module.runtime.account_local import LocalProtector
from module.runtime.game_data import GameDataProtector
with patch.object(LocalProtector, 'host_identity', side_effect=AssertionError('不能读取机器标识')):
    identity, key = load_identity(sys.argv[1], 'test')
    assert binding_key(identity, key) == sys.argv[2]
    protection = GameDataProtector(sys.argv[1])
    assert protection.read_file('bindings.json') == {'fixture': '原玩家绑定'}
    assert protection.anchor('fixture/history', [3, 4, 'a' * 64])
'''
        result = subprocess.run([sys.executable, '-c', script, str(moved), binding_key(identity, key)],
                                capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(0, result.returncode, result.stderr)

    def test_cache_migration_moves_files_before_any_format_validation(self):
        cache = self.root / 'cache' / 'stock-exchange'
        (cache / 'identities').mkdir(parents=True)
        (cache / 'bindings.json').write_bytes(b'{broken-binding')
        (cache / 'identities' / 'fixture.json').write_bytes(b'old-player-data')
        self.protection.migrate_cache()
        self.assertFalse(cache.exists())
        self.assertEqual(b'{broken-binding', self.protection.file_path('bindings.json').read_bytes())
        self.assertEqual(b'old-player-data', self.protection.file_path('identities/fixture.json').read_bytes())
        self.assertFalse(self.protection.state_path.exists())
        self.assertFalse(self.protection.key_path.exists())

    def test_cache_conflicts_silently_keep_default_config_data(self):
        cache = self.root / 'cache' / 'stock-exchange'
        (cache / 'identities').mkdir(parents=True)
        self.protection.directory.mkdir()
        (self.protection.directory / 'identities').mkdir()
        (cache / 'bindings.json').write_bytes(b'cache-bindings')
        (cache / 'identities' / 'fixture.json').write_bytes(b'cache-identity')
        (cache / 'identities' / 'other.json').write_bytes(b'unique-identity')
        self.protection.file_path('bindings.json').write_bytes(b'config-bindings')
        self.protection.file_path('identities/fixture.json').write_bytes(b'config-identity')
        self.protection.migrate_cache()
        self.assertFalse(cache.exists())
        self.assertEqual(b'config-bindings', self.protection.file_path('bindings.json').read_bytes())
        self.assertEqual(b'config-identity', self.protection.file_path('identities/fixture.json').read_bytes())
        self.assertEqual(b'unique-identity', self.protection.file_path('identities/other.json').read_bytes())

    def test_cache_protected_files_use_normal_config_loading(self):
        identity, key = load_identity(self.root, 'test')
        self.protection.write_file('bindings.json', {'fixture': '保留原绑定'})
        cache = self.root / 'cache' / 'stock-exchange'
        cache.mkdir(parents=True)
        for name in ('identities', 'bindings.json', 'protected-v2'):
            (self.protection.directory / name).replace(cache / name)
        again, same = load_identity(self.root, 'test')
        self.assertFalse(cache.exists())
        self.assertEqual(identity, again)
        self.assertEqual(binding_key(identity, key), binding_key(again, same))
        self.assertEqual({'fixture': '保留原绑定'}, self.protection.read_file('bindings.json'))

    def test_cache_migration_supports_separate_mounts(self):
        cache = self.root / 'cache' / 'stock-exchange'
        (cache / 'history').mkdir(parents=True)
        (cache / 'bindings.json').write_bytes(b'fixture-bindings')
        (cache / 'history' / 'fixture.sqlite3').write_bytes(b'fixture-history')
        with patch('shutil.os.rename', side_effect=OSError(errno.EXDEV, '隔离跨盘迁移夹具')):
            self.protection.migrate_cache()
        self.assertFalse(cache.exists())
        self.assertEqual(b'fixture-bindings', self.protection.file_path('bindings.json').read_bytes())
        self.assertEqual(b'fixture-history', self.protection.file_path('history/fixture.sqlite3').read_bytes())

    def test_parallel_initialization_keeps_one_identity_and_key(self):
        script = '''
import json
import sys
from pathlib import Path
from module.api.stock_exchange_identity import load_identity, binding_key
identity, key = load_identity(sys.argv[1], 'test')
Path(sys.argv[2]).write_text(json.dumps([identity, binding_key(identity, key)]), encoding='utf-8')
'''
        outputs = [Path(self.temp.name) / f'process-{index}.json' for index in range(3)]
        processes = [subprocess.Popen([sys.executable, '-c', script, str(self.root), str(path)],
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      text=True, encoding='utf-8') for path in outputs]
        try:
            for process in processes:
                _, errors = process.communicate(timeout=30)
                self.assertEqual(0, process.returncode, errors)
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                    process.communicate(timeout=10)
        records = [json.loads(path.read_bytes()) for path in outputs]
        self.assertEqual([records[0]] * len(records), records)
        identity, key = load_identity(self.root, 'test')
        self.assertEqual(records[0], [identity, binding_key(identity, key)])

    def test_legacy_migration_keeps_identity_files_bindings_and_checkpoints(self):
        identity, binding, old_state = self.make_legacy()
        original = {path: path.read_bytes() for path in self.protection.directory.rglob('*.json')}
        with patch.object(LocalProtector, 'host_identity', side_effect=AssertionError('容器身份不应阻止迁移')), \
                patch('module.runtime.game_data.dpapi', side_effect=lambda value, decrypt=False: bytes(value)):
            again, key = load_identity(self.root, 'test')
        self.assertEqual(identity, again)
        self.assertEqual(binding, binding_key(again, key))
        for path, raw in original.items():
            self.assertEqual(raw, path.read_bytes())
        self.assertTrue(old_state.exists())
        self.assertEqual({'fixture': '原玩家绑定'}, self.protection.read_file('bindings.json'))
        self.assertTrue(self.protection.anchor('fixture/history', [3, 4, 'a' * 64]))
        envelope = json.loads(self.protection.state_path.read_bytes())
        self.assertNotIn('wrapped', envelope)
        self.assertEqual(old_state.stem, envelope['context'])

    @unittest.skipUnless(os.name == 'nt', '验证真实 Windows DPAPI 旧数据迁移')
    def test_native_windows_legacy_key_migrates(self):
        identity, binding, _ = self.make_legacy(native=True)
        again, key = load_identity(self.root, 'test')
        self.assertEqual(identity, again)
        self.assertEqual(binding, binding_key(again, key))

    def test_interrupted_legacy_migration_reuses_authenticated_key(self):
        identity, binding, _ = self.make_legacy()
        script = '''
import os
import sys
from pathlib import Path
from unittest.mock import patch
from module.api.stock_exchange_identity import load_identity
from module.runtime.account_local import LocalProtector
from module.runtime.game_data import GameDataProtector
with patch.object(LocalProtector, 'key_directory', return_value=Path(sys.argv[2])), \\
     patch('module.runtime.game_data.dpapi', side_effect=lambda value, decrypt=False: bytes(value)), \\
     patch.object(GameDataProtector, '_save_state', side_effect=lambda *args: os._exit(82)):
    load_identity(sys.argv[1], 'test')
'''
        result = subprocess.run([sys.executable, '-c', script, str(self.root), str(self.keys)],
                                capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(82, result.returncode, result.stderr)
        original = self.protection.key_path.read_bytes()
        self.assertFalse(self.protection.state_path.exists())
        with patch('module.runtime.game_data.dpapi', side_effect=lambda value, decrypt=False: bytes(value)):
            again, key = load_identity(self.root, 'test')
        self.assertEqual(identity, again)
        self.assertEqual(binding, binding_key(again, key))
        self.assertEqual(original, self.protection.key_path.read_bytes())

    def test_unrecoverable_legacy_key_does_not_modify_data(self):
        _, _, old_state = self.make_legacy()
        next(self.keys.glob('*.key')).unlink()
        original = old_state.read_bytes()
        files = {path: path.read_bytes() for path in self.protection.directory.rglob('*') if path.is_file()}
        with self.assertRaises(ApiError) as failure:
            load_identity(self.root, 'test')
        self.assertEqual('STOCK_STORAGE_DAMAGED', failure.exception.code)
        self.assertIn('旧版', failure.exception.message)
        self.assertFalse(self.protection.state_path.exists())
        self.assertFalse(self.protection.key_path.exists())
        self.assertEqual(original, old_state.read_bytes())
        for path, raw in files.items():
            self.assertEqual(raw, path.read_bytes())

    def test_missing_portable_registry_never_falls_back_to_old_checkpoint(self):
        self.make_legacy()
        with patch('module.runtime.game_data.dpapi', side_effect=lambda value, decrypt=False: bytes(value)):
            load_identity(self.root, 'test')
        self.protection.write_file('bindings.json', {'fixture': '迁移后的新玩家绑定'})
        original = self.protection.file_path('bindings.json').read_bytes()
        self.protection.state_path.unlink()
        self.protection.key_path.unlink()
        with self.assertRaises(ApiError):
            load_identity(self.root, 'test')
        self.assertFalse(self.protection.state_path.exists())
        self.assertEqual(original, self.protection.file_path('bindings.json').read_bytes())

    def test_modified_key_context_or_registry_blocks_without_rebuilding(self):
        identity, _ = load_identity(self.root, 'test')
        key = self.protection.key_path.read_bytes()
        registry = self.protection.state_path.read_bytes()
        identity_path = self.protection.file_path('identities/' + identity + '.json')
        original = identity_path.read_bytes()
        for corruption in ('key', 'context', 'registry'):
            with self.subTest(corruption=corruption):
                self.protection.key_path.write_bytes(key)
                self.protection.state_path.write_bytes(registry)
                if corruption == 'key':
                    self.protection.key_path.write_bytes(os.urandom(32))
                elif corruption == 'context':
                    envelope = json.loads(registry)
                    envelope['context'] = 'f' * 64
                    self.protection.state_path.write_bytes(canonical(envelope))
                else:
                    self.protection.state_path.write_bytes(b'{broken')
                with self.assertRaises(ApiError):
                    load_identity(self.root, 'test')
                self.assertEqual(original, identity_path.read_bytes())

    @unittest.skipIf(os.name == 'nt', 'POSIX 私有文件权限')
    def test_private_directory_and_key_permissions(self):
        load_identity(self.root, 'test')
        self.assertEqual(0o700, stat.S_IMODE(self.protection.state_path.parent.stat().st_mode))
        self.assertEqual(0o600, stat.S_IMODE(self.protection.key_path.stat().st_mode))
        self.assertEqual(0o600, stat.S_IMODE(self.protection.state_path.stat().st_mode))

    def test_path_alias_above_root_is_not_a_link(self):
        """root 之上的路径别名（macOS 的 /var、Windows junction）不参与链接判定；root 之内的链接仍被拒绝。"""
        alias = Path(self.temp.name) / 'alias'
        inside = self.root / 'cache' / 'stock-exchange'
        try:
            make_directory_link(alias, Path(self.temp.name))
            inside.mkdir(parents=True)
            make_directory_link(inside / 'linked', self.root / 'config')
        except (OSError, subprocess.CalledProcessError):
            self.skipTest('本机不允许创建目录链接')
        self.protection._safe(alias / 'project' / 'cache' / 'stock-exchange' / 'cl1_data.db')
        with self.assertRaises(ApiError):
            self.protection._safe(inside / 'linked' / 'cl1_data.db')


@unittest.skipUnless(sys.platform == 'darwin', '需要原生 macOS，跨平台模拟由通用测试覆盖')
class MacOSGameDataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'project'
        (self.root / 'config').mkdir(parents=True)
        (self.root / 'config' / 'test.json').write_text(json.dumps({'Alas': {}}), encoding='utf-8')

    def test_native_macos_does_not_require_local_provider_or_keychain(self):
        # 实际执行不支持 macOS 的旧提供者分支，确保不因其异常中断新部署。
        with self.assertRaises(ApiError) as failure:
            LocalProtector.key_directory()
        self.assertEqual('LOCAL_KEY_UNAVAILABLE', failure.exception.code)
        with patch.object(LocalProtector, 'host_identity', side_effect=AssertionError('不能读取机器身份')), \
                patch('module.runtime.game_data.dpapi', side_effect=AssertionError('不能调用 DPAPI')):
            identity, key = load_identity(self.root, 'test')
            again, same = load_identity(self.root, 'test')
        self.assertEqual(binding_key(identity, key), binding_key(again, same))
        protection = GameDataProtector(self.root)
        self.assertEqual(0o600, stat.S_IMODE(protection.key_path.stat().st_mode))

    def test_macos_temp_directory_alias_preserves_identity_and_checkpoints(self):
        identity, key = load_identity(self.root, 'test')
        protection = GameDataProtector(self.root)
        protection.write_file('bindings.json', {'fixture': '原玩家绑定'})
        protection.anchor('fixture/history', [3, 4, 'a' * 64], prepare=True)
        protection.anchor('fixture/history', [3, 4, 'a' * 64])
        physical = self.root.resolve()
        again, same = load_identity(physical, 'test')
        reopened = GameDataProtector(physical)
        self.assertEqual(binding_key(identity, key), binding_key(again, same))
        self.assertEqual({'fixture': '原玩家绑定'}, reopened.read_file('bindings.json'))
        self.assertTrue(reopened.anchor('fixture/history', [3, 4, 'a' * 64]))
        self.assertEqual(physical, protection.root)


if __name__ == '__main__':
    unittest.main()
