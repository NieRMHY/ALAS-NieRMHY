"""最终格式的解密向量、设备对象及普通后端故障的隔离验证。"""
import base64
import ctypes
import json
import os
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import Mock, patch

from module.statistics import opsi_secure, opsi_keys
from module.statistics.opsi_device_keys import WindowsTPM, MacOSEnclave, pack_reference
from tests.test_opsi_secure import seal_v2


class DecryptFormatTests(unittest.TestCase):
    def test_draft_xchacha_a31_vector_through_runtime_codec(self):
        """运行时解密必须通过 RFC 向量（写入方向已删除，向量冻结在校验解密）。"""
        key = bytes(range(0x80, 0xA0))
        nonce = bytes(range(0x40, 0x58))
        aad = bytes.fromhex('50515253c0c1c2c3c4c5c6c7')
        raw = (b"Ladies and Gentlemen of the class of '99: If I could offer you only one tip for the future, "
               b"sunscreen would be it.")
        expected = bytes.fromhex(
            'bd6d179d3e83d43b9576579493c0e939572a1700252bfaccbed2902c21396cbb'
            '731c7f1b0b4aa6440bf3a82f4eda7e39ae64c6708c54c216cb96b72e1213b452'
            '2f8c9ba40db5d945b11b69b982c1bb9e3f3fac2bc369488f76b2383565d3fff9'
            '21f9664c97637da9768812f615c68b13b52e'
            'c0875924c1c7987947deafd8780acf49')
        token = base64.b64encode(nonce + expected).decode()
        with patch.object(opsi_secure, 'canonical', return_value=aad):
            self.assertEqual(opsi_secure._decrypt(key, token, {}), raw)

    def test_wrong_key_length_and_tampered_fields_are_rejected(self):
        key = os.urandom(32)
        token = seal_v2(key, 'loot', {'a': 1}, {'dataset': 'loot'}, 'inst')
        for length in (16, 24, 31, 33):
            with self.subTest(length=length), self.assertRaises(ValueError):
                opsi_secure._decrypt(bytes(length), token[len(opsi_secure.BLOB_PREFIX):], {})
        raw = base64.b64decode(token[len(opsi_secure.BLOB_PREFIX):])
        for index in (0, 23, 24, -1):
            changed = bytearray(raw)
            changed[index] ^= 1
            with self.subTest(index=index), self.assertRaises(ValueError):
                opsi_secure._decrypt(key, base64.b64encode(changed).decode(), {})
        with self.assertRaises(ValueError):
            opsi_secure._decrypt(os.urandom(32), token[len(opsi_secure.BLOB_PREFIX):],
                                 {'dataset': 'loot', 'installation_id': 'inst', 'schema': 2,
                                  'algorithm': opsi_secure.ALGORITHM})

    def test_records_only_decode_for_the_matching_installation(self):
        key = os.urandom(32)
        directory = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__('shutil').rmtree(directory, ignore_errors=True))
        secure_dir = directory / 'config' / 'opsi_secure'
        secure_dir.mkdir(parents=True)
        (secure_dir / 'keyring.json').write_bytes(json.dumps(
            {'version': 2, 'algorithm': opsi_secure.ALGORITHM, 'installation_id': 'mine',
             'provider': 'container-file'}).encode())
        (secure_dir / 'state.json').write_bytes(json.dumps({'slot': 'x', 'state': {
            'phase': 'ready', 'key': base64.b64encode(key).decode(), 'installation_id': 'mine'}}).encode())
        previous = opsi_secure._STORE
        opsi_secure.set_store(opsi_secure.StatsStore(directory))
        self.addCleanup(opsi_secure.set_store, previous)
        context = {'dataset': 'loot', 'instance': 'i', 'identity': '1', 'period': '2026-09'}
        good = seal_v2(key, 'loot', {'a': 1}, context, 'mine')
        self.assertEqual(opsi_secure.decode_record('loot', good, context), {'a': 1})
        # 身份不一致（别的安装环境）的记录不可解码。
        foreign = seal_v2(key, 'loot', {'a': 1}, context, 'other')
        self.assertIsNone(opsi_secure.decode_record('loot', foreign, context))
        # 上下文不一致（AAD 不匹配）不可解码。
        self.assertIsNone(opsi_secure.decode_record('loot', good, dict(context, instance='j')))
        # 未知算法版本（V1 前缀以外的变体）不被当作密文处理。
        self.assertIsNone(opsi_secure.decode_record('loot', 'OPSIV3.abc', context))


class DeviceRootTests(unittest.TestCase):
    def setUp(self):
        self.reference = uuid.uuid4().hex
        self.key = os.urandom(32)
        self.device = Mock(prefix=WindowsTPM.prefix)
        self.token = pack_reference(WindowsTPM.prefix, self.reference, b'hardware-wrapped')
        self.device.wrap.return_value = self.token
        def wrap(raw):
            self.device.unwrap.return_value = raw
            return self.token
        self.device.wrap.side_effect = wrap
        self.device.unwrap.return_value = self.key
        self.device.available.return_value = True
        self.provider = opsi_keys.WindowsProvider()
        self.states = {}

        def call(action, slot, state=None):
            if action == 'read':
                return dict(self.states[slot]) if slot in self.states else None
            if action == 'write':
                self.states[slot] = dict(state)
            if action == 'delete':
                self.states.pop(slot, None)
        self.native = patch.object(self.provider, '_call', side_effect=call)
        self.native.start()
        self.addCleanup(self.native.stop)
        self.hardware = patch.object(self.provider, '_device', return_value=self.device)
        self.hardware.start()
        self.addCleanup(self.hardware.stop)

    def test_windows_prefers_tpm_and_existing_objects_never_downgrade(self):
        self.assertEqual(self.provider.new_key(), self.token)
        self.device.wrap.assert_called_once()
        self.device.available.return_value = False
        fallback = self.provider.new_key()
        self.assertEqual(len(base64.b64decode(fallback)), 32)
        self.provider._runtime_key = None
        self.device.unwrap.side_effect = opsi_keys.ProviderUnavailable('offline')
        with self.assertRaises(opsi_keys.ProviderUnavailable):
            self.provider.key({'key': self.token})
        self.device.wrap.assert_called_once()

    def test_transient_creation_failure_has_no_software_fallback(self):
        self.device.available.side_effect = opsi_keys.ProviderUnavailable('tbs offline')
        with self.assertRaises(opsi_keys.ProviderUnavailable):
            self.provider.new_key()
        self.device.wrap.assert_not_called()
        self.device.available.side_effect = None
        self.device.wrap.side_effect = opsi_keys.ProviderUnavailable('pcp offline')
        with self.assertRaises(opsi_keys.ProviderUnavailable):
            self.provider.new_key()

    def test_new_device_root_requires_successful_unwrap_before_state_creation(self):
        self.device.wrap.side_effect = None
        self.device.unwrap.side_effect = opsi_keys.ProviderUnavailable('offline')
        with self.assertRaises(opsi_keys.ProviderUnavailable):
            self.provider.new_key()
        self.device.delete.assert_called_once_with(self.reference)
        self.assertEqual(self.states, {})
        self.assertIsNone(self.provider._runtime_key)

    def test_cached_root_does_not_bypass_device_offline_state_check(self):
        self.provider.new_key()
        self.provider.save('slot', {'key': self.token, 'phase': 'ready'})
        self.device.check.side_effect = opsi_keys.ProviderUnavailable('offline')
        with self.assertRaises(opsi_keys.ProviderUnavailable):
            self.provider.load('slot')

    def test_state_lookup_by_installation_id_recovers_moved_install(self):
        slot = 'current-slot'
        state = {'phase': 'ready', 'key': self.token, 'installation_id': 'install-1'}
        with patch.object(self.provider, '_enumerate_states',
                          return_value=[{'phase': 'ready', 'key': 'x', 'installation_id': 'install-2'}, state]):
            self.assertEqual(self.provider.load_any(slot, 'install-1'), state)
            self.assertIsNone(self.provider.load_any(slot, 'install-3'))

    def test_wiping_revokes_root_before_hardware_cleanup_and_retry(self):
        self.provider.save('slot', {'key': self.token, 'phase': 'ready', 'root': 'original'})
        self.device.delete.side_effect = opsi_keys.ProviderUnavailable('offline')
        with self.assertRaises(opsi_keys.ProviderUnavailable):
            self.provider.save('slot', {'phase': 'wiping'})
        self.assertNotIn('key', self.states['slot'])
        self.assertNotIn('root', self.states['slot'])
        self.assertEqual(self.states['slot']['device_reference'], self.reference)
        self.device.delete.side_effect = None
        self.provider.delete('slot')
        self.assertNotIn('slot', self.states)
        self.device.delete.assert_called_with(self.reference)

    def test_macos_enclave_opt_in_and_existing_binding_is_enforced(self):
        provider = opsi_keys.MacOSProvider()
        device = Mock(prefix=MacOSEnclave.prefix)
        token = pack_reference(device.prefix, self.reference, b'enclave-wrapped')
        device.wrap.return_value = token
        def wrap(raw):
            device.unwrap.return_value = raw
            return token
        device.wrap.side_effect = wrap
        device.unwrap.return_value = self.key
        with patch.object(provider, '_device', return_value=device), \
                patch.dict(os.environ, {'ALAS_STATISTICS_SECURE_ENCLAVE': '1'}):
            self.assertEqual(provider.new_key(), token)
            device.wrap.side_effect = opsi_keys.ProviderUnavailable('not entitled')
            with self.assertRaises(opsi_keys.ProviderUnavailable):
                provider.new_key()
            provider._runtime_key = None
            device.unwrap.return_value = self.key
            with patch.dict(os.environ, {'ALAS_STATISTICS_SECURE_ENCLAVE': '0'}):
                self.assertEqual(provider.key({'key': token}), self.key)

    def test_host_linux_selection_prefers_tpm(self):
        with patch.object(opsi_keys.LinuxTPMProvider, 'available', return_value=True):
            self.assertIsInstance(opsi_keys.linux_provider(), opsi_keys.LinuxTPMProvider)

    def test_linux_cached_root_still_requires_the_live_device(self):
        provider = opsi_keys.LinuxTPMProvider()
        provider._runtime_key = ('TPM2:opaque', self.key)
        with patch.object(opsi_keys.LinuxProvider, 'load', return_value={'key': 'TPM2:opaque'}), \
                patch.object(provider, '_run', side_effect=opsi_keys.ProviderUnavailable('offline')) as run:
            with self.assertRaises(opsi_keys.ProviderUnavailable):
                provider.load('slot')
            run.assert_called_once_with('tpm2_getcap', 'properties-fixed')

    def test_linux_tss_uses_local_device_without_secret_arguments(self):
        with patch.object(opsi_keys.subprocess, 'run', return_value=Mock(stdout=b'')) as run:
            opsi_keys.LinuxTPMProvider._run('tpm2_create', '-i', '-', data=self.key)
            command = run.call_args.args[0]
            self.assertEqual(command[:3], ['tpm2_create', '-T', 'device:/dev/tpmrm0'])
            self.assertEqual(run.call_args.kwargs['input'], self.key)
            self.assertNotIn(self.key, command)

    def test_windows_tpm_probe_never_raises_and_fails_closed(self):
        """设备探针任何失败都只回 False（绝不抛错），由调用方回退账户级凭据。

        Modify by MHY, available() 在非 Windows 上会直接短路返回 False，
        下面的断言只在 Windows 分支上有意义，因此把 os.name 固定为 nt，
        否则用例在 Linux 上永远走不到探针逻辑。
        """
        self.enterContext(patch.object(opsi_keys.os, 'name', 'nt'))
        self.addCleanup(WindowsTPM.available.cache_clear)
        WindowsTPM.available.cache_clear()
        with patch.object(WindowsTPM, '_api', side_effect=opsi_keys.ProviderUnavailable('no device')):
            self.assertFalse(WindowsTPM.available())
        WindowsTPM.available.cache_clear()
        api = Mock()
        api.NCryptOpenStorageProvider.return_value = 0x80090035  # 设备未就绪
        with patch.object(WindowsTPM, '_api', return_value=api):
            self.assertFalse(WindowsTPM.available())
        WindowsTPM.available.cache_clear()
        api = Mock()
        api.NCryptOpenStorageProvider.return_value = 0
        api.NCryptCreatePersistedKey.return_value = 0
        api.NCryptSetProperty.return_value = 0
        api.NCryptFinalizeKey.return_value = 0x80090030  # 落盘时设备不存在
        with patch.object(WindowsTPM, '_api', return_value=api):
            self.assertFalse(WindowsTPM.available())
        WindowsTPM.available.cache_clear()
        api = Mock()
        api.NCryptOpenStorageProvider.return_value = 0
        api.NCryptCreatePersistedKey.return_value = 0
        api.NCryptSetProperty.return_value = 0
        api.NCryptFinalizeKey.return_value = 0
        with patch.object(WindowsTPM, '_api', return_value=api):
            self.assertTrue(WindowsTPM.available())
        self.assertTrue(api.NCryptDeleteKey.called)  # 临时密钥随即删除
        WindowsTPM.available.cache_clear()

    @unittest.skipUnless(sys.platform == 'win32', '需要 Windows CNG')
    def test_native_cng_non_exportable_restart_and_wrong_object(self):
        WindowsTPM.available.cache_clear()
        if not WindowsTPM.available():
            self.skipTest('本机没有 TPM2')
        hardware = WindowsTPM()
        token = hardware.wrap(self.key)
        from module.statistics.opsi_device_keys import unpack_reference
        reference, data = unpack_reference(token, hardware.prefix)
        try:
            self.assertNotIn(base64.b64encode(self.key).decode(), token)
            self.assertEqual(WindowsTPM().unwrap(token), self.key)
            with hardware._provider() as (api, provider):
                handle = ctypes.c_size_t()
                hardware._check(api.NCryptOpenKey(provider, ctypes.byref(handle), hardware._name(reference), 0, hardware.silent))
                try:
                    policy, size = ctypes.c_uint32(), ctypes.c_uint32()
                    hardware._check(api.NCryptGetProperty(handle, 'Export Policy', ctypes.byref(policy), 4, ctypes.byref(size), 0))
                    self.assertEqual(policy.value, 0)
                finally:
                    api.NCryptFreeObject(handle)
            wrong = pack_reference(hardware.prefix, uuid.uuid4().hex, data)
            with self.assertRaises(opsi_keys.ProviderUnavailable):
                WindowsTPM().unwrap(wrong)
        finally:
            hardware.delete(reference)
        with self.assertRaises(opsi_keys.ProviderUnavailable):
            WindowsTPM().unwrap(token)
        hardware.delete(reference)


if __name__ == '__main__':
    unittest.main()
