"""设备连接属性与 ADB 路径解析模块。

提供 ConnectionAttr 类，负责：
- 查找和下载适配平台的 ADB 可执行文件
- 规范化和校验设备序列号
- 识别模拟器类型（MuMu、LDPlayer、BlueStacks、Nox、WSA 等）
- 初始化并缓存 ADB 和 uiautomator2 客户端
"""

import os
import re
import shutil
import stat
import sys
import urllib.request
import zipfile
from pathlib import Path

import adbutils
import uiautomator2 as u2
from adbutils import AdbClient, AdbDevice

from module.base.decorator import cached_property
from module.config.config import AzurLaneConfig
from module.config.env import IS_ON_PHONE_CLOUD
from module.config.deep import deep_iter
from module.device.method.utils import get_serial_pair
from module.exception import RequestHumanTakeover
from module.logger import logger


def platform_tools_url():
    """返回当前平台对应的 Android platform-tools 下载地址。

    Returns:
        str | None: 对应的 zip 下载链接，不支持的平台返回 None。
    """
    if sys.platform == 'win32':
        return 'https://dl.google.com/android/repository/platform-tools-latest-windows.zip'
    if sys.platform == 'darwin':
        return 'https://dl.google.com/android/repository/platform-tools-latest-darwin.zip'
    if sys.platform.startswith('linux'):
        return 'https://dl.google.com/android/repository/platform-tools-latest-linux.zip'
    return None


class ConnectionAttr:
    """设备连接属性与客户端管理类。

    解析配置中的模拟器/设备序列号，确定连接类型，管理 ADB 与 uiautomator2 客户端的初始化。
    """
    config: AzurLaneConfig
    serial: str

    adb_binary_list = [
        './.venv/Scripts/adb.exe',
        './.venv/bin/adb',
        './bin/adb/adb.exe',
        '/usr/bin/adb'
    ]

    def download_adb_binary(self, target):
        """下载官方 Android platform-tools，并把 adb 放到目标路径。

        Args:
            target (str): 期望的 adb 可执行文件路径，通常是 .venv/bin/adb。

        Returns:
            str | None: 安装成功后的 adb 绝对路径。
        """
        url = platform_tools_url()
        if url is None:
            logger.warning(f'[设备] 当前平台不支持自动下载 ADB: {sys.platform}')
            return None

        if not target:
            logger.warning('[设备] ADB 下载失败，目标路径为空')
            return None

        target = Path(target).resolve()
        download_dir = target.parent
        if target.parent.name in ['Scripts', 'bin'] and target.parent.parent.name == '.venv':
            download_dir = target.parent.parent
        tools_dir = download_dir / 'platform-tools'
        archive = download_dir / 'platform-tools.zip'
        executable = 'adb.exe' if os.name == 'nt' else 'adb'
        source = tools_dir / executable

        logger.hr('下载ADB', level=2)
        logger.warning(f'[设备] 未找到 ADB，正在下载 Android platform-tools: {url}')
        tools_dir.parent.mkdir(parents=True, exist_ok=True)
        try:
            urllib.request.urlretrieve(url, archive)
        except Exception as e:
            archive.unlink(missing_ok=True)
            logger.warning(f'[设备] ADB 下载失败: {e}')
            return None

        if tools_dir.exists():
            shutil.rmtree(tools_dir)
        try:
            with zipfile.ZipFile(archive, 'r') as z:
                z.extractall(tools_dir.parent)
        finally:
            archive.unlink(missing_ok=True)

        if not source.exists():
            logger.warning(f'[设备] ADB 下载失败，未找到 {source}')
            return None

        if os.name != 'nt':
            source.chmod(source.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() or target.is_symlink():
            target.unlink()
        shutil.copy2(source, target)
        if os.name == 'nt':
            for dll in tools_dir.glob('*.dll'):
                shutil.copy2(dll, target.parent / dll.name)
        else:
            target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

        logger.info(f'[设备] ADB 已安装: {target}')
        return str(target).replace('\\\\', '/').replace('\\', '/')

    def __init__(self, config):
        """初始化设备连接属性。

        Args:
            config (AzurLaneConfig | str): ./config 下的用户配置名或 AzurLaneConfig 实例。
        """
        logger.hr('设备', level=1)
        if isinstance(config, str):
            self.config = AzurLaneConfig(config, task=None)
        else:
            self.config = config

        logger.attr('是否云手机', IS_ON_PHONE_CLOUD)

        if self.config.Emulator_Serial == 'azurpilot_android':
            self.serial = 'azurpilot_android'
            self.config.DEVICE_OVER_HTTP = False
            return

        # 初始化 adb 客户端
        logger.attr('ADB路径', self.adb_binary)
        # Monkey patch 自定义 adb
        adbutils.adb_path = lambda: self.adb_binary
        # 移除全局代理设置，避免 uiautomator2 请求走代理
        d = dict(**os.environ)
        d.update(self.config.args)
        for k, _ in deep_iter(d, depth=1):
            if 'proxy' in k[0].split('_')[-1].lower():
                del os.environ[k[0]]
        # 缓存 adb_client
        _ = self.adb_client

        # 解析自定义序列号
        self.serial = str(self.config.Emulator_Serial)
        self.serial_check()
        self.config.DEVICE_OVER_HTTP = self.is_over_http

    @staticmethod
    def revise_serial(serial: str):
        """修正手动输入的序列号常见拼写错误。

        Args:
            serial (str): 原始序列号字符串。

        Returns:
            str: 修正后的序列号。
        """
        serial = serial.strip().replace(' ', '')
        # 127。0。0。1：5555
        serial = serial.replace('。', '.').replace('，', '.').replace(',', '.').replace('：', ':')
        # 127.0.0.1.5555
        serial = serial.replace('127.0.0.1.', '127.0.0.1:')
        # 5555,16384 (实际上为 "5555.16384"，因为替换了逗号)
        if '.' in serial:
            left, _, right = serial.partition('.')
            try:
                left = int(left)
                right = int(right)
                if 5500 < left < 6000 and 16300 < right < 20000:
                    serial = str(right)
            except ValueError:
                pass
        # 16384
        if serial.isdigit():
            try:
                port = int(serial)
                if 1000 < port < 65536:
                    serial = f'127.0.0.1:{port}'
            except ValueError:
                pass
        # 夜神模拟器 127.0.0.1:62001
        # MuMu模拟器12127.0.0.1:16384
        if '模拟' in serial:
            import re
            res = re.search(r'(127\.\d+\.\d+\.\d+:\d+)', serial)
            if res:
                serial = res.group(1)
        # 12127.0.0.1:16384
        serial = serial.replace('12127.0.0.1', '127.0.0.1')
        # auto127.0.0.1:16384
        serial = serial.replace('auto127.0.0.1', '127.0.0.1').replace('autoemulator', 'emulator')
        return str(serial)

    def serial_check(self):
        """检查并规范化序列号，校验 WSA 及 HTTP 模式下的配置合法性。

        Raises:
            RequestHumanTakeover: 当序列号格式异常或 HTTP 模式下配置了不支持的截图/控制方法时抛出。
        """
        # 容错处理
        new = self.revise_serial(self.serial)
        if new != self.serial:
            logger.warning(f'[设备-属性] 序列号 "{self.config.Emulator_Serial}" 已修正为 "{new}"')
            self.config.Emulator_Serial = new
            self.serial = new
        if self.is_bluestacks4_hyperv:
            self.serial = self.find_bluestacks4_hyperv(self.serial)
        if self.is_bluestacks5_hyperv:
            self.serial = self.find_bluestacks5_hyperv(self.serial)
        if "127.0.0.1:58526" in self.serial:
            logger.warning('[设备-属性] 序列号 127.0.0.1:58526 疑似 WSA 设备，'
                           '请改用 "wsa-0" 或其他格式')
            raise RequestHumanTakeover
        if self.is_wsa:
            self.serial = '127.0.0.1:58526'
            if self.config.Emulator_ScreenshotMethod != 'uiautomator2' \
                    or self.config.Emulator_ControlMethod != 'uiautomator2':
                with self.config.multi_set():
                    self.config.Emulator_ScreenshotMethod = 'uiautomator2'
                    self.config.Emulator_ControlMethod = 'uiautomator2'
        if self.is_over_http:
            if self.config.Emulator_ScreenshotMethod not in ["ADB", "uiautomator2", "aScreenCap"] \
                    or self.config.Emulator_ControlMethod not in ["ADB", "uiautomator2", "minitouch"]:
                logger.warning(
                    f'通过 HTTP 连接设备: {self.serial} 时，'
                    f'ScreenshotMethod 仅支持 ["ADB", "uiautomator2", "aScreenCap"], '
                    f'ControlMethod 仅支持 ["ADB", "uiautomator2", "minitouch"]'
                )
                raise RequestHumanTakeover

    @cached_property
    def is_bluestacks4_hyperv(self):
        return "bluestacks4-hyperv" in self.serial

    @cached_property
    def is_bluestacks5_hyperv(self):
        return "bluestacks5-hyperv" in self.serial

    @cached_property
    def is_bluestacks_hyperv(self):
        return self.is_bluestacks4_hyperv or self.is_bluestacks5_hyperv

    @cached_property
    def is_wsa(self):
        return bool(re.match(r'^wsa', self.serial))

    @cached_property
    def port(self) -> int:
        port_serial, _ = get_serial_pair(self.serial)
        if port_serial is None:
            port_serial = self.serial
        try:
            return int(port_serial.split(':')[1])
        except (IndexError, ValueError):
            return 0

    @cached_property
    def is_mumu12_family(self):
        # 127.0.0.1:16384 + 32*n，假定最多 32 个多开实例
        return 16384 <= self.port <= 17408

    @cached_property
    def is_mumu_family(self):
        # 127.0.0.1:7555
        # 127.0.0.1:16384 + 32*n
        return self.serial == '127.0.0.1:7555' or self.is_mumu12_family

    @cached_property
    def is_ldplayer_bluestacks_family(self):
        # 注意 LDPlayer 和 BlueStacks 使用相同的序列号端口范围
        # 127.0.0.1:5555 + 2*n，假定最多 32 个多开实例
        return self.serial.startswith('emulator-') or 5555 <= self.port <= 5619

    @cached_property
    def is_nox_family(self):
        return 62001 <= self.port <= 63025

    @cached_property
    def is_vmos(self):
        return 5667 <= self.port <= 5699

    @cached_property
    def is_emulator(self):
        return self.serial.startswith('emulator-') or self.serial.startswith('127.0.0.1:')

    @cached_property
    def is_network_device(self):
        return bool(re.match(r'\d+\.\d+\.\d+\.\d+:\d+', self.serial))

    @cached_property
    def is_local_network_device(self):
        return bool(re.match(r'192\.168\.\d+\.\d+:\d+', self.serial))

    @cached_property
    def is_over_http(self):
        return bool(re.match(r"^https?://", self.serial))

    @cached_property
    def is_chinac_phone_cloud(self):
        # 带公网 ADB 连接的云手机
        # 序列号格式形如 xxx.xxx.xxx.xxx:301
        return bool(re.search(r":30[0-9]$", self.serial))

    @staticmethod
    def find_bluestacks4_hyperv(serial):
        """
        Find dynamic serial of BlueStacks4 Hyper-V Beta.

        Args:
            serial (str): 'bluestacks4-hyperv', 'bluestacks4-hyperv-2' for multi instance, and so on.

        Returns:
            str: 127.0.0.1:{port}
        """
        from winreg import HKEY_LOCAL_MACHINE, OpenKey, QueryValueEx

        logger.info("使用蓝叠4 Hyper-V测试版")
        logger.info("读取实时ADB端口")

        if serial == "bluestacks4-hyperv":
            folder_name = "Android"
        else:
            folder_name = f"Android_{serial[19:]}"

        try:
            with OpenKey(HKEY_LOCAL_MACHINE,
                         rf"SOFTWARE\BlueStacks_bgp64_hyperv\Guests\{folder_name}\Config") as key:
                port = QueryValueEx(key, "BstAdbPort")[0]
        except FileNotFoundError:
            logger.error(
                rf'[设备-蓝叠] 无法找到注册表 HKEY_LOCAL_MACHINE\SOFTWARE\BlueStacks_bgp64_hyperv\Guests\{folder_name}\Config')
            logger.error('[设备-蓝叠] 请确认您使用的是BlueStack 4 hyper-v而不是普通BlueStacks 4')
            logger.error(r'[设备-蓝叠] 请检查注册表 HKEY_LOCAL_MACHINE\SOFTWARE\BlueStacks_bgp64_hyperv\Guests 下是否有其他模拟器实例')
            raise RequestHumanTakeover
        logger.info(f"新ADB端口: {port}")
        return f"127.0.0.1:{port}"

    @staticmethod
    def find_bluestacks5_hyperv(serial):
        """
        Find dynamic serial of BlueStacks5 Hyper-V.

        Args:
            serial (str): 'bluestacks5-hyperv', 'bluestacks5-hyperv-1' for multi instance, and so on.

        Returns:
            str: 127.0.0.1:{port}
        """
        from winreg import HKEY_LOCAL_MACHINE, OpenKey, QueryValueEx

        logger.info("使用蓝叠5 Hyper-V")
        logger.info("读取实时ADB端口")

        if serial == "bluestacks5-hyperv":
            parameter_name = r"bst\.instance\.(Nougat64|Pie64|Rvc64)\.status\.adb_port"
        else:
            parameter_name = rf"bst\.instance\.(Nougat64|Pie64|Rvc64)_{serial[19:]}\.status.adb_port"

        try:
            with OpenKey(HKEY_LOCAL_MACHINE, r"SOFTWARE\BlueStacks_nxt") as key:
                directory = QueryValueEx(key, 'UserDefinedDir')[0]
        except FileNotFoundError:
            try:
                with OpenKey(HKEY_LOCAL_MACHINE, r"SOFTWARE\BlueStacks_nxt_cn") as key:
                    directory = QueryValueEx(key, 'UserDefinedDir')[0]
            except FileNotFoundError:
                logger.error(r'[设备-属性] 未找到注册表 HKEY_LOCAL_MACHINE\SOFTWARE\BlueStacks_nxt '
                             r'或 HKEY_LOCAL_MACHINE\SOFTWARE\BlueStacks_nxt_cn')
                logger.error('[设备-属性] 请确认使用的是蓝叠 5 Hyper-V 版本，而非普通蓝叠 5')
                raise RequestHumanTakeover
        logger.info(f"配置文件目录: {directory}")

        with open(os.path.join(directory, 'bluestacks.conf'), encoding='utf-8') as f:
            content = f.read()
        port = re.search(rf'{parameter_name}="(\d+)"', content)
        if port is None:
            logger.warning(f"未匹配结果: {serial}.")
            raise RequestHumanTakeover
        port = port.group(2)
        logger.info(f"匹配到动态端口: {port}")
        return f"127.0.0.1:{port}"

    @cached_property
    def adb_binary(self):
        """
        获取 ADB 可执行文件路径。

        检查顺序：
        1. deploy.yaml 配置的路径（绝对路径）
        2. 预定义的候选路径列表
        3. Python 环境中的 adb
        4. 系统 PATH 中的 adb
        5. 自动下载到配置路径

        Returns:
            str: ADB 可执行文件的绝对路径。
        """
        from module.runtime.setting import State

        # 统一使用绝对路径检查，避免相对路径导致的 CWD 问题
        # deploy.yaml 中的路径是相对于项目根目录的
        deploy_adb = State.deploy_config.AdbExecutable
        root = State.deploy_config.root_filepath
        deploy_adb_file = os.path.abspath(os.path.join(root, deploy_adb)).replace('\\', '/')
        if os.path.exists(deploy_adb_file):
            return deploy_adb_file

        # Try existing adb.exe in predefined list
        for candidate in self.adb_binary_list:
            if os.path.exists(candidate):
                return os.path.abspath(candidate).replace('\\', '/')

        # Try adb in python environment
        import sys
        if os.name == 'nt':
            file = os.path.join(sys.executable, '../adb.exe')
        else:
            file = os.path.join(sys.executable, '../adb')
        file = os.path.abspath(file).replace('\\', '/')
        if os.path.exists(file):
            return file

        # Use adb in system PATH
        path_adb = shutil.which('adb')
        if path_adb:
            return os.path.abspath(path_adb).replace('\\', '/')

        # Download adb only when all local candidates are missing
        # 使用绝对路径下载，确保后续实例能找到文件
        downloaded = self.download_adb_binary(deploy_adb_file)
        if downloaded:
            return downloaded

        return 'adb'

    @cached_property
    def adb_client(self) -> AdbClient:
        host = '127.0.0.1'
        port = 5037

        # Trying to get adb port from env
        env = os.environ.get('ANDROID_ADB_SERVER_PORT', None)
        if env is not None:
            try:
                port = int(env)
            except ValueError:
                logger.warning(f'无效的环境变量 ANDROID_ADB_SERVER_PORT={port}, 使用默认端口')

        logger.attr('ADB客户端', f'AdbClient({host}, {port})')
        return AdbClient(host, port)

    @cached_property
    def adb(self) -> AdbDevice:
        """获取 ADB 设备实例。

        Returns:
            AdbDevice: 通过 ADB 客户端和序列号绑定的设备对象。
        """
        return AdbDevice(self.adb_client, self.serial)

    @cached_property
    def u2(self) -> u2.Device:
        """获取 uiautomator2 设备实例。

        根据连接类型选择不同的连接方式：
        - HTTP 设备使用 u2.connect()
        - 本地模拟器（emulator- 或 127.0.0.1:）使用 u2.connect_usb()
        - 其他设备使用 u2.connect()

        设置命令超时为 7 天（604800 秒）以保持长连接。

        Returns:
            u2.Device: uiautomator2 设备对象。
        """
        if self.is_over_http:
            # Using uiautomator2_http
            device = u2.connect(self.serial)
        else:
            # Normal uiautomator2
            if self.serial.startswith('emulator-') or self.serial.startswith('127.0.0.1:'):
                device = u2.connect_usb(self.serial)
            else:
                device = u2.connect(self.serial)

        # Stay alive
        # best-effort：keepalive 只是提示而非必需。atx-agent 刚被重启/瞬时抖动时
        # 首次 POST 可能失败（RemoteDisconnected），此时若抛出会阻断整个 u2 客户端
        # 建立并反复重建连接放大竞态窗口，故失败仅告警忽略。
        # 真实的连接问题会在后续实际操作中经 uiautomator_2 的 @retry 恢复。
        try:
            device.set_new_command_timeout(604800)
        except Exception as e:
            logger.warning(f'[设备-u2] 设置命令超时失败，忽略（keepalive 非必需）: {e}')

        logger.attr('u2.Device', f'Device(atx_agent_url={device._get_atx_agent_url()})')
        return device
