"""设备方法层通用工具。包含 ADB 错误处理、重试策略、序列号解析、
UI 层级解析（HierarchyButton）和 Shell 命令辅助函数。"""

import os
import random
import re
import socket
import time
import typing as t

import uiautomator2 as u2
import uiautomator2cache
from adbutils import AdbTimeout
from lxml import etree

from module.device.method.remove_warning import remove_shell_warning

try:
    # adbutils 0.x
    from adbutils import _AdbStreamConnection as AdbConnection
except ImportError:
    # adbutils >= 1.0
    from adbutils import AdbConnection
    # Patch list2cmdline back to subprocess.list2cmdline
    # We expect `screencap | nc 192.168.0.1 20298` instead of `screencap '|' nc 192.168.80.1 20298`
    import adbutils
    import subprocess

    adbutils._utils.list2cmdline = subprocess.list2cmdline
    adbutils._device.list2cmdline = subprocess.list2cmdline


    # BaseDevice.shell() is missing a check_okay() call before reading output,
    # resulting in an `OKAY` prefix in output.
    def shell(self,
              cmdargs: t.Union[str, list, tuple],
              stream: bool = False,
              timeout: t.Optional[float] = None,
              rstrip=True) -> t.Union[AdbConnection, str]:
        if isinstance(cmdargs, (list, tuple)):
            cmdargs = subprocess.list2cmdline(cmdargs)
        if stream:
            timeout = None
        c = self.open_transport(timeout=timeout)
        c.send_command("shell:" + cmdargs)
        c.check_okay()  # check_okay() is missing here
        if stream:
            return c
        output = c.read_until_close()
        return output.rstrip() if rstrip else output


    adbutils._device.BaseDevice.shell = shell

from module.base.decorator import cached_property
from module.base.runtime_params import RETRY_DELAY, RETRY_TRIES, IMAGE_TRUNCATED_THRESHOLD
from module.exception import EmulatorNotRunningError, RequestHumanTakeover
from module.logger import logger

# Track consecutive ImageTruncated counts per device serial
_image_truncated_counts: dict = {}

def report_image_truncated(serial: str) -> int:
    if serial is None:
        return 0
    cnt = _image_truncated_counts.get(serial, 0) + 1
    _image_truncated_counts[serial] = cnt
    return cnt

def reset_image_truncated(serial: str) -> None:
    if serial in _image_truncated_counts:
        del _image_truncated_counts[serial]

def handle_image_truncated(obj, exc: Exception) -> None:
    """
    Central handler for ImageTruncated: increment counter and try recovery when
    threshold reached. `obj` is expected to be a device/connection instance
    that may implement `droidcast_init`, `adb_reconnect`, `ascreencap_init`, etc.
    This function performs immediate recovery actions and resets the counter.
    """
    serial = getattr(obj, 'serial', None)
    cnt = report_image_truncated(serial)
    logger.error(f'图像截断发生 ({cnt}) for device {serial}: {exc}')

    if cnt >= IMAGE_TRUNCATED_THRESHOLD:
        logger.warning(f'[设备-工具] 图像截断达到阈值 ({IMAGE_TRUNCATED_THRESHOLD}) 对于 {serial}，尝试恢复')
        # Try specific recoveries in order of likelihood
        try:
            if hasattr(obj, 'droidcast_init'):
                logger.info('尝试重启DroidCast服务')
                try:
                    obj.droidcast_init()
                except (RequestHumanTakeover, EmulatorNotRunningError):
                    raise
                except Exception:
                    logger.exception('Failed to restart DroidCast')
            # Try ascreencap init if available
            if hasattr(obj, 'ascreencap_init'):
                try:
                    obj.ascreencap_init()
                except (RequestHumanTakeover, EmulatorNotRunningError):
                    raise
                except Exception:
                    logger.exception('Failed to init ascreencap')
            # Reconnect adb as a final attempt
            if hasattr(obj, 'adb_reconnect'):
                try:
                    obj.adb_reconnect()
                except (RequestHumanTakeover, EmulatorNotRunningError):
                    raise
                except Exception:
                    logger.exception('Failed to adb_reconnect')
        finally:
            reset_image_truncated(serial)

# Patch uiautomator2 appdir
u2.init.appdir = os.path.dirname(uiautomator2cache.__file__)

# Patch uiautomator2 logger
u2_logger = u2.logger
u2_logger.debug = logger.info
u2_logger.info = logger.info
u2_logger.warning = logger.warning
u2_logger.error = logger.error
u2_logger.critical = logger.critical


def setup_logger(*args, **kwargs):
    return u2_logger


u2.setup_logger = setup_logger
u2.init.setup_logger = setup_logger


# Patch Initer
class PatchedIniter(u2.init.Initer):
    @property
    def atx_agent_url(self):
        files = {
            'armeabi-v7a': 'atx-agent_{v}_linux_armv7.tar.gz',
            # 'arm64-v8a': 'atx-agent_{v}_linux_armv7.tar.gz',
            'arm64-v8a': 'atx-agent_{v}_linux_arm64.tar.gz',
            'armeabi': 'atx-agent_{v}_linux_armv6.tar.gz',
            'x86': 'atx-agent_{v}_linux_386.tar.gz',
            'x86_64': 'atx-agent_{v}_linux_386.tar.gz',
        }
        name = None
        for abi in self.abis:
            name = files.get(abi)
            if name:
                break
        if not name:
            raise Exception(
                "arch(%s) need to be supported yet, please report an issue in github"
                % self.abis)
        return u2.init.GITHUB_BASEURL + '/atx-agent/releases/download/%s/%s' % (
            u2.version.__atx_agent_version__, name.format(v=u2.version.__atx_agent_version__))

    @property
    def minicap_urls(self):
        return []


u2.init.Initer = PatchedIniter


def is_port_using(port_num):
    """检查本地端口是否已被占用。

    Args:
        port_num (int): 待检测的端口号。

    Returns:
        bool: 端口被占用返回 True，否则返回 False。
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(2)

    try:
        s.bind(('127.0.0.1', port_num))
        return False
    except OSError:
        # 地址已被绑定
        return True
    finally:
        s.close()


def random_port(port_range):
    """从指定的端口号范围内随机获取一个未占用的端口。

    Args:
        port_range (tuple[int, int]): 端口范围 (start, end)。

    Returns:
        int: 未被占用的可用端口号。
    """
    new_port = random.choice(list(range(*port_range)))
    if is_port_using(new_port):
        return random_port(port_range)
    else:
        return new_port


def recv_all(stream, chunk_size=4096, recv_interval=0.000) -> bytes:
    """从 Socket 或流中持续读取所有可用数据直至结束。

    Args:
        stream: 可读取数据的 Socket 或流对象。
        chunk_size (int): 每次读取的缓冲区大小（字节）。
        recv_interval (float): 每次读取后的休眠间隔（秒）。

    Returns:
        bytes: 聚合后的二进制数据。

    Raises:
        AdbTimeout: 读取超时。
    """
    if isinstance(stream, AdbConnection):
        stream = stream.conn
        stream.settimeout(10)
    else:
        stream.settimeout(10)

    try:
        fragments = []
        while 1:
            chunk = stream.recv(chunk_size)
            if chunk:
                fragments.append(chunk)
                # 参见 https://stackoverflow.com/questions/23837827/python-server-program-has-high-cpu-usage/41749820#41749820
                time.sleep(recv_interval)
            else:
                break
        return remove_shell_warning(b''.join(fragments))
    except socket.timeout:
        raise AdbTimeout('adb read timeout')


def possible_reasons(*args):
    """打印可能导致设备连接/操作失败的原因列表。

    Args:
        *args: 错误原因描述字符串。
    """
    for index, reason in enumerate(args):
        index += 1
        logger.critical(f'[设备-工具] 可能原因 #{index}: {reason}')


class PackageNotInstalled(Exception):
    """应用未安装异常。"""
    pass


class ImageTruncated(Exception):
    """截屏图像数据不完整/截断异常。"""
    pass


def retry_sleep(trial):
    """根据当前重试轮次计算休眠等待时间（秒）。

    Args:
        trial (int): 重试次数（从 0 开始）。

    Returns:
        int: 休眠等待秒数。
    """
    # 首次尝试
    if trial == 0:
        return 0
    # 失败一次，快速重试
    elif trial == 1:
        return 0
    # 失败两次
    elif trial == 2:
        return 1
    # 失败更多次，按标准间隔等待
    else:
        return RETRY_DELAY


def handle_adb_error(e):
    """根据 ADB 错误类型判断是否应该触发重试并输出对应的诊断信息。

    Args:
        e (Exception): 捕获到的异常实例。

    Returns:
        bool: 如果可以通过重连/重试恢复则返回 True，否则返回 False。
    """
    text = str(e)
    if 'not found' in text:
        # 当执行 `adb disconnect <serial>` 或 adb server 意外被杀时触发
        # AdbError(device '127.0.0.1:59865' not found)
        logger.error(e)
        return True
    elif 'timeout' in text:
        # AdbTimeout(adb read timeout)
        logger.error(e)
        return True
    elif 'closed' in text:
        # AdbError(closed)
        # 通常发生于 AdbTimeout 之后，断开并重连即可恢复
        logger.error(e)
        return True
    elif 'device offline' in text:
        # AdbError(device offline)
        # 无线连接的设备被动断开后不会从 adb 列表消失，而是显示为 offline
        # 网络波动断开恢复后或手机 VMOS 重启后，需要断开并重新连接
        logger.error(e)
        return True
    elif 'is offline' in text:
        # RuntimeError: USB device 127.0.0.1:7555 is offline
        # 当当前 ADB 服务被另一个版本的 ADB 抢占关闭时由 uiautomator2 抛出
        logger.error(e)
        return True
    elif text == 'rest':
        # AdbError(rest)
        # 服务端响应表明 adbd 服务已重置，客户端应重新建立连接
        logger.error(e)
        return True
    elif text == '':
        # AdbError('')
        # 空错误消息，通常是 ADB 连接被模拟器意外关闭（如网络弹窗导致 atx-agent 崩溃）
        # 断开重连通常可以修复
        logger.error(e)
        return True
    else:
        # 未知 AdbError
        logger.exception(e)
        possible_reasons(
            '如果使用 BlueStacks、雷电模拟器或 WSA，请在模拟器设置中启用 ADB',
            '模拟器已崩溃，请重启模拟器',
            '序列号错误，设备不存在或模拟器未运行'
        )
        return False


def handle_unknown_host_service(e):
    """处理 unknown host service 错误（通常由不同版本 ADB 相互抢占引发）。

    Args:
        e (Exception): 捕获到的异常实例。

    Returns:
        bool: 是否应触发重试。
    """
    text = str(e)
    if 'unknown host service' in text:
        # 启动了另一个版本的 ADB 服务，导致当前 ADB 服务被终止
        # 常见于启动了自带古老版本 ADB 的国产模拟器
        logger.error(e)
        return True
    else:
        return False


def get_serial_pair(serial):
    """将序列号解析为 (port_serial, emulator_serial) 对。

    Args:
        serial (str): 原始序列号字符串。

    Returns:
        tuple[str | None, str | None]: `127.0.0.1:5555+{X}` 和 `emulator-5554+{X}` 二元组 (0 <= X <= 64)。
    """
    if serial.startswith('127.0.0.1:'):
        try:
            port = int(serial[10:])
            if 5555 <= port <= 5555 + 64:
                return f'127.0.0.1:{port}', f'emulator-{port - 1}'
        except (ValueError, IndexError):
            pass
    if serial.startswith('emulator-'):
        try:
            port = int(serial[9:])
            if 5554 <= port <= 5554 + 64:
                return f'127.0.0.1:{port + 1}', f'emulator-{port}'
        except (ValueError, IndexError):
            pass

    return None, None


@t.overload
def removeprefix(s: str, prefix: str) -> str: ...


@t.overload
def removeprefix(s: bytes, prefix: bytes) -> bytes: ...


@t.overload
def removesuffix(s: str, suffix: str) -> str: ...


@t.overload
def removesuffix(s: bytes, suffix: bytes) -> bytes: ...


def removeprefix(s, prefix):
    """移除字符串或字节串的前缀（兼容 Python 3.9 之前版本）。

    Args:
        s (str | bytes): 目标字符串或字节串。
        prefix (str | bytes): 待移除的前缀。

    Returns:
        str | bytes: 移除前缀后的结果。
    """
    if s.startswith(prefix):
        return s[len(prefix):]
    return s


def removesuffix(s, suffix):
    """移除字符串或字节串的后缀（兼容 Python 3.9 之前版本）。

    Args:
        s (str | bytes): 目标字符串或字节串。
        suffix (str | bytes): 待移除的后缀。

    Returns:
        str | bytes: 移除后缀后的结果。
    """
    # suffix 为空时 s[:-0] 会导致空字符串，故需特别判断
    if suffix and s.endswith(suffix):
        return s[:-len(suffix)]
    return s


class IniterNoMinicap(u2.init.Initer):
    """禁止在模拟器上安装 minicap 的 Initer。"""

    @property
    def minicap_urls(self):
        """返回空 URL 列表，禁止在模拟器上下载安装 minicap。"""
        return []


class Device(u2.Device):
    """继承 u2.Device，覆写悬浮窗等行为。"""

    def show_float_window(self, show=True):
        """禁止弹出悬浮窗。"""
        pass


# 猴子补丁
u2.init.Initer = IniterNoMinicap
u2.Device = Device


class HierarchyButton:
    """将 UI 层级结构转换为类似 Alas 中 Button 的对象。"""
    _name_regex = re.compile('@.*?=[\'\"](.*?)[\'\"]')

    def __init__(self, hierarchy: etree._Element, xpath: str):
        """初始化层级按钮。

        Args:
            hierarchy (etree._Element): XML UI 树根节点。
            xpath (str): 目标节点的 XPath 表达式。
        """
        self.hierarchy = hierarchy
        self.xpath = xpath
        self.nodes = hierarchy.xpath(xpath)

    @cached_property
    def name(self):
        res = HierarchyButton._name_regex.findall(self.xpath)
        if res:
            return res[0]
        else:
            return self.xpath

    @cached_property
    def count(self):
        return len(self.nodes)

    @cached_property
    def exist(self):
        return self.count == 1

    @cached_property
    def attrib(self):
        if self.exist:
            return self.nodes[0].attrib
        else:
            return {}

    @cached_property
    def area(self):
        if self.exist:
            bounds = self.attrib.get("bounds")
            lx, ly, rx, ry = map(int, re.findall(r"\d+", bounds))
            return lx, ly, rx, ry
        else:
            return None

    @cached_property
    def size(self):
        if self.area is not None:
            lx, ly, rx, ry = self.area
            return rx - lx, ry - ly
        else:
            return None

    @cached_property
    def button(self):
        return self.area

    def __bool__(self):
        return self.exist

    def __str__(self):
        return self.name

    """
    Element props
    """

    def _get_bool_prop(self, prop: str) -> bool:
        return self.attrib.get(prop, "").lower() == 'true'

    @cached_property
    def index(self) -> int:
        try:
            return int(self.attrib.get("index", 0))
        except IndexError:
            return 0

    @cached_property
    def text(self) -> str:
        return self.attrib.get("text", "").strip()

    @cached_property
    def resourceId(self) -> str:
        return self.attrib.get("resourceId", "").strip()

    @cached_property
    def package(self) -> str:
        return self.attrib.get("resourceId", "").strip()

    @cached_property
    def description(self) -> str:
        return self.attrib.get("resourceId", "").strip()

    @cached_property
    def checkable(self) -> bool:
        return self._get_bool_prop('checkable')

    @cached_property
    def clickable(self) -> bool:
        return self._get_bool_prop('clickable')

    @cached_property
    def enabled(self) -> bool:
        return self._get_bool_prop('enabled')

    @cached_property
    def fucusable(self) -> bool:
        return self._get_bool_prop('fucusable')

    @cached_property
    def focused(self) -> bool:
        return self._get_bool_prop('focused')

    @cached_property
    def scrollable(self) -> bool:
        return self._get_bool_prop('scrollable')

    @cached_property
    def longClickable(self) -> bool:
        return self._get_bool_prop('longClickable')

    @cached_property
    def password(self) -> bool:
        return self._get_bool_prop('password')

    @cached_property
    def selected(self) -> bool:
        return self._get_bool_prop('selected')
