"""本机设备对象的创建、使用与回收。"""
from __future__ import annotations

import base64
import ctypes
import json
import os
import uuid
from contextlib import contextmanager
from functools import lru_cache

from module.statistics.opsi_keys import ProviderUnavailable


def pack_reference(prefix, name, data):
    return prefix + base64.b64encode(json.dumps([name, base64.b64encode(data).decode()]).encode()).decode()


def unpack_reference(token, prefix):
    try:
        if not token.startswith(prefix):
            raise ValueError()
        name, value = json.loads(base64.b64decode(token[len(prefix):], validate=True))
        if not isinstance(name, str) or len(name) != 32 or uuid.UUID(hex=name).hex != name:
            raise ValueError()
        return name, base64.b64decode(value, validate=True)
    except (ValueError, TypeError, AttributeError) as exc:
        raise ProviderUnavailable('本机设备对象不可用') from exc


class WindowsTPM:
    prefix = 'CNG-TPM2:'
    silent = 0x40
    missing = (0x80090016, 0x80090011)

    @staticmethod
    @lru_cache(maxsize=1)
    def available() -> bool:
        """本机是否真能执行 TPM 硬件密钥操作（功能探针，永不抛错）。

        接口存在不代表可用：部分机器上没有 TPM 时探测接口依旧应答，误判会让
        统计环境在设备封装上反复失败。判据是完整走一遍密钥生成——建一把临时
        2048 位密钥、完成落盘、随即删除；任何一步失败或不完整都视为无设备，
        调用方回退账户级凭据，统计功能不受影响。结果按进程缓存（单次约 1 秒）。
        """
        if os.name != 'nt':
            return False
        try:
            api = WindowsTPM._api()
        except ProviderUnavailable:
            return False
        provider = ctypes.c_size_t()
        try:
            if api.NCryptOpenStorageProvider(ctypes.byref(provider), 'Microsoft Platform Crypto Provider', 0):
                return False
            try:
                key = ctypes.c_size_t()
                name = 'AzurPilot.Probe.' + uuid.uuid4().hex
                if api.NCryptCreatePersistedKey(provider, ctypes.byref(key), 'RSA', name, 0, 0):
                    return False
                try:
                    value = ctypes.c_uint32(2048)
                    if api.NCryptSetProperty(key, 'Length', ctypes.byref(value), 4, 0):
                        return False
                    if api.NCryptFinalizeKey(key, WindowsTPM.silent):
                        return False
                    return True
                finally:
                    api.NCryptDeleteKey(key, 0)
                    api.NCryptFreeObject(key)
            finally:
                api.NCryptFreeObject(provider)
        except Exception:
            return False

    @staticmethod
    def _api():
        try:
            api = ctypes.WinDLL('ncrypt')
            handle, dword, ptr, text = ctypes.c_size_t, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_wchar_p
            signatures = {
                'NCryptOpenStorageProvider': [ctypes.POINTER(handle), text, dword],
                'NCryptCreatePersistedKey': [handle, ctypes.POINTER(handle), text, text, dword, dword],
                'NCryptOpenKey': [handle, ctypes.POINTER(handle), text, dword, dword],
                'NCryptSetProperty': [handle, text, ptr, dword, dword],
                'NCryptGetProperty': [handle, text, ptr, dword, ctypes.POINTER(dword), dword],
                'NCryptFinalizeKey': [handle, dword], 'NCryptDeleteKey': [handle, dword],
                'NCryptFreeObject': [handle],
                'NCryptEncrypt': [handle, ptr, dword, ptr, ptr, dword, ctypes.POINTER(dword), dword],
                'NCryptDecrypt': [handle, ptr, dword, ptr, ptr, dword, ctypes.POINTER(dword), dword],
            }
            for name, signature in signatures.items():
                function = getattr(api, name)
                function.argtypes, function.restype = signature, ctypes.c_uint32
            return api
        except (OSError, AttributeError) as exc:
            raise ProviderUnavailable('本机设备服务暂不可用') from exc

    @staticmethod
    def _check(status):
        if status:
            raise ProviderUnavailable('本机设备操作未完成')

    @contextmanager
    def _provider(self):
        api = self._api()
        provider = ctypes.c_size_t()
        self._check(api.NCryptOpenStorageProvider(ctypes.byref(provider), 'Microsoft Platform Crypto Provider', 0))
        try:
            result, size = ctypes.c_uint32(), ctypes.c_uint32()
            self._check(api.NCryptGetProperty(provider, 'Impl Type', ctypes.byref(result), 4, ctypes.byref(size), 0))
            if not result.value & 1:
                raise ProviderUnavailable('本机设备后端不满足要求')
            yield api, provider
        finally:
            api.NCryptFreeObject(provider)

    @staticmethod
    def _name(reference):
        return 'AzurPilot.Statistics.' + reference

    def _crypt(self, api, key, data, decrypt=False):
        class Padding(ctypes.Structure):
            _fields_ = [('algorithm', ctypes.c_wchar_p), ('label', ctypes.c_void_p), ('length', ctypes.c_uint32)]
        padding = Padding('SHA256', None, 0)
        source = ctypes.create_string_buffer(data)
        size = ctypes.c_uint32()
        function = api.NCryptDecrypt if decrypt else api.NCryptEncrypt
        flags = 4 | self.silent
        self._check(function(key, source, len(data), ctypes.byref(padding), None, 0, ctypes.byref(size), flags))
        output = ctypes.create_string_buffer(size.value)
        self._check(function(key, source, len(data), ctypes.byref(padding), output, size.value, ctypes.byref(size), flags))
        return output.raw[:size.value]

    def wrap(self, raw):
        if not self.available():
            raise ProviderUnavailable('本机设备服务暂不可用')
        reference = uuid.uuid4().hex
        with self._provider() as (api, provider):
            key = ctypes.c_size_t()
            self._check(api.NCryptCreatePersistedKey(provider, ctypes.byref(key), 'RSA', self._name(reference), 0, 0))
            complete = False
            try:
                for property_, number in [('Length', 2048), ('Export Policy', 0), ('Key Usage', 1)]:
                    value = ctypes.c_uint32(number)
                    self._check(api.NCryptSetProperty(key, property_, ctypes.byref(value), 4, 0))
                self._check(api.NCryptFinalizeKey(key, self.silent))
                token = pack_reference(self.prefix, reference, self._crypt(api, key, raw))
                complete = True
                return token
            finally:
                if complete:
                    api.NCryptFreeObject(key)
                else:
                    if api.NCryptDeleteKey(key, 0):
                        api.NCryptFreeObject(key)

    def unwrap(self, token):
        reference, data = unpack_reference(token, self.prefix)
        with self._provider() as (api, provider):
            key = ctypes.c_size_t()
            self._check(api.NCryptOpenKey(provider, ctypes.byref(key), self._name(reference), 0, self.silent))
            try:
                return self._crypt(api, key, data, decrypt=True)
            finally:
                api.NCryptFreeObject(key)

    def check(self, token):
        reference, _ = unpack_reference(token, self.prefix)
        # 不再单独探测：能否打开设备密钥本身就是判据（探测另有一次建键开销）。
        with self._provider() as (api, provider):
            key = ctypes.c_size_t()
            self._check(api.NCryptOpenKey(provider, ctypes.byref(key), self._name(reference), 0, self.silent))
            api.NCryptFreeObject(key)

    def delete(self, reference):
        with self._provider() as (api, provider):
            key = ctypes.c_size_t()
            status = api.NCryptOpenKey(provider, ctypes.byref(key), self._name(reference), 0, self.silent)
            if status in self.missing:
                return
            self._check(status)
            status = api.NCryptDeleteKey(key, 0)
            if status:
                api.NCryptFreeObject(key)
                self._check(status)


class MacOSEnclave:
    prefix = 'SECURE-ENCLAVE:'

    def _operate(self, action, reference, raw=None):
        owned = []
        try:
            from keyring.backends.macOS import api
            release = api._found.CFRelease
            release.argtypes = [ctypes.c_void_p]

            def own(pointer):
                if not pointer:
                    raise ProviderUnavailable('本机设备服务暂不可用')
                owned.append(pointer)
                return pointer

            def function(name, signature, result=ctypes.c_void_p):
                value = getattr(api._sec, name)
                value.argtypes, value.restype = signature, result
                return value

            def data(value):
                create = api._found.CFDataCreate
                create.argtypes, create.restype = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long], ctypes.c_void_p
                return own(create(None, value, len(value)))

            true = ctypes.c_void_p.in_dll(api._found, 'kCFBooleanTrue')
            false = ctypes.c_void_p.in_dll(api._found, 'kCFBooleanFalse')
            tag = data(('AzurPilot.Statistics.' + reference).encode())
            fields = dict(kSecClass=api.k_('kSecClassKey'), kSecAttrApplicationTag=tag,
                          kSecAttrKeyType=api.k_('kSecAttrKeyTypeECSECPrimeRandom'),
                          kSecAttrTokenID=api.k_('kSecAttrTokenIDSecureEnclave'),
                          kSecUseDataProtectionKeychain=true, kSecAttrSynchronizable=false,
                          kSecUseAuthenticationUI=api.k_('kSecUseAuthenticationUIFail'))
            query = own(api.create_query(**fields))
            if action == 'delete':
                status = api.SecItemDelete(query)
                if status not in (0, -25300):
                    raise ProviderUnavailable('本机设备服务暂不可用')
                return
            error = ctypes.c_void_p()
            if action == 'wrap':
                access = function('SecAccessControlCreateWithFlags',
                                  [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p])(
                    None, api.k_('kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly'), 1 << 30, ctypes.byref(error))
                if error.value:
                    owned.append(error)
                access = own(access)
                private = own(api.create_query(kSecAttrIsPermanent=true, kSecAttrApplicationTag=tag,
                                               kSecAttrAccessControl=access))
                bits = own(api.create_cf(256))
                attributes = own(api.create_query(kSecAttrKeyType=api.k_('kSecAttrKeyTypeECSECPrimeRandom'),
                                                  kSecAttrKeySizeInBits=bits,
                                                  kSecAttrTokenID=api.k_('kSecAttrTokenIDSecureEnclave'),
                                                  kSecUseDataProtectionKeychain=true,
                                                  kSecPrivateKeyAttrs=private))
                error = ctypes.c_void_p()
                key = function('SecKeyCreateRandomKey', [ctypes.c_void_p, ctypes.c_void_p])(attributes, ctypes.byref(error))
            else:
                query = own(api.create_query(**fields, kSecReturnRef=true, kSecMatchLimit=api.k_('kSecMatchLimitOne')))
                key = ctypes.c_void_p()
                if api.SecItemCopyMatching(query, ctypes.byref(key)):
                    raise ProviderUnavailable('本机设备对象暂不可用')
            if error.value:
                owned.append(error)
            key = own(key)
            if action == 'check':
                return
            algorithm = api.k_('kSecKeyAlgorithmECIESEncryptionCofactorX963SHA256AESGCM')
            if action == 'wrap':
                key = own(function('SecKeyCopyPublicKey', [ctypes.c_void_p])(key))
            operation = 2 if action == 'wrap' else 3
            if not function('SecKeyIsAlgorithmSupported', [ctypes.c_void_p, ctypes.c_long, ctypes.c_void_p], ctypes.c_bool)(
                    key, operation, algorithm):
                raise ProviderUnavailable('本机设备对象不支持此操作')
            error = ctypes.c_void_p()
            value = function('SecKeyCreateEncryptedData' if action == 'wrap' else 'SecKeyCreateDecryptedData',
                             [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p])(
                key, algorithm, data(raw), ctypes.byref(error))
            if error.value:
                owned.append(error)
            value = own(value)
            return ctypes.string_at(api.CFDataGetBytePtr(value), api.CFDataGetLength(value))
        except ProviderUnavailable:
            raise
        except Exception as exc:
            raise ProviderUnavailable('本机设备服务暂不可用') from exc
        finally:
            if owned:
                for pointer in reversed(owned):
                    release(pointer)

    def wrap(self, raw):
        reference = uuid.uuid4().hex
        try:
            return pack_reference(self.prefix, reference, self._operate('wrap', reference, raw))
        except ProviderUnavailable:
            try:
                self.delete(reference)
            except ProviderUnavailable:
                pass
            raise

    def unwrap(self, token):
        reference, raw = unpack_reference(token, self.prefix)
        return self._operate('unwrap', reference, raw)

    def delete(self, reference):
        self._operate('delete', reference)

    def check(self, token):
        reference, _ = unpack_reference(token, self.prefix)
        self._operate('check', reference)
