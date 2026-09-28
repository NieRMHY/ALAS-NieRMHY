"""项目外的本机自动解锁密钥；软件绑定不具有 TPM 的硬件防复制能力。"""
import base64
import ctypes
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import uuid
from pathlib import Path

from Crypto.Cipher import AES

from module.api.protocol import ApiError


def is_local(blob: bytes) -> bool:
    """判定密钥封装载荷是否为本机受保护提供者。

    Args:
        blob: 封装的载荷二进制数据。

    Returns:
        bool: 是本机绑定提供者返回 True，否则返回 False。
    """
    try:
        return isinstance(blob, bytes) and json.loads(blob).get('provider') == 'local'
    except (ValueError, AttributeError, UnicodeError):
        return False


def dpapi(data: bytes, decrypt: bool = False) -> bytes:
    """调用 Windows DPAPI 进行数据加密或解密。

    DPAPI 仅绑定当前 Windows 用户；输入和输出不进入命令行或日志。

    Args:
        data: 待加密或解密的明文/密文字节串。
        decrypt: 若为 True 则执行解密，否则执行加密。

    Returns:
        bytes: 加密或解密后的数据字节串。

    Raises:
        ValueError: DPAPI 加密或解密调用失败。
    """
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]

    source = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    incoming, outgoing = Blob(len(data), source), Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    try:
        if not function(ctypes.byref(incoming), None, None, None, None, 1, ctypes.byref(outgoing)):
            raise ValueError()
        return ctypes.string_at(outgoing.data, outgoing.size)
    finally:
        ctypes.memset(source, 0, len(data))
        if outgoing.data:
            ctypes.memset(outgoing.data, 0, outgoing.size)
            kernel.LocalFree(outgoing.data)


class LocalProtector:
    """基于本机用户环境与凭据保护的主机端密钥管理器。

    在 Windows 环境使用 DPAPI 保护，在 Linux 环境结合 machine-id 及特定权限目录保护。

    Attributes:
        root: 项目根目录的绝对路径。
        instance: 实例名称。
        context: 项目路径与实例绑定的上下文哈希值。
    """

    def __init__(self, root: str, instance: str):
        """初始化本机保护器。

        Args:
            root: 项目根目录路径。
            instance: 实例名称。
        """
        self.root, self.instance = Path(root).resolve(), instance
        self.context = hashlib.sha256((str(self.root) + '\0' + instance).encode()).hexdigest()

    @staticmethod
    def key_directory() -> Path:
        """获取存储本机解锁密钥的安全目录。

        Returns:
            Path: 本机密钥存储目录路径。

        Raises:
            ApiError: 当前操作系统不受支持时抛出 LOCAL_KEY_UNAVAILABLE。
        """
        if os.name == 'nt':
            return Path.home() / 'AppData' / 'Local' / 'AzurPilot' / 'account-keys'
        if sys.platform == 'linux':
            return Path.home() / '.local' / 'share' / 'azurpilot' / 'account-keys'
        raise ApiError('LOCAL_KEY_UNAVAILABLE', '本机自动解锁目前支持 Windows 和 Linux')

    @staticmethod
    def host_identity() -> str:
        """获取并计算当前主机的唯一身份哈希。

        Returns:
            str: 主机身份的 SHA-256 十六进制哈希串。

        Raises:
            ApiError: 无法获取 Windows 用户 SID 或 Linux machine-id。
        """
        if os.name == 'nt':
            from module.runtime.account_tpm import TpmProtector
            # MachineGuid 检测迁移；实际用户保护由 DPAPI 完成。
            identity = TpmProtector.host_identity()
            result = subprocess.run(['whoami.exe', '/user', '/fo', 'csv', '/nh'], capture_output=True,
                                    timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
            sid = re.search(rb'S-1-[0-9-]+', result.stdout)
            if result.returncode or sid is None:
                raise ApiError('LOCAL_KEY_UNAVAILABLE', '无法确认当前 Windows 用户身份')
            identity += '\0' + sid.group().decode('ascii')
        elif sys.platform == 'linux':
            identity = ''
            for name in ('/etc/machine-id', '/var/lib/dbus/machine-id'):
                try:
                    candidate = Path(name).read_text().strip()
                except OSError:
                    continue
                if re.fullmatch(r'[0-9a-fA-F]{32}', candidate):
                    identity = candidate + '\0' + str(os.geteuid())
                    break
            if not identity:
                raise ApiError('LOCAL_KEY_UNAVAILABLE', '无法读取有效 Linux machine-id，已拒绝本机自动解锁')
        else:
            raise ApiError('LOCAL_KEY_UNAVAILABLE', '本机自动解锁目前支持 Windows 和 Linux')
        return hashlib.sha256(identity.encode()).hexdigest()

    def path(self, key_id: str) -> Path:
        """根据密钥 ID 解析对应的本地密钥文件路径并验证其安全性。

        Args:
            key_id: 32 位十六进制密钥标识。

        Returns:
            Path: 本地密钥文件的完整路径。

        Raises:
            ValueError: 密钥 ID 格式不合法或路径中包含软链接/接合点。
            ApiError: 密钥目录被配置在项目内。
        """
        if not re.fullmatch(r'[0-9a-f]{32}', key_id):
            raise ValueError()
        directory = self.key_directory()
        if directory.resolve().is_relative_to(self.root):
            raise ApiError('LOCAL_KEY_UNAVAILABLE', '本机密钥目录不能位于项目内')
        # 拒绝链接与 Windows junction，防止写入路径被引导到项目或共享目录。
        for parent in (directory, *directory.parents):
            if parent.is_symlink() or parent.is_junction():
                raise ValueError()
        path = directory / (self.context + '-' + key_id + '.key')
        if path.is_symlink() or path.is_junction():
            raise ValueError()
        return path

    def prepare_directory(self, directory: Path):
        """创建并严格限制密钥目录的访问权限（仅允许当前用户访问）。

        Args:
            directory: 目标目录路径。

        Raises:
            ValueError: Windows ACL 设置失败或 Linux 目录所有权/权限不符合安全要求。
        """
        directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        if os.name == 'nt':
            script = r'''
$ErrorActionPreference = 'Stop'
try {
    $path = [Console]::In.ReadToEnd() | ConvertFrom-Json
    $sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
    $acl = [System.Security.AccessControl.DirectorySecurity]::new()
    $acl.SetOwner($sid)
    $acl.SetAccessRuleProtection($true, $false)
    $rule = [System.Security.AccessControl.FileSystemAccessRule]::new($sid, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
    $acl.AddAccessRule($rule)
    [System.IO.DirectoryInfo]::new($path).SetAccessControl($acl)
} catch { exit 1 }
'''
            result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                                    input=json.dumps(str(directory)).encode(), capture_output=True, timeout=30,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode:
                raise ValueError()
        else:
            if directory.stat().st_uid != os.geteuid():
                raise ValueError()
            directory.chmod(0o700)

    def load(self, key_id: str) -> bytes:
        """从本地磁盘读取并解密指定的密钥内容。

        Args:
            key_id: 密钥标识字符串。

        Returns:
            bytes: 解密后的 32 字节密钥。

        Raises:
            ValueError: 文件类型异常、权限不安全或解密长度不符合要求。
        """
        path = self.path(key_id)
        flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0)
        with os.fdopen(os.open(path, flags), 'rb') as file:
            info = os.fstat(file.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > 4096:
                raise ValueError()
            if os.name != 'nt':
                directory = path.parent.stat()
                if (info.st_uid != os.geteuid() or info.st_mode & 0o077
                        or directory.st_uid != os.geteuid() or directory.st_mode & 0o077):
                    raise ValueError()
            data = file.read(4097)
        key = dpapi(data, decrypt=True) if os.name == 'nt' else data
        if len(key) != 32:
            raise ValueError()
        return key

    def binding(self, blob: bytes) -> dict:
        """解析并校验封装绑定的元数据及主机一致性。

        Args:
            blob: JSON 格式的绑定数据。

        Returns:
            dict: 解析后的绑定配置字典。

        Raises:
            ValueError: 绑定格式不合法或版本不兼容。
            ApiError: 主机或用户身份已变更时抛出 LOCAL_DEVICE_CHANGED。
        """
        binding = json.loads(blob)
        if binding['provider'] != 'local' or binding['version'] != 1:
            raise ValueError()
        if binding['host'] != self.host_identity():
            raise ApiError('LOCAL_DEVICE_CHANGED', '本机自动解锁的主机或用户身份已改变')
        return binding

    def wrap(self, key: bytes, previous: bytes = None) -> bytes:
        """将主密钥使用本地保护密钥通过 AES-GCM 进行封装。

        Args:
            key: 待封装的主密钥（32 字节）。
            previous: 可选的先前封装载荷，用于就地重轮换。

        Returns:
            bytes: 包含密文、IV、Tag 和主机元数据的 JSON 载荷字节串。

        Raises:
            ApiError: 无法建立本机保护密钥或加密失败。
        """
        from module.runtime.account_vault import SecretKey
        secret = None
        path = None
        created = False
        try:
            host = self.host_identity()
            key_id = self.binding(previous)['id'] if previous else uuid.uuid4().hex
            path = self.path(key_id)
            if previous:
                secret = SecretKey(self.load(key_id))
            else:
                self.prepare_directory(path.parent)
                secret = SecretKey(os.urandom(32))
                data = dpapi(secret.value) if os.name == 'nt' else secret.value
                with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0), 0o600), 'wb') as file:
                    created = True
                    file.write(data)
                    file.flush()
                    os.fsync(file.fileno())
            cipher = AES.new(secret.value, AES.MODE_GCM, nonce=os.urandom(12))
            cipher.update(f'AzurPilot/local/v1/{host}/{self.context}/{key_id}'.encode())
            ciphertext, tag = cipher.encrypt_and_digest(key)
            return json.dumps({'provider': 'local', 'version': 1, 'host': host, 'id': key_id,
                               'nonce': base64.b64encode(cipher.nonce).decode(), 'tag': base64.b64encode(tag).decode(),
                               'payload': base64.b64encode(ciphertext).decode()}).encode()
        except Exception:
            if created and path is not None:
                from module.runtime.account_vault import AccountVault
                AccountVault.wipe_file(path)
            raise ApiError('LOCAL_KEY_UNAVAILABLE', '无法建立本机自动解锁，请检查用户密钥目录、权限及系统加密服务') from None
        finally:
            if secret is not None:
                secret.clear()

    def unwrap(self, blob: bytes) -> bytes:
        """从本地保护封装中解密还原主密钥。

        Args:
            blob: JSON 格式的封装载荷字节串。

        Returns:
            bytes: 解密还原出的 32 字节主密钥。

        Raises:
            ApiError: 封装失效、本地密钥丢失或权限异常。
        """
        from module.runtime.account_vault import SecretKey
        secret = None
        try:
            binding = self.binding(blob)
            secret = SecretKey(self.load(binding['id']))
            cipher = AES.new(secret.value, AES.MODE_GCM, nonce=base64.b64decode(binding['nonce'], validate=True))
            cipher.update(f"AzurPilot/local/v1/{binding['host']}/{self.context}/{binding['id']}".encode())
            key = cipher.decrypt_and_verify(base64.b64decode(binding['payload'], validate=True),
                                            base64.b64decode(binding['tag'], validate=True))
            if len(key) != 32:
                raise ValueError()
            return key
        except ApiError:
            raise
        except Exception:
            raise ApiError('LOCAL_KEY_UNAVAILABLE', '本机密钥丢失、权限不安全或封装失效；启动已阻止，可用实例密码解除绑定后重建') from None
        finally:
            if secret is not None:
                secret.clear()

    def remove(self, blob: bytes):
        """擦除并销毁封装绑定的本地密钥文件。

        Args:
            blob: 包含密钥 ID 的封装载荷字节串。
        """
        from module.runtime.account_vault import AccountVault
        binding = json.loads(blob)
        AccountVault.wipe_file(self.path(binding['id']))
