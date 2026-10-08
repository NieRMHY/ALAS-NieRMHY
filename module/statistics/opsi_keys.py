"""统计运行环境的本机凭据接口（现仅服务旧加密数据的一次性解密）。"""
from __future__ import annotations

import base64
import ctypes
import hashlib
import hmac
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from contextlib import nullcontext


class ProviderUnavailable(RuntimeError):
    pass


class KeyProvider:
    name = 'abstract'

    def load(self, slot: str) -> dict | None:
        raise NotImplementedError

    def save(self, slot: str, state: dict) -> None:
        raise NotImplementedError

    def delete(self, slot: str) -> None:
        raise NotImplementedError

    def load_any(self, slot: str, installation_id: str) -> dict | None:
        """按安装标识找回本机状态（安装目录被移动后的解密路径）；默认不支持。"""
        return None

    def new_key(self) -> str:
        return base64.b64encode(os.urandom(32)).decode('ascii')

    def key(self, state: dict) -> bytes:
        return base64.b64decode(state['key'], validate=True)

    def lock(self, slot):
        return nullcontext()

    def decode(self, slot, state, info, token, aad):
        from module.statistics.opsi_secure import _decrypt, _subkey
        return _decrypt(_subkey(self.key(state), info), token, aad)


class DeviceRootProvider(KeyProvider):
    device_class = ''

    def _device(self):
        from module.statistics import opsi_device_keys
        return getattr(opsi_device_keys, self.device_class)()

    def _use_device(self):
        raise NotImplementedError

    def new_key(self):
        raw = os.urandom(32)
        if not self._use_device():
            return base64.b64encode(raw).decode()
        token = self._device().wrap(raw)
        try:
            restored = self._device().unwrap(token)
            if not hmac.compare_digest(raw, restored):
                raise ProviderUnavailable('本机设备对象回读未通过')
        except ProviderUnavailable:
            self._runtime_key = None
            from module.statistics.opsi_device_keys import unpack_reference
            reference, _ = unpack_reference(token, self._device().prefix)
            self._device().delete(reference)
            raise
        self._runtime_key = (token, restored)
        return token

    def key(self, state):
        token = state['key']
        if not token.startswith(self._device().prefix):
            return super().key(state)
        cached = getattr(self, '_runtime_key', None)
        if cached and cached[0] == token:
            return cached[1]
        raw = self._device().unwrap(token)
        if len(raw) != 32:
            raise ProviderUnavailable('本机设备对象不可用')
        self._runtime_key = (token, raw)
        return raw

    def _check_device(self, state):
        if state and state.get('key', '').startswith(self._device().prefix):
            self._device().check(state['key'])
        return state

    def _reference(self, state):
        if not state:
            return None
        if state.get('device_reference'):
            return state['device_reference']
        token = state.get('key', '')
        if token.startswith(self._device().prefix):
            from module.statistics.opsi_device_keys import unpack_reference
            return unpack_reference(token, self._device().prefix)[0]
        return None

    def _save_device_state(self, slot, state, write):
        if state.get('phase') != 'wiping':
            write(state)
            return
        reference = self._reference(self.load(slot))
        write(dict(state, device_reference=reference) if reference else state)
        self._runtime_key = None
        if reference:
            self._device().delete(reference)

    def _delete_device_state(self, slot, delete):
        reference = self._reference(self.load(slot))
        self._runtime_key = None
        if reference:
            self._device().delete(reference)
        delete()


def _credential_type():
    """Windows 凭据管理器的 CREDENTIAL 结构（读取与枚举共用）。"""
    from ctypes import wintypes as w

    class Credential(ctypes.Structure):
        _fields_ = [('Flags', w.DWORD), ('Type', w.DWORD), ('TargetName', w.LPWSTR),
                    ('Comment', w.LPWSTR), ('LastWritten', w.FILETIME),
                    ('CredentialBlobSize', w.DWORD), ('CredentialBlob', ctypes.POINTER(ctypes.c_ubyte)),
                    ('Persist', w.DWORD), ('AttributeCount', w.DWORD), ('Attributes', ctypes.c_void_p),
                    ('TargetAlias', w.LPWSTR), ('UserName', w.LPWSTR)]
    return Credential


class WindowsProvider(DeviceRootProvider):
    name = 'windows-current-user'
    device_class = 'WindowsTPM'

    def _use_device(self):
        return self._device().available()

    def _call(self, action, slot, payload=None):
        from ctypes import wintypes as w
        from module.runtime.account_local import dpapi

        Credential = _credential_type()
        try:
            api = ctypes.WinDLL('advapi32', use_last_error=True)
            target = 'AzurPilot/Statistics/' + slot
            api.CredFree.argtypes = [ctypes.c_void_p]
            if action == 'read':
                output = ctypes.POINTER(Credential)()
                api.CredReadW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, ctypes.POINTER(ctypes.POINTER(Credential))]
                if not api.CredReadW(target, 1, 0, ctypes.byref(output)):
                    if ctypes.get_last_error() == 1168:
                        return None
                    raise ProviderUnavailable('凭据服务不可用')
                try:
                    raw = ctypes.string_at(output.contents.CredentialBlob, output.contents.CredentialBlobSize)
                    return json.loads(dpapi(raw, decrypt=True))
                finally:
                    api.CredFree(output)
            if action == 'delete':
                api.CredDeleteW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD]
                if not api.CredDeleteW(target, 1, 0) and ctypes.get_last_error() != 1168:
                    raise ProviderUnavailable('凭据服务不可用')
                return
            raw = dpapi(json.dumps(payload, separators=(',', ':')).encode())
            if len(raw) > 2560:
                raise ProviderUnavailable('凭据状态超过平台容量')
            buf = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
            credential = Credential(Type=1, TargetName=target, CredentialBlobSize=len(raw),
                                    CredentialBlob=buf, Persist=2, UserName='AzurPilot')
            api.CredWriteW.argtypes = [ctypes.POINTER(Credential), w.DWORD]
            if not api.CredWriteW(ctypes.byref(credential), 0):
                raise ProviderUnavailable('凭据服务不可用')
        except ProviderUnavailable:
            raise
        except Exception as exc:
            raise ProviderUnavailable('本机凭据暂不可用') from exc

    def load(self, slot):
        return self._check_device(self._call('read', slot))

    def save(self, slot, state):
        self._save_device_state(slot, state, lambda value: self._call('write', slot, value))

    def delete(self, slot):
        self._delete_device_state(slot, lambda: self._call('delete', slot))

    def _enumerate_states(self):
        """枚举本机（当前用户）保存的全部统计状态；不可用时返回空列表。"""
        from module.runtime.account_local import dpapi
        try:
            api = ctypes.WinDLL('advapi32', use_last_error=True)
            Credential = _credential_type()
            count = ctypes.c_uint32(0)
            credentials = ctypes.POINTER(ctypes.POINTER(Credential))()
            api.CredEnumerateW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32,
                                           ctypes.POINTER(ctypes.c_uint32),
                                           ctypes.POINTER(ctypes.POINTER(ctypes.POINTER(Credential)))]
            api.CredEnumerateW.restype = ctypes.c_int
            if not api.CredEnumerateW('AzurPilot/Statistics/*', 0, ctypes.byref(count), ctypes.byref(credentials)):
                return []
            try:
                states = []
                for index in range(count.value):
                    item = credentials[index].contents
                    raw = ctypes.string_at(item.CredentialBlob, item.CredentialBlobSize)
                    try:
                        state = json.loads(dpapi(raw, decrypt=True))
                    except Exception:
                        continue
                    if isinstance(state, dict):
                        states.append(state)
                return states
            finally:
                api.CredFree.argtypes = [ctypes.c_void_p]
                api.CredFree(credentials)
        except Exception:
            return []

    def load_any(self, slot, installation_id):
        for state in self._enumerate_states():
            if state.get('installation_id') == installation_id:
                return state
        return None


class SystemKeyringProvider(KeyProvider):
    backend_module = ''
    backend_class = ''

    def _backend(self):
        import importlib
        try:
            backend = getattr(importlib.import_module(self.backend_module), self.backend_class)()
            if backend.priority <= 0:
                raise ProviderUnavailable('本机凭据服务不可用')
            return backend
        except Exception as exc:
            raise ProviderUnavailable('本机凭据服务不可用') from exc

    def load(self, slot):
        try:
            value = self._backend().get_password('AzurPilot.Statistics', slot)
            return json.loads(value) if value else None
        except Exception as exc:
            raise ProviderUnavailable('本机凭据暂不可用') from exc

    def save(self, slot, state):
        try:
            self._backend().set_password('AzurPilot.Statistics', slot, json.dumps(state, separators=(',', ':')))
        except Exception as exc:
            raise ProviderUnavailable('本机凭据暂不可用') from exc

    def delete(self, slot):
        try:
            backend = self._backend()
            if backend.get_password('AzurPilot.Statistics', slot) is not None:
                backend.delete_password('AzurPilot.Statistics', slot)
        except Exception as exc:
            raise ProviderUnavailable('本机凭据暂不可用') from exc

    def _enumerate_states(self):
        """按服务名枚举钥匙串里的全部统计状态（经 secretstorage）；不可用时返回空列表。"""
        try:
            import secretstorage
            connection = secretstorage.dbus_init()
            try:
                collection = secretstorage.get_default_collection(connection)
                states = []
                for item in collection.search_items({'service': 'AzurPilot.Statistics'}):
                    try:
                        state = json.loads(item.get_secret().decode('utf-8'))
                    except Exception:
                        continue
                    if isinstance(state, dict):
                        states.append(state)
                return states
            finally:
                connection.close()
        except Exception:
            return []

    def load_any(self, slot, installation_id):
        for state in self._enumerate_states():
            if state.get('installation_id') == installation_id:
                return state
        return None


class MacOSProvider(DeviceRootProvider):
    """macOS 登录钥匙串凭据（现仅服务旧加密数据解密）。

    查询形态与 keyring 自带的 macOS 后端一致（登录钥匙串 + create_cf 构造）：
    数据保护钥匙串要求进程带钥匙串权限签名，未签名进程会直接被拒（-34018），
    因此只作为旧版本数据的**只读**兼容回退（读取沿用）。不实现按安装标识的
    状态枚举：条目缺少可靠的安装标识检索路径，读不到时按不可解密保留。
    """

    name = 'macos-keychain'
    device_class = 'MacOSEnclave'
    _mode = 'login'

    def _use_device(self):
        return os.getenv('ALAS_STATISTICS_SECURE_ENCLAVE') == '1'

    def _native(self, action, slot, state=None, mode='login'):
        try:
            from keyring.backends.macOS import api
            owned = []

            def value(item):
                pointer = api.create_cf(item)
                owned.append(pointer)
                return pointer

            release = api._found.CFRelease
            release.argtypes = [ctypes.c_void_p]
            query = dict(kSecClass=api.k_('kSecClassGenericPassword'),
                         kSecAttrService=value('AzurPilot.Statistics'), kSecAttrAccount=value(slot))
            if mode == 'dp':
                query.update(kSecUseDataProtectionKeychain=value(True), kSecAttrSynchronizable=value(False))
            try:
                if action == 'read':
                    query['kSecReturnData'] = value(True)
                    query['kSecMatchLimit'] = api.k_('kSecMatchLimitOne')
                    ref = api.create_query(**query)
                    owned.append(ref)
                    output = ctypes.c_void_p()
                    status = api.SecItemCopyMatching(ref, ctypes.byref(output))
                    if status == -25300:
                        return None
                    if status:
                        raise ProviderUnavailable(f'本机凭据暂不可用（{status}）')
                    try:
                        return json.loads(ctypes.string_at(api.CFDataGetBytePtr(output), api.CFDataGetLength(output)))
                    finally:
                        release(output)
                ref = api.create_query(**query)
                owned.append(ref)
                if action == 'delete':
                    status = api.SecItemDelete(ref)
                    if status not in (0, -25300):
                        raise ProviderUnavailable(f'本机凭据暂不可用（{status}）')
                    return
                fields = dict(kSecValueData=value(json.dumps(state, separators=(',', ':'))))
                updates = api.create_query(**fields)
                owned.append(updates)
                update = api._sec.SecItemUpdate
                update.restype = ctypes.c_int32
                update.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
                status = update(ref, updates)
                if status == -25300:
                    add = api.create_query(**query, **fields)
                    owned.append(add)
                    status = api.SecItemAdd(add, None)
                if status:
                    raise ProviderUnavailable(f'本机凭据暂不可用（{status}）')
            finally:
                for pointer in reversed(owned):
                    release(pointer)
        except ProviderUnavailable:
            raise
        except Exception as exc:
            # 带上异常类型：钥匙串框架加载失败、符号缺失等都要能被日志区分出来。
            raise ProviderUnavailable(f'本机凭据暂不可用（{type(exc).__name__}）') from exc

    def load(self, slot):
        state = self._check_device(self._native('read', slot))
        if state is None:
            # 旧版本曾把状态写进数据保护钥匙串：读取沿用该通道，避免环境被判为不存在。
            legacy = self._check_device(self._native('read', slot, mode='dp'))
            if legacy is not None:
                self._mode = 'dp'
                return legacy
        return state

    def save(self, slot, state):
        self._save_device_state(slot, state, lambda value: self._native('write', slot, value, mode=self._mode))

    def delete(self, slot):
        def remove():
            # 两个钥匙串都清理：只删一个会留下可解密的旧状态，撤销不彻底。
            for mode in ('login', 'dp'):
                self._native('delete', slot, mode=mode)
        self._delete_device_state(slot, remove)


class LinuxProvider(SystemKeyringProvider):
    name = 'linux-secret-service'
    backend_module = 'keyring.backends.SecretService'
    backend_class = 'Keyring'
    # 部署检查开关：运行时选择凭据服务前必须显式确认；解密迁移不受该开关限制。
    trusted = False

    def key(self, state):
        if state.get('key', '').startswith('TPM2:'):
            return LinuxTPMProvider().key(state)
        return super().key(state)

    def _backend(self):
        if type(self) is LinuxProvider and not self.trusted \
                and os.environ.get('ALAS_STATISTICS_SECRET_SERVICE_VERIFIED') != '1':
            raise ProviderUnavailable('本机凭据服务尚未通过部署检查')
        backend = super()._backend()
        try:
            collection = backend.get_preferred_collection()
            if collection.is_locked():
                raise ProviderUnavailable('本机凭据集合未就绪')
        except Exception as exc:
            raise ProviderUnavailable('本机凭据集合未就绪') from exc
        return backend


class LinuxTPMProvider(LinuxProvider):
    name = 'linux-tpm2-secret-service'

    @staticmethod
    def available():
        return Path('/dev/tpmrm0').exists()

    @staticmethod
    def _run(*args, data=None):
        try:
            command = [args[0], '-T', 'device:/dev/tpmrm0', *args[1:]]
            # fTPM 建 RSA-2048 primary 实测约 10s，new_key/key 各建一次，留足余量。
            return subprocess.run(command, input=data, check=True, capture_output=True, timeout=60).stdout
        except (OSError, subprocess.SubprocessError) as exc:
            raise ProviderUnavailable('本机设备服务暂不可用') from exc

    def load(self, slot):
        state = super().load(slot)
        # 只有根密钥确实封存在 TPM 里才需要探测设备；否则沿用普通凭据读取。
        if state and str(state.get('key', '')).startswith('TPM2:'):
            self._run('tpm2_getcap', 'properties-fixed')
        return state

    def new_key(self):
        with tempfile.TemporaryDirectory(prefix='azurpilot-device-') as folder:
            parent, public, private = [str(Path(folder) / name) for name in ('parent', 'public', 'private')]
            self._run('tpm2_createprimary', '-Q', '-C', 'o', '-G', 'rsa', '-c', parent)
            raw = os.urandom(32)
            # 封存数据（-i）时 tpm2-tools 禁止 -G：只允许 keyedhash + null scheme。
            self._run('tpm2_create', '-Q', '-C', parent, '-i', '-',
                      '-a', 'fixedtpm|fixedparent|userwithauth|noda', '-u', public, '-r', private, data=raw)
            wrapped = [base64.b64encode(Path(p).read_bytes()).decode() for p in (public, private)]
            token = 'TPM2:' + base64.b64encode(json.dumps(wrapped).encode()).decode()
            if not hmac.compare_digest(raw, self.key({'key': token})):
                self._runtime_key = None
                raise ProviderUnavailable('本机设备对象回读未通过')
            return token

    def key(self, state):
        cached = getattr(self, '_runtime_key', None)
        if cached and cached[0] == state['key']:
            return cached[1]
        # 设备可用性变化（如启用/停用 fTPM）会让选择到本 Provider 的既有环境
        # 只带普通凭据密钥：按基类方式解出即可，不当作设备对象处理。
        if not str(state.get('key', '')).startswith('TPM2:'):
            return super().key(state)
        with tempfile.TemporaryDirectory(prefix='azurpilot-device-') as folder:
            parent, public, private, loaded = [str(Path(folder) / name)
                                              for name in ('parent', 'public', 'private', 'loaded')]
            wrapped = json.loads(base64.b64decode(state['key'][5:], validate=True))
            for path, blob in zip((public, private), wrapped):
                Path(path).write_bytes(base64.b64decode(blob, validate=True))
            self._run('tpm2_createprimary', '-Q', '-C', 'o', '-G', 'rsa', '-c', parent)
            self._run('tpm2_load', '-Q', '-C', parent, '-u', public, '-r', private, '-c', loaded)
            key = self._run('tpm2_unseal', '-c', loaded)
            if len(key) != 32:
                raise ProviderUnavailable('本机设备状态不可用')
            self._runtime_key = (state['key'], key)
            return key

    def save(self, slot, state):
        if state.get('phase') == 'wiping':
            self._runtime_key = None
        super().save(slot, state)

    def delete(self, slot):
        self._runtime_key = None
        super().delete(slot)


class ContainerFileProvider(KeyProvider):
    """容器内未配置宿主统计服务时的本地文件凭据（自动兜底，免配置）。

    状态存于本安装的 config/opsi_secure/state.json，随数据目录迁移；状态不做
    slot 隔离：文件与数据同目录、同搬同走，安装路径变化后应继续可用。
    """

    name = 'container-file'

    def __init__(self, state_path=None):
        self.state_path = Path(state_path) if state_path else (
            Path(__file__).resolve().parents[2] / 'config' / 'opsi_secure' / 'state.json')

    def load(self, slot):
        try:
            payload = json.loads(self.state_path.read_bytes())
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            raise ProviderUnavailable('统计本地凭据不可用') from exc
        if not isinstance(payload, dict) or not isinstance(payload.get('state'), dict):
            raise ProviderUnavailable('统计本地凭据不可用')
        return payload['state']

    def save(self, slot, state):
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.state_path.with_name(self.state_path.name + '.tmp')
            temporary.write_bytes(json.dumps({'slot': slot, 'state': state},
                                             separators=(',', ':')).encode())
            os.replace(temporary, self.state_path)
            os.chmod(self.state_path, 0o600)
        except OSError as exc:
            raise ProviderUnavailable('统计本地凭据不可用') from exc

    def delete(self, slot):
        try:
            self.state_path.unlink(missing_ok=True)
        except OSError as exc:
            raise ProviderUnavailable('统计本地凭据不可用') from exc


def in_container():
    return Path('/.dockerenv').exists() or Path('/run/.containerenv').exists() or bool(os.getenv('container'))


_local_fallback_logged = False


def get_provider():
    if in_container():
        # 容器里没有平台凭据服务：状态存在数据目录内的本地文件（随数据目录迁移）。
        global _local_fallback_logged
        if not _local_fallback_logged:
            _local_fallback_logged = True
            try:
                from module.logger import logger
                logger.warning('[统计-解密] 容器环境按数据目录本地文件读取统计凭据'
                               '（config/opsi_secure/state.json）')
            except Exception:
                pass
        return ContainerFileProvider()
    if sys.platform == 'win32':
        return WindowsProvider()
    if sys.platform == 'darwin':
        return MacOSProvider()
    if sys.platform == 'linux':
        return linux_provider()
    raise ProviderUnavailable('当前平台没有本机凭据服务')


def provider_for_descriptor(name, directory):
    """按描述文件记录的名称恢复当时的凭据提供者实例（旧数据解密）。

    `directory` 为统计目录（容器本地文件提供者的状态文件所在位置）。
    名称不受支持时返回 None；描述文件缺失（name=None）时按平台默认尝试。
    """
    if name is None:
        try:
            return get_provider()
        except ProviderUnavailable:
            return None
    if name == ContainerFileProvider.name:
        return ContainerFileProvider(Path(directory) / 'state.json')
    if name == WindowsProvider.name:
        return WindowsProvider()
    if name == MacOSProvider.name:
        return MacOSProvider()
    if name == LinuxTPMProvider.name:
        provider = LinuxTPMProvider()
        provider.trusted = True
        return provider
    if name == LinuxProvider.name:
        provider = LinuxProvider()
        provider.trusted = True
        return provider
    return None


def linux_provider():
    return LinuxTPMProvider() if LinuxTPMProvider.available() else LinuxProvider()


def installation_slot(root):
    return hashlib.sha256(os.fsencode(str(Path(root).resolve()))).hexdigest()
