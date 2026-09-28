"""Windows TPM 密钥封装；只使用硬件提供者，不回退到软件密钥。"""
import base64
import hashlib
import json
import os
import subprocess
from functools import lru_cache

from module.api.protocol import ApiError

# 参数通过 stdin 传入，不进入进程命令行、环境变量或临时脚本。
SCRIPT = r'''
$ErrorActionPreference = 'Stop'
try {
    $request = [Console]::In.ReadToEnd() | ConvertFrom-Json
    $provider = [System.Security.Cryptography.CngProvider]::new('Microsoft Platform Crypto Provider')
    if ($request.action -eq 'wrap') {
        if (![System.Security.Cryptography.CngKey]::Exists($request.name, $provider)) {
            $parameters = [System.Security.Cryptography.CngKeyCreationParameters]::new()
            $parameters.Provider = $provider
            $parameters.KeyUsage = [System.Security.Cryptography.CngKeyUsages]::Decryption
            $parameters.ExportPolicy = [System.Security.Cryptography.CngExportPolicies]::None
            $parameters.Parameters.Add([System.Security.Cryptography.CngProperty]::new(
                'Length', [BitConverter]::GetBytes([int]2048), [System.Security.Cryptography.CngPropertyOptions]::None))
            $key = [System.Security.Cryptography.CngKey]::Create([System.Security.Cryptography.CngAlgorithm]::Rsa, $request.name, $parameters)
        } else {
            $key = [System.Security.Cryptography.CngKey]::Open($request.name, $provider)
        }
    } else {
        $key = [System.Security.Cryptography.CngKey]::Open($request.name, $provider)
    }
    $rsa = [System.Security.Cryptography.RSACng]::new($key)
    $bytes = [Convert]::FromBase64String($request.data)
    if ($request.action -eq 'wrap') {
        $result = $rsa.Encrypt($bytes, [System.Security.Cryptography.RSAEncryptionPadding]::OaepSHA256)
    } else {
        $result = $rsa.Decrypt($bytes, [System.Security.Cryptography.RSAEncryptionPadding]::OaepSHA256)
    }
    [Console]::Out.Write([Convert]::ToBase64String($result))
    $rsa.Dispose()
    $key.Dispose()
} catch { exit 1 }
'''


class TpmProtector:
    """基于 Windows TPM (Microsoft Platform Crypto Provider) 的硬件密钥保护器。

    使用底层硬件安全芯片进行 RSA 密钥生成与 OAEP-SHA256 加解密，确保私钥不可导出。

    Attributes:
        name: 绑定的 TPM CNG 密钥名称字符串。
    """

    @staticmethod
    @lru_cache(maxsize=1)
    def available() -> bool:
        """探测当前主机是否具备可用的 TPM 硬件加密能力。

        执行独立的能力探测，不读取实例保险库，也不触发已绑定数据的销毁策略。

        Returns:
            bool: 具备可用的 TPM 加解密能力返回 True，否则返回 False。
        """
        if os.name != 'nt':
            return False
        script = r'''
$ErrorActionPreference = 'Stop'
$key = $null
$rsa = $null
try {
    $provider = [System.Security.Cryptography.CngProvider]::new('Microsoft Platform Crypto Provider')
    $parameters = [System.Security.Cryptography.CngKeyCreationParameters]::new()
    $parameters.Provider = $provider
    $parameters.KeyUsage = [System.Security.Cryptography.CngKeyUsages]::Decryption
    $parameters.ExportPolicy = [System.Security.Cryptography.CngExportPolicies]::None
    $parameters.Parameters.Add([System.Security.Cryptography.CngProperty]::new(
        'Length', [BitConverter]::GetBytes([int]2048), [System.Security.Cryptography.CngPropertyOptions]::None))
    $name = 'AzurPilot.Capability.' + [Guid]::NewGuid().ToString('N')
    $key = [System.Security.Cryptography.CngKey]::Create([System.Security.Cryptography.CngAlgorithm]::Rsa, $name, $parameters)
    $rsa = [System.Security.Cryptography.RSACng]::new($key)
    $input = [byte[]]::new(32)
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($input)
    $sealed = $rsa.Encrypt($input, [System.Security.Cryptography.RSAEncryptionPadding]::OaepSHA256)
    $output = $rsa.Decrypt($sealed, [System.Security.Cryptography.RSAEncryptionPadding]::OaepSHA256)
    if ([Convert]::ToBase64String($input) -ne [Convert]::ToBase64String($output)) { throw 'probe failed' }
    [Console]::Out.Write('ready')
} catch { exit 1 }
finally {
    if ($key) { $key.Delete() }
    if ($rsa) { $rsa.Dispose() }
    if ($key) { $key.Dispose() }
}
'''
        try:
            result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                                    capture_output=True, timeout=30, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            return result.returncode == 0 and result.stdout == b'ready'
        except (OSError, subprocess.SubprocessError):
            return False

    def __init__(self, root, instance: str):
        """初始化 TPM 保护器。

        Args:
            root: 项目根目录 Path 对象。
            instance: 实例名称。
        """
        # TPM 密钥归属于当前 Windows 用户；同实例复制到另一目录不共享绑定。
        identity = str(root.resolve()) + '\0' + instance
        self.name = 'AzurPilot.Account.' + hashlib.sha256(identity.encode('utf-8')).hexdigest()

    @staticmethod
    def host_identity() -> str:
        """获取 Windows 系统 MachineGuid 的哈希摘要以标识主机硬件。

        Returns:
            str: 机器唯一标识哈希。

        Raises:
            ApiError: 非 Windows 系统或无法读取注册表 MachineGuid。
        """
        if os.name != 'nt':
            raise ApiError('TPM_UNAVAILABLE', 'TPM 自动解锁目前只支持 Windows 主机')
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\Cryptography',
                                0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
                identity = winreg.QueryValueEx(key, 'MachineGuid')[0]
            if not isinstance(identity, str) or not identity:
                raise ValueError()
            return hashlib.sha256(identity.encode('utf-8')).hexdigest()
        except (OSError, ValueError):
            raise ApiError('TPM_UNAVAILABLE', '无法验证 Windows 主机身份') from None

    def execute(self, action: str, data: bytes) -> bytes:
        """调用 PowerShell 子进程执行 TPM CNG 封装或解封操作。

        Args:
            action: 操作类型，'wrap' 或 'unwrap'。
            data: 待处理的字节串。

        Returns:
            bytes: 处理后的字节串。

        Raises:
            ApiError: 系统不支持 TPM 或执行过程抛出异常。
        """
        if os.name != 'nt':
            raise ApiError('TPM_UNAVAILABLE', 'TPM 自动解锁目前只支持 Windows 主机')
        request = json.dumps({'action': action, 'name': self.name, 'data': base64.b64encode(data).decode('ascii')})
        try:
            result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', SCRIPT],
                                    input=request.encode('utf-8'), capture_output=True, timeout=30,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode != 0:
                raise ValueError()
            blob = base64.b64decode(result.stdout, validate=True)
            if len(blob) != (256 if action == 'wrap' else 32):
                raise ValueError()
            return blob
        except (OSError, subprocess.SubprocessError, ValueError):
            raise ApiError('TPM_UNAVAILABLE', 'TPM 不可用或本机绑定失效') from None

    def wrap(self, key: bytes) -> bytes:
        """使用 TPM 硬件密钥封装主密钥。

        Args:
            key: 待封装的主密钥明文字节串。

        Returns:
            bytes: JSON 格式的封装数据载荷字节串。
        """
        identity = self.host_identity()
        blob = self.execute('wrap', key)
        return json.dumps({'version': 1, 'host': identity, 'key': base64.b64encode(blob).decode('ascii')}).encode('utf-8')

    def unwrap(self, blob: bytes) -> bytes:
        """使用 TPM 硬件密钥解封主密钥。

        Args:
            blob: JSON 格式或历史 256 字节的封装数据载荷。

        Returns:
            bytes: 解封还原出的 32 字节主密钥。

        Raises:
            ApiError: 主机已更换 (TPM_DEVICE_CHANGED) 或绑定数据无效 (TPM_UNAVAILABLE)。
        """
        if len(blob) != 256:
            try:
                binding = json.loads(blob)
                if binding['version'] != 1 or not isinstance(binding['host'], str):
                    raise ValueError()
                if binding['host'] != self.host_identity():
                    raise ApiError('TPM_DEVICE_CHANGED', '检测到 Windows 主机已更换')
                blob = base64.b64decode(binding['key'], validate=True)
                if len(blob) != 256:
                    raise ValueError()
            except (ValueError, TypeError, KeyError, UnicodeError):
                raise ApiError('TPM_UNAVAILABLE', 'TPM 绑定数据无效') from None
        # 旧版 256 字节绑定通过实际 TPM 解封校验，失败只阻止自动解锁，保留密码恢复路径。
        return self.execute('unwrap', blob)
