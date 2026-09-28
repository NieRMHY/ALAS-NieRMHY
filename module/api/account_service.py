"""账号管理 API 模块。

提供账号保险库管理服务，每次敏感操作重新验证实例密码。
支持国服客户端账号快照备份、切换、本地密钥自动解锁与 TPM 绑定。
"""

import secrets
import uuid

from module.api.protocol import ApiError
from module.runtime.account_device import PACKAGE, AccountDevice
from module.runtime.account_local import LocalProtector, is_local
from module.runtime.account_vault import OPERATIONS, AccountVault, sensitive_operation, vault
from module.runtime.process_manager import ProcessManager


def device_for(configs, instance, device=None):
    """根据实例配置获取对应的账号设备操作对象。

    Args:
        configs: 配置管理服务实例。
        instance (str): 实例名称。
        device (optional): 已有的设备连接实例。默认为 None。

    Returns:
        AccountDevice: 账号设备操作对象。

    Raises:
        ApiError: 客户端包名不受支持时抛出 ACCOUNT_UNSUPPORTED。
    """
    data, _ = configs.read(instance)
    emulator = data.get('Alas', {}).get('Emulator', {})
    if emulator.get('PackageName') != PACKAGE:
        raise ApiError('ACCOUNT_UNSUPPORTED', '账号管理目前只支持国服 B 站客户端')
    # worker 使用设备层实际连接成功的地址和 ADB，避免绕过连接与模拟器冷启动。
    if device is not None:
        return AccountDevice(device.serial, device.adb_binary)
    from deploy.config import DeployConfig
    from module.runtime.setting import State
    adb = DeployConfig().filepath('AdbExecutable') if State.deploy_config is None else State.deploy_config.filepath('AdbExecutable')
    return AccountDevice(emulator.get('Serial'), adb)


def ensure_idle(configs, instance):
    """确保指定实例及其复用同一模拟器的其他实例处于停止状态。

    Args:
        configs: 配置管理服务实例。
        instance (str): 实例名称。

    Raises:
        ApiError: 存在正在运行的相关实例时抛出 INSTANCE_RUNNING。
    """
    data, _ = configs.read(instance)
    serial = data.get('Alas', {}).get('Emulator', {}).get('Serial')
    for name in configs.names():
        other, _ = configs.read(name)
        if (name == instance or other.get('Alas', {}).get('Emulator', {}).get('Serial') == serial) and ProcessManager.is_running(name):
            raise ApiError('INSTANCE_RUNNING', '请先停止此实例以及使用同一模拟器的其他实例')


class AccountService:
    """账号保险库与快照管理服务。

    负责处理账号保险库的锁定/解锁、快照捕获与恢复、密码变更及硬件保护绑定。
    """

    def __init__(self, configs):
        """初始化账号管理服务。

        Args:
            configs: 配置管理服务实例。
        """
        self.configs = configs
        self.vault = vault if configs.root.resolve() == vault.root.resolve() else AccountVault(configs.root)

    def status(self, params):
        """获取指定实例的账号保险库状态。

        Args:
            params: 状态请求参数对象，包含 instance 字段。

        Returns:
            dict: 账号保险库当前状态字典。
        """
        instance = self.configs.path(params.instance).stem
        with OPERATIONS:
            return self.status_result(instance)

    def status_result(self, instance):
        """组装指定实例的保险库状态字典（包含 TPM 可用性）。

        Args:
            instance (str): 实例名称。

        Returns:
            dict: 状态字典，包含 tpm_available 等字段。
        """
        from module.runtime.account_tpm import TpmProtector
        result = self.vault.status(instance)
        result['tpm_available'] = bool(TpmProtector.available())
        return result

    @sensitive_operation
    def manage(self, params, web_password=''):
        """执行账号管理敏感操作。

        Args:
            params: 管理请求参数，包含 action, instance, password 等。
            web_password (str, optional): WebUI 当前密码，用于防重用校验。默认为 ''。

        Returns:
            dict: 操作完成后的状态字典或包含快照列表的数据字典。

        Raises:
            ApiError: 参数不合法、密码错误、快照满额或设备未选择时抛出。
        """
        instance, action = self.configs.path(params.instance).stem, params.action
        with ProcessManager._get_lifecycle_lock(instance), OPERATIONS:
            if action == 'lock':
                ensure_idle(self.configs, instance)
                self.vault.forget(instance)
                return self.status_result(instance)
            if action in ('create', 'password'):
                password = params.password if action == 'create' else params.new_password
                self.vault.check_password(password)
                if web_password and secrets.compare_digest(password.encode(), web_password.encode()):
                    raise ApiError('PASSWORD_REUSED', '实例密码必须与 WebUI 密码不同')
            if action == 'create':
                ensure_idle(self.configs, instance)
                self.vault.create(instance, params.password)
                return self.status_result(instance)
            row, key, data = self.vault.authenticate(instance, params.password)
            if action in ('capture', 'select', 'enable', 'password', 'delete', 'bind_tpm', 'unbind_tpm', 'bind_local', 'unbind_local'):
                ensure_idle(self.configs, instance)
            enabled = bool(row[4])
            machine = row[5]
            if action == 'capture':
                if len(data['profiles']) >= 20:
                    raise ApiError('VAULT_FULL', '最多保存 20 份账号快照')
                files, users = device_for(self.configs, instance).capture()
                profile = {'id': uuid.uuid4().hex, 'label': params.label or '账号快照', 'files': files, 'users': users}
                data['profiles'].append(profile)
                data['selected'] = data['selected'] or profile['id']
            elif action in ('select', 'delete'):
                profile = next((p for p in data['profiles'] if p['id'] == params.profile), None)
                if profile is None:
                    raise ApiError('ACCOUNT_NOT_FOUND', '账号快照不存在')
                if action == 'select':
                    device = device_for(self.configs, instance)
                    device.restore(profile['files'])
                    data['selected'] = profile['id']
                    self.vault.save(instance, row[0], key, data, enabled)
                    device.launch()
                else:
                    data['profiles'].remove(profile)
                    if data['selected'] == profile['id']:
                        data['selected'] = None
                        enabled = False
            elif action == 'enable':
                enabled = params.enabled
                if enabled and not data['selected']:
                    raise ApiError('ACCOUNT_NOT_SELECTED', '请先备份并选择账号')
            elif action == 'password':
                salt = secrets.token_bytes(256)
                key = self.vault.derive(params.new_password, salt)
                row = (salt,)
                if machine:
                    try:
                        protector = self.vault.protector(instance, machine)
                        machine = protector.wrap(key.value, previous=machine) if is_local(machine) else protector.wrap(key.value)
                    except Exception:
                        key.clear()
                        if is_local(machine):
                            raise
                        self.vault.block_binding(instance)
            elif action == 'bind_local':
                if machine:
                    raise ApiError('AUTOUNLOCK_BOUND', '请先解除已有自动解锁绑定，再选择其他方式')
                protector = LocalProtector(self.vault.root, instance)
                machine = protector.wrap(key.value)
                try:
                    if not secrets.compare_digest(protector.unwrap(machine), key.value):
                        raise ApiError('LOCAL_KEY_UNAVAILABLE', '本机自动解锁回环校验失败，保险库保持原状态')
                    self.vault.save(instance, row[0], key, data, enabled, machine)
                except Exception:
                    protector.remove(machine)
                    raise
            elif action == 'bind_tpm':
                if is_local(machine):
                    raise ApiError('AUTOUNLOCK_BOUND', '请先解除本机密钥绑定，再绑定 TPM')
                from module.runtime.account_tpm import TpmProtector
                if not TpmProtector.available():
                    raise ApiError('TPM_UNAVAILABLE', '未检测到可用 TPM，保险库未改变；可选择安全性较低的本机密钥自动解锁')
                protector = TpmProtector(self.vault.root, instance)
                failed = False
                try:
                    machine = protector.wrap(key.value)
                    failed = not secrets.compare_digest(protector.unwrap(machine), key.value)
                except Exception:
                    failed = True
                if failed:
                    key.clear()
                    self.vault.block_binding(instance)
            elif action == 'unbind_tpm':
                if is_local(machine):
                    raise ApiError('INVALID_PARAMS', '当前绑定的是本机密钥，请使用解除本机绑定')
                machine = None
            elif action == 'unbind_local':
                if not is_local(machine):
                    raise ApiError('INVALID_PARAMS', '当前实例未绑定本机密钥')
                old_machine = machine
                machine = None
                self.vault.save(instance, row[0], key, data, enabled, machine)
                try:
                    LocalProtector(self.vault.root, instance).remove(old_machine)
                except FileNotFoundError:
                    pass
                except Exception:
                    self.vault.forget(instance)
                    raise ApiError('LOCAL_KEY_CLEANUP_FAILED', '自动解锁绑定已解除，但项目外密钥未能清理，请检查用户目录权限') from None
            if action not in ('list', 'unlock', 'select', 'bind_local', 'unbind_local'):
                self.vault.save(instance, row[0], key, data, enabled, machine)
            self.vault.cache_key(instance, key)
            result = self.status_result(instance)
            if result['destroyed']:
                raise ApiError('VAULT_DESTROYED', '检测到旧版保险库禁用标记，账号信息不再返回')
            # 只有显式查看列表返回账号身份；不会返回 token、密码或数据库内容。
            if action == 'list':
                result.update(profiles=[{k: p[k] for k in ('id', 'label', 'users')} for p in data['profiles']],
                              selected=data['selected'])
            return result


@sensitive_operation
def prepare_worker(instance):
    """父进程启动前检查解锁与同设备冲突；与账号操作共享锁。

    Args:
        instance (str): 待启动的实例名称。

    Returns:
        Any: 启动所需密钥，未启用保险库时返回 None。

    Raises:
        ApiError: 同一设备已有运行实例时抛出 DEVICE_BUSY。
    """
    from module.api.config_service import ConfigService
    if not any((vault.root / 'config').glob('*/config.db')) and not any((vault.root / 'config').glob('*/account.destroyed')):
        return None
    configs = ConfigService()
    key = vault.startup_key(instance)
    # 已启用保险库的设备只能由一个实例操作，防止跨实例恢复覆盖。
    data, _ = configs.read(instance)
    serial = data.get('Alas', {}).get('Emulator', {}).get('Serial')
    for name in configs.names():
        if name == instance:
            continue
        other, _ = configs.read(name)
        if other.get('Alas', {}).get('Emulator', {}).get('Serial') != serial:
            continue
        if ProcessManager.is_running(name) and (key is not None or vault.status(name)['enabled']):
            raise ApiError('DEVICE_BUSY', '同一模拟器已有账号管理实例运行，请先停止')
    return key


@sensitive_operation
def restore_worker(instance, device=None):
    """在 worker 启动时将当前选中的账号恢复到设备。

    Args:
        instance (str): 实例名称。
        device (optional): 已建立连接的设备对象。默认为 None。
    """
    from module.api.config_service import ConfigService
    with OPERATIONS:
        if vault.startup_key(instance) is not None:
            vault.restore(instance, device_for(ConfigService(), instance, device=device))
