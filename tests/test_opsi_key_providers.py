"""本机凭据解析与各平台提供者的隔离验证（现服务于旧数据解密）。"""
import base64
import json
import os
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import Mock, patch

from module.statistics import opsi_keys


class ProviderTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == 'win32', '需要 Windows 凭据服务')
    def test_windows_native_roundtrip_and_delete(self):
        provider = opsi_keys.WindowsProvider()
        slot = 'test-' + uuid.uuid4().hex
        state = {'key': provider.new_key(), 'root': 'root', 'generation': 3}
        try:
            self.assertIsNone(provider.load(slot))
            provider.save(slot, state)
            self.assertEqual(provider.load(slot), state)
            raw = provider.key(state)
            self.assertEqual(len(raw), 32)
            self.assertEqual(opsi_keys.WindowsProvider().key(provider.load(slot)), raw)
            state['generation'] = 4
            provider.save(slot, state)
            self.assertEqual(provider.load(slot)['generation'], 4)
        finally:
            provider.delete(slot)
        self.assertIsNone(provider.load(slot))

    def test_macos_dispatch_and_unavailable(self):
        provider = opsi_keys.MacOSProvider()
        with patch.object(provider, '_native', return_value={'key': 'opaque'}) as native:
            self.assertEqual(provider.load('slot'), {'key': 'opaque'})
            provider.save('slot', {'state': 1})
            provider.delete('slot')
            self.assertEqual([call.args[0] for call in native.call_args_list],
                             ['read', 'write', 'read', 'delete', 'delete'])
        with patch.dict(sys.modules, {'keyring.backends.macOS.api': None}):
            if sys.platform != 'darwin':
                with self.assertRaises(opsi_keys.ProviderUnavailable):
                    provider.load('slot')

    def test_macos_read_falls_back_to_data_protection_keychain(self):
        """旧版本写入数据保护钥匙串的环境：登录钥匙串读不到时走兼容通道并沿用。"""
        provider = opsi_keys.MacOSProvider()
        legacy = {'key': 'opaque', 'installation_id': 'x'}

        def fake_native(action, slot, state=None, mode='login'):
            if action == 'read':
                return legacy if mode == 'dp' else None
            return None

        with patch.object(provider, '_native', side_effect=fake_native) as native:
            self.assertEqual(provider.load('slot'), legacy)
            self.assertEqual(provider._mode, 'dp')
            provider.save('slot', legacy)
            native.assert_called_with('write', 'slot', legacy, mode='dp')

    def test_macos_save_uses_login_keychain_by_default(self):
        provider = opsi_keys.MacOSProvider()
        with patch.object(provider, '_native', return_value=None) as native:
            provider.save('slot', {'key': 'opaque'})
        native.assert_called_once_with('write', 'slot', {'key': 'opaque'}, mode='login')

    def test_macos_delete_clears_both_keychain_modes(self):
        """删除凭据必须两个钥匙串都清理，撤销才彻底。"""
        provider = opsi_keys.MacOSProvider()
        calls = []

        def fake_native(action, slot, state=None, mode='login'):
            calls.append((action, mode))
            return None

        with patch.object(provider, '_native', side_effect=fake_native):
            provider.delete('slot')
        self.assertIn(('delete', 'login'), calls)
        self.assertIn(('delete', 'dp'), calls)

    def test_linux_explicit_service_roundtrip_and_locked(self):
        provider = opsi_keys.LinuxProvider()
        backend = Mock()
        backend.get_password.return_value = json.dumps({'key': 'opaque'})
        with patch.object(provider, '_backend', return_value=backend):
            self.assertEqual(provider.load('slot'), {'key': 'opaque'})
            provider.save('slot', {'key': 'opaque'})
            provider.delete('slot')
            backend.set_password.assert_called_once()
            backend.delete_password.assert_called_once()
        with patch.object(opsi_keys.SystemKeyringProvider, '_backend', return_value=backend):
            backend.get_preferred_collection.return_value.is_locked.return_value = True
            with self.assertRaises(opsi_keys.ProviderUnavailable):
                provider.load('slot')

    def test_linux_never_selects_plaintext_or_third_party_backend(self):
        with patch.object(opsi_keys, 'in_container', return_value=False), patch.dict(os.environ, {}, clear=True), \
                patch.object(opsi_keys.sys, 'platform', 'linux'), patch.object(opsi_keys.LinuxTPMProvider, 'available', return_value=False):
            self.assertIsInstance(opsi_keys.get_provider(), opsi_keys.LinuxProvider)
        with patch.object(opsi_keys, 'in_container', return_value=True), patch.dict(os.environ, {}, clear=True):
            self.assertIsInstance(opsi_keys.get_provider(), opsi_keys.ContainerFileProvider)
        # 容器本地文件密钥只接受数据目录内的状态文件，其余环境变量不改变选择。
        with patch.object(opsi_keys, 'in_container', return_value=True), \
                patch.dict(os.environ, {'ALAS_STATISTICS_BROKER': 'https://127.0.0.1:25549'}, clear=True):
            self.assertIsInstance(opsi_keys.get_provider(), opsi_keys.ContainerFileProvider)

    def test_container_file_provider_roundtrip(self):
        directory = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(directory.cleanup)
        provider = opsi_keys.ContainerFileProvider(Path(directory.name) / 'state.json')
        self.assertIsNone(provider.load('slot'))
        sealed = provider.new_key()
        state = {'phase': 'ready', 'key': sealed, 'installation_id': uuid.uuid4().hex}
        provider.save('slot', state)
        self.assertEqual(provider.load('slot'), state)
        self.assertEqual(provider.key(state), base64.b64decode(sealed))
        provider.delete('slot')
        self.assertIsNone(provider.load('slot'))

    def test_container_file_provider_survives_slot_change(self):
        """状态文件与数据同目录同搬：安装路径变化（slot 变化）后仍按原状态加载。"""
        directory = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(directory.cleanup)
        provider = opsi_keys.ContainerFileProvider(Path(directory.name) / 'state.json')
        state = {'phase': 'ready', 'key': provider.new_key()}
        provider.save('old-slot', state)
        self.assertEqual(provider.load('new-slot'), state)

    def test_provider_for_descriptor_restores_historical_choice(self):
        directory = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__('shutil').rmtree(directory, ignore_errors=True))
        self.assertIsInstance(opsi_keys.provider_for_descriptor('container-file', directory),
                              opsi_keys.ContainerFileProvider)
        self.assertIsInstance(opsi_keys.provider_for_descriptor('windows-current-user', directory),
                              opsi_keys.WindowsProvider)
        self.assertIsInstance(opsi_keys.provider_for_descriptor('macos-keychain', directory),
                              opsi_keys.MacOSProvider)
        linux = opsi_keys.provider_for_descriptor('linux-secret-service', directory)
        self.assertIsInstance(linux, opsi_keys.LinuxProvider)
        self.assertTrue(linux.trusted)              # 解密不受部署检查开关限制
        tpm = opsi_keys.provider_for_descriptor('linux-tpm2-secret-service', directory)
        self.assertIsInstance(tpm, opsi_keys.LinuxTPMProvider)
        self.assertTrue(tpm.trusted)
        self.assertIsNone(opsi_keys.provider_for_descriptor('host-broker', directory))
        self.assertIsNone(opsi_keys.provider_for_descriptor('unknown-provider', directory))

    def test_linux_tpm_sealed_only_and_no_cleartext_temp_file(self):
        provider = opsi_keys.LinuxTPMProvider()
        key = os.urandom(32)
        commands = []

        def run(*args, data=None):
            nonlocal key
            commands.append(args)
            if args[0] == 'tpm2_create':
                self.assertEqual(len(data), 32)
                key = data
                Path(args[args.index('-u') + 1]).write_bytes(b'public')
                Path(args[args.index('-r') + 1]).write_bytes(b'sealed-private')
            if args[0] == 'tpm2_unseal':
                return key
            return b''
        with patch.object(provider, '_run', side_effect=run):
            sealed = provider.new_key()
            self.assertTrue(sealed.startswith('TPM2:'))
            self.assertNotIn(base64.b64encode(key).decode(), sealed)
            self.assertEqual(provider.key({'key': sealed}), key)
        self.assertIn('fixedtpm|fixedparent|userwithauth|noda', commands[1])
        # 封存载荷的 tpm2_create 不得带 -G：真实 tpm2-tools 会拒绝 -G 与 -i 同传。
        self.assertNotIn('-G', commands[1])

    def test_tpm_failure_does_not_fall_back_to_file(self):
        provider = opsi_keys.LinuxTPMProvider()
        with patch.object(provider, '_run', side_effect=opsi_keys.ProviderUnavailable('offline')):
            with self.assertRaises(opsi_keys.ProviderUnavailable):
                provider.new_key()

    def test_linux_tpm_provider_serves_plain_credentials(self):
        """设备可用性切换（如启用 fTPM）后既有环境只带普通凭据密钥：
        按基类方式解出密钥，且不触达任何设备命令。"""
        provider = opsi_keys.LinuxTPMProvider()
        raw = os.urandom(32)
        state = {'key': base64.b64encode(raw).decode()}
        with patch.object(opsi_keys.LinuxTPMProvider, '_run', side_effect=AssertionError('不应触达设备命令')):
            self.assertEqual(provider.key(state), raw)
            with patch.object(opsi_keys.LinuxProvider, 'load', return_value=state):
                self.assertEqual(provider.load('slot'), state)


if __name__ == '__main__':
    unittest.main()
