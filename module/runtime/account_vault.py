"""实例账号保险库：磁盘只存密文，解密密钥只驻留当前服务和 worker 内存。"""
import json
import os
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path

from Crypto.Cipher import AES
from Crypto.Protocol.KDF import scrypt

from module.api.config_service import ROOT, validate_name
from module.api.protocol import ApiError

OPERATIONS = threading.RLock()
MAX_BYTES = 16 * 1024 * 1024
_KEEP_MACHINE = object()


class SecretKey:
    """受保护的内存密钥包装对象。

    跨进程传递密钥时避免调试器和富文本异常日志输出明文密钥，并支持主动零化内存。

    Attributes:
        value: 包含密钥数据的可变字节数组 bytearray。
    """

    def __init__(self, value: bytes):
        """初始化密钥容器。

        Args:
            value: 原始密钥字节串。
        """
        self.value = bytearray(value)

    def clear(self):
        """将内部存储的密钥内存缓冲区全部置零覆写。"""
        self.value[:] = b'\0' * len(self.value)

    def __repr__(self) -> str:
        """返回隐藏的调试描述字符串。"""
        return '<实例密钥已隐藏>'


def sensitive_operation(function):
    """敏感账号操作装饰器。

    捕获异常并隐藏底层堆栈与调用参数，防止 trace 日志和异常信息中泄露密码或密钥。

    Args:
        function: 待保护的函数对象。

    Returns:
        Callable: 包装后的受保护函数。
    """
    from functools import wraps

    @wraps(function)
    def wrapped(*args, **kwargs):
        failure = None
        try:
            return function(*args, **kwargs)
        except ApiError as error:
            failure = (error.code, error.message)
        except Exception:
            failure = ('ACCOUNT_FAILED', '账号操作失败，敏感上下文已隐藏；请检查设备和保险库状态')
        # 清除调用参数，不让上层带局部变量的 traceback 暴露密码或密钥。
        args = kwargs = None
        raise ApiError(*failure) from None

    return wrapped


class AccountVault:
    """账号安全保险库管理器。

    管理实例账号数据的 AES-GCM 加密存储、scrypt 密钥派生、内存密钥缓存及物理擦除。

    Attributes:
        root: 项目根目录 Path 对象。
        keys: 内存中缓存的各实例密钥映射。
        failures: 各实例密码验证失败的时间记录（用于防暴力破解）。
        revoked: 当前会话中已标记销毁的实例集合。
    """

    def __init__(self, root=ROOT):
        """初始化账号保险库。

        Args:
            root: 项目根目录路径。
        """
        self.root = Path(root)
        self.keys = {}
        self.failures = {}
        self.revoked = set()

    def path(self, instance: str) -> Path:
        """获取指定实例保险库数据库文件的绝对路径。

        Args:
            instance: 实例名称。

        Returns:
            Path: 保险库 config.db 文件路径。

        Raises:
            ApiError: 实例名非法或路径试图越界。
        """
        instance = validate_name(instance)
        directory = self.root / 'config' / instance
        path = directory / 'config.db'
        if directory.is_symlink() or path.is_symlink() or directory.resolve().parent != (self.root / 'config').resolve():
            raise ApiError('INVALID_PARAMS', '账号保险库路径无效')
        return path

    def marker(self, instance: str) -> Path:
        """获取指定实例的保险库销毁标记文件路径。

        Args:
            instance: 实例名称。

        Returns:
            Path: account.destroyed 标记文件路径。
        """
        return self.path(instance).with_name('account.destroyed')

    def forget(self, instance: str):
        """从内存中安全擦除并移除指定实例的密钥缓存。

        Args:
            instance: 实例名称。
        """
        key = self.keys.pop(instance, None)
        if key is not None:
            key.clear()
        self.failures.pop(instance, None)

    def cache_key(self, instance: str, key: SecretKey):
        """在内存中缓存实例密钥，若存在旧密钥则先将其清空。

        Args:
            instance: 实例名称。
            key: 待缓存的 SecretKey 实例。
        """
        previous = self.keys.get(instance)
        if previous is not None and previous is not key:
            previous.clear()
        self.keys[instance] = key

    @staticmethod
    def wipe_file(path: Path):
        """安全物理擦除指定文件：使用全零数据完全覆写后截断并删除。

        Args:
            path: 待覆写擦除的文件路径。

        Raises:
            OSError: 文件覆写过程写入失败。
        """
        if path.is_symlink():
            path.unlink()
            return
        if not path.exists():
            return
        with path.open('r+b', buffering=0) as file:
            remaining = os.fstat(file.fileno()).st_size
            zeros = bytes(64 * 1024)
            while remaining:
                written = file.write(zeros[:min(remaining, len(zeros))])
                if not written:
                    raise OSError('保险库覆写失败')
                remaining -= written
            os.fsync(file.fileno())
            file.truncate(0)
            os.fsync(file.fileno())
        path.unlink()

    def destroy(self, instance: str):
        """彻底销毁指定实例的账号保险库。

        先持久化写入禁用标记，再物理覆写并删除盐、密文、SQLite 边文件及本地绑定密钥。

        Args:
            instance: 实例名称。

        Raises:
            ApiError: 保险库已禁用但部分物理文件未能成功销毁时抛出 VAULT_DESTROY_FAILED。
        """
        self.revoked.add(validate_name(instance))
        self.forget(instance)
        path = self.path(instance)
        marker = self.marker(instance)
        failed = False
        local_binding = None
        # 销毁标记可能已存在，不能调用会再次进入 destroy 的 record。
        try:
            from module.runtime.account_local import is_local
            if path.exists() and path.stat().st_size <= MAX_BYTES:
                with closing(sqlite3.connect(f'{path.as_uri()}?mode=ro', uri=True)) as db:
                    row = db.execute('SELECT machine FROM vault WHERE id=1').fetchone()
                if row and is_local(row[0]):
                    local_binding = row[0]
        except (sqlite3.Error, OSError):
            pass
        try:
            if marker.is_symlink():
                raise OSError('销毁标记路径无效')
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with marker.open('wb') as file:
                file.write(b'account vault destroyed\n')
                file.flush()
                os.fsync(file.fileno())
        except OSError:
            failed = True
        for suffix in ('', '-journal', '-wal', '-shm'):
            try:
                self.wipe_file(path.with_name(path.name + suffix))
            except OSError:
                failed = True
        if local_binding:
            try:
                self.protector(instance, local_binding).remove(local_binding)
            except Exception:
                failed = True
        if failed:
            raise ApiError('VAULT_DESTROY_FAILED', '保险库已禁止使用，但部分文件未能销毁；请检查文件占用或磁盘权限') from None

    def block_binding(self, instance: str):
        """阻止失效的本机绑定自动解锁，并从内存清除密钥。

        Args:
            instance: 实例名称。

        Raises:
            ApiError: 始终抛出 VAULT_BINDING_UNAVAILABLE。
        """
        self.forget(instance)
        raise ApiError('VAULT_BINDING_UNAVAILABLE', '本机自动解锁验证失败，数据已保留；请用实例密码解除绑定后重新绑定') from None

    def require_active(self, instance: str):
        """确认保险库未被销毁或吊销。

        Args:
            instance: 实例名称。

        Raises:
            ApiError: 保险库处于销毁或吊销状态时抛出 VAULT_DESTROYED。
        """
        if instance in self.revoked or self.marker(instance).exists():
            # 兼容旧版标记，但不再重试销毁磁盘上的剩余数据。
            self.forget(instance)
            raise ApiError('VAULT_DESTROYED', '账号保险库已销毁，请重新设置实例密码并备份账号')

    def checked_record(self, instance: str) -> tuple:
        """读取并验证保险库记录及硬件绑定状态。

        Args:
            instance: 实例名称。

        Returns:
            tuple: 数据库记录元组；不存在则返回 None。
        """
        row = self.record(instance)
        if row is not None and row[5]:
            from module.runtime.account_local import is_local
            if is_local(row[5]):
                try:
                    self.protector(instance, row[5]).binding(row[5])
                except Exception:
                    self.block_binding(instance)
                return row
            key = None
            failed = False
            try:
                key = SecretKey(self.protector(instance, row[5]).unwrap(row[5]))
                self.decrypt(instance, row, key)
            except Exception:
                failed = True
            finally:
                if key is not None:
                    key.clear()
            if failed:
                self.block_binding(instance)
        return row

    def protector(self, instance: str, blob: bytes):
        """根据绑定数据类型获取对应的硬件或本机保护器。

        Args:
            instance: 实例名称。
            blob: 机器绑定数据字节串。

        Returns:
            Union[LocalProtector, TpmProtector]: 匹配的保护器对象。
        """
        from module.runtime.account_local import LocalProtector, is_local
        from module.runtime.account_tpm import TpmProtector
        return LocalProtector(self.root, instance) if is_local(blob) else TpmProtector(self.root, instance)

    def record(self, instance: str) -> tuple:
        """从 SQLite 保险库只读读取原始记录数据。

        Args:
            instance: 实例名称。

        Returns:
            tuple: 包含 (salt, nonce, tag, payload, enabled, machine) 的元组；文件不存在返回 None。

        Raises:
            ApiError: 保险库损坏、文件超大或校验异常。
        """
        self.require_active(instance)
        path = self.path(instance)
        if not path.exists():
            return None
        try:
            if path.stat().st_size > MAX_BYTES:
                raise ValueError()
            with closing(sqlite3.connect(f'{path.as_uri()}?mode=ro', uri=True)) as db:
                row = db.execute('SELECT salt, nonce, tag, payload, enabled, machine FROM vault WHERE id=1').fetchone()
            if row is None or len(row[0]) != 256 or len(row[1]) != 12 or len(row[2]) != 16:
                raise ValueError()
            return row
        except (sqlite3.Error, ValueError, OSError):
            raise ApiError('VAULT_INVALID', '账号保险库损坏，已拒绝读取或写入游戏') from None

    def status(self, instance: str) -> dict:
        """获取指定实例的账号保险库状态摘要。

        Args:
            instance: 实例名称。

        Returns:
            dict: 包含 initialized、enabled、unlocked、tpm_bound、local_bound、destroyed 的字典。
        """
        if instance in self.revoked or self.marker(instance).exists():
            self.forget(instance)
            return {'initialized': False, 'enabled': False, 'unlocked': False, 'tpm_bound': False, 'destroyed': True}
        try:
            row = self.record(instance)
        except ApiError as error:
            if error.code != 'VAULT_DESTROYED':
                raise
            return {'initialized': False, 'enabled': False, 'unlocked': False, 'tpm_bound': False, 'destroyed': True}
        from module.runtime.account_local import is_local
        local = bool(row and is_local(row[5]))
        return {'initialized': row is not None, 'enabled': bool(row and row[4]),
                'unlocked': instance in self.keys, 'tpm_bound': bool(row and row[5] and not local),
                'local_bound': local, 'destroyed': False}

    @staticmethod
    def derive(password: str, salt: bytes) -> SecretKey:
        """使用 scrypt 算法由用户密码和盐派生 32 字节高强度密钥。

        内存成本约 128 MiB (N=2^17, r=8, p=1)；参数固定，拒绝由文件指定成本。

        Args:
            password: 实例密码字符串。
            salt: 256 字节随机盐。

        Returns:
            SecretKey: 派生生成的受保护密钥。
        """
        return SecretKey(scrypt(password.encode('utf-8'), salt, 32, N=2**17, r=8, p=1))

    @staticmethod
    def aad(instance: str, enabled: bool, machine: bytes) -> bytes:
        """构造 AES-GCM 的附加身份验证数据 (AAD)。

        Args:
            instance: 实例名称。
            enabled: 是否启用自动恢复标志。
            machine: 机器绑定数据。

        Returns:
            bytes: 拼接编码后的 AAD 字节串。
        """
        return f'AzurPilot/account-vault/v1/{instance}/{int(enabled)}'.encode('utf-8') + (machine or b'')

    def decrypt(self, instance: str, row: tuple, key: SecretKey) -> dict:
        """使用密钥解密并校验保险库中的账号数据。

        Args:
            instance: 实例名称。
            row: 数据库记录元组。
            key: 解密密钥。

        Returns:
            dict: 解密还原出的 JSON 账号数据字典。

        Raises:
            ApiError: 密码错误或数据被篡改时抛出 VAULT_AUTH_FAILED。
        """
        try:
            cipher = AES.new(key.value, AES.MODE_GCM, nonce=row[1])
            cipher.update(self.aad(instance, row[4], row[5]))
            return json.loads(cipher.decrypt_and_verify(row[3], row[2]))
        except (ValueError, TypeError, UnicodeError):
            raise ApiError('VAULT_AUTH_FAILED', '实例密码不正确或保险库已被篡改') from None

    def authenticate(self, instance: str, password: str) -> tuple[tuple, SecretKey, dict]:
        """验证实例密码并返回数据库记录、派生密钥及解密数据。

        具有防止暴力破解的速率限制延迟保护。

        Args:
            instance: 实例名称。
            password: 用户提交的密码。

        Returns:
            tuple: (原始记录元组, 派生密钥对象, 解密数据字典)。

        Raises:
            ApiError: 认证被限流 (RATE_LIMITED)、未设置密码 (VAULT_NOT_SET) 或密码错误。
        """
        # 人工密码路径独立于自动解锁，允许无 TPM 主机解除旧绑定。
        row = self.record(instance)
        until = self.failures.get(instance, 0)
        if time.monotonic() < until:
            raise ApiError('RATE_LIMITED', '密码验证失败，请稍后重试')
        if row is None:
            raise ApiError('VAULT_NOT_SET', '请先设置独立实例密码')
        key = self.derive(password, row[0])
        try:
            data = self.decrypt(instance, row, key)
        except ApiError:
            self.failures[instance] = time.monotonic() + 5
            raise
        self.failures.pop(instance, None)
        return row, key, data

    def save(self, instance: str, salt: bytes, key: SecretKey, data: dict, enabled: bool = False,
             machine=_KEEP_MACHINE, reset_destroyed: bool = False):
        """将账号数据经 AES-GCM 加密后原子持久化写入 SQLite 保险库。

        Args:
            instance: 实例名称。
            salt: 盐字节串。
            key: 加密密钥。
            data: 待加密保存的账号字典。
            enabled: 是否开启开机自动恢复。
            machine: 机器硬件绑定数据。
            reset_destroyed: 是否重置已销毁状态标记。

        Raises:
            ApiError: 数据超出容量限制时抛出 VAULT_FULL。
        """
        if not reset_destroyed:
            self.require_active(instance)
        if machine is _KEEP_MACHINE:
            row = self.record(instance)
            machine = row[5] if row else None
        cipher = AES.new(key.value, AES.MODE_GCM, nonce=os.urandom(12))
        cipher.update(self.aad(instance, enabled, machine))
        payload, tag = cipher.encrypt_and_digest(json.dumps(data, ensure_ascii=False).encode('utf-8'))
        if len(payload) > MAX_BYTES // 2:
            raise ApiError('VAULT_FULL', '账号数据超过保险库容量限制')
        path = self.path(instance)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        # SQLite 文件、回滚日志与旧页从未包含账号明文。
        with closing(sqlite3.connect(path)) as db, db:
            db.execute('PRAGMA secure_delete=ON')
            db.execute('CREATE TABLE IF NOT EXISTS vault (id INTEGER PRIMARY KEY, salt BLOB, nonce BLOB, tag BLOB, payload BLOB, enabled INTEGER, machine BLOB)')
            db.execute('INSERT OR REPLACE INTO vault VALUES (1, ?, ?, ?, ?, ?, ?)',
                       (salt, cipher.nonce, tag, payload, int(enabled), machine))
        path.chmod(0o600)
        if reset_destroyed:
            self.marker(instance).unlink(missing_ok=True)
            self.revoked.discard(instance)

    def create(self, instance: str, password: str):
        """为指定实例初始化全新的保险库并设置实例密码。

        Args:
            instance: 实例名称。
            password: 实例初始密码。

        Raises:
            ApiError: 保险库已存在时抛出 VAULT_EXISTS。
        """
        destroyed = instance in self.revoked or self.marker(instance).exists()
        if not destroyed and self.record(instance) is not None:
            raise ApiError('VAULT_EXISTS', '实例密码已设置，请使用修改密码')
        self.check_password(password)
        salt = os.urandom(256)
        key = self.derive(password, salt)
        self.save(instance, salt, key, {'profiles': [], 'selected': None}, machine=None, reset_destroyed=destroyed)
        self.cache_key(instance, key)

    @staticmethod
    def check_password(password: str):
        """校验密码复杂度是否达标。

        Args:
            password: 待检测的密码字符串。

        Raises:
            ApiError: 密码长度不足 16 位或不同字符少于 8 种时抛出 WEAK_PASSWORD。
        """
        if len(password) < 16 or len(set(password)) < 8:
            raise ApiError('WEAK_PASSWORD', '请使用至少 16 位、包含至少 8 种不同字符的独立密码或长口令')

    def startup_key(self, instance: str) -> SecretKey:
        """获取实例启动所需的解密密钥（从内存缓存或硬件/本机绑定中解锁）。

        Args:
            instance: 实例名称。

        Returns:
            SecretKey: 解锁成功的密钥对象；未启用恢复时返回 None。

        Raises:
            ApiError: 处于锁定状态需人工解锁 (VAULT_LOCKED) 或未选中账号 (ACCOUNT_NOT_SELECTED)。
        """
        row = self.checked_record(instance)
        if row is None or not row[4]:
            return None
        key = self.keys.get(instance)
        from module.runtime.account_local import is_local
        if is_local(row[5]):
            # 每次启动都重新检查用户目录密钥，不能用旧缓存绕过缺失或不安全权限。
            try:
                local_key = SecretKey(self.protector(instance, row[5]).unwrap(row[5]))
                try:
                    self.decrypt(instance, row, local_key)
                except Exception:
                    local_key.clear()
                    raise
            except Exception:
                self.forget(instance)
                raise
            self.forget(instance)
            key = local_key
            self.cache_key(instance, key)
        if key is None and row[5]:
            failed = False
            try:
                key = SecretKey(self.protector(instance, row[5]).unwrap(row[5]))
                self.decrypt(instance, row, key)
            except Exception:
                failed = True
            if failed:
                if key is not None:
                    key.clear()
                self.block_binding(instance)
            self.cache_key(instance, key)
        if key is None:
            raise ApiError('VAULT_LOCKED', '账号恢复已启用，请先用实例密码解锁；服务重启后需重新解锁')
        data = self.decrypt(instance, row, key)
        if not any(p['id'] == data['selected'] for p in data['profiles']):
            raise ApiError('ACCOUNT_NOT_SELECTED', '请先备份并选择账号')
        return key

    def restore(self, instance: str, device):
        """在排他操作锁保护下将选中的账号快照还原到目标设备中。

        Args:
            instance: 实例名称。
            device: 目标 AccountDevice 设备交互实例。
        """
        with OPERATIONS:
            key = self.startup_key(instance)
            if key is None:
                return
            data = self.decrypt(instance, self.record(instance), key)
            profile = next(p for p in data['profiles'] if p['id'] == data['selected'])
            device.restore(profile['files'])


vault = AccountVault()
