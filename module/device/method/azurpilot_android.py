"""AzurPilot Android 虚拟屏设备后端，经本机特权桥执行设备 I/O。

代理（spike/m0/agent/main.py）在手机上监听 127.0.0.1:22301，协议为行分隔 JSON + 二进制帧：
    ping/screencap/click/swipe/shell，详见代理源文件 docstring。

启用方式：Emulator_Serial 以 "azurpilot_android" 开头（默认 serial 即 "azurpilot_android"），
截图/控制方法选择 "azurpilot_android"。本模块不 import 任何 adb/u2 依赖。

注意：
- Android 桥输出 BGR，AzurPilot 的截图管线使用 RGB，客户端负责交换红蓝通道。
- 游戏必须跑在 MaaFwApp 的虚拟屏上：app_start_azurpilot_android 用 `am start --display <VID>`，
  VID 由代理侧 shell 探测（dumpsys display 找 VIRTUAL displayId），每轮进程缓存一次。
- get_orientation 对桥接固定返回 0（虚拟屏始终横屏 1280x720）。
- dump_hierarchy 不可用：uiautomator 只反映物理屏，不能用于虚拟屏。
"""
import json
import re
import shlex
import socket
import threading
import time

import numpy as np

from module.base.decorator import cached_property
from module.exception import RequestHumanTakeover, ScriptError
from module.logger import logger

AZURPILOT_ANDROID_DEFAULT_ADDR = '127.0.0.1:22301'


class AzurPilotAndroidBridgeError(Exception):
    """AzurPilot Android 特权桥通信异常。"""
    pass


class AzurPilotAndroid:
    _azurpilot_android_sock = None
    _azurpilot_android_req_id = 0
    _azurpilot_android_lock = threading.RLock()

    # ---------------------------------------------------------------- 协议层

    @cached_property
    def azurpilot_android_addr(self) -> str:
        import os
        return os.environ.get('AZURPILOT_ANDROID_PROXY_ADDR', AZURPILOT_ANDROID_DEFAULT_ADDR)

    def _azurpilot_android_connect(self) -> socket.socket:
        """建立到 AzurPilot Android 代理服务的套接字连接。

        Returns:
            socket.socket: 已连接的套接字对象。
        """
        host, _, port = self.azurpilot_android_addr.partition(':')
        sock = socket.create_connection((host, int(port)), timeout=10)
        sock.settimeout(60)
        return sock

    def _azurpilot_android_call(self, payload: dict, frame: bytes = None) -> dict:
        """发送一条请求（可随附一帧二进制），返回响应字典。

        连接错误时自动重连并重试一次。

        Args:
            payload: JSON 请求体字典。
            frame: 随附的二进制数据帧，默认为 None。

        Returns:
            dict: 代理返回的响应字典。
        """
        with self._azurpilot_android_lock:
            return self._azurpilot_android_call_locked(payload, frame)

    def _azurpilot_android_call_locked(self, payload: dict, frame: bytes = None) -> dict:
        """在互斥锁保护下执行代理请求调用。

        Args:
            payload: JSON 请求体字典。
            frame: 随附的二进制数据帧。

        Returns:
            dict: 代理返回的响应字典。

        Raises:
            RequestHumanTakeover: 代理服务不可达或通信严重异常。
        """
        AzurPilotAndroid._azurpilot_android_req_id += 1
        payload = dict(payload)
        payload['id'] = AzurPilotAndroid._azurpilot_android_req_id

        last_error = None
        for _ in range(2):
            try:
                sock = AzurPilotAndroid._azurpilot_android_sock
                if sock is None:
                    sock = AzurPilotAndroid._azurpilot_android_sock = self._azurpilot_android_connect()
                sock.sendall(json.dumps(payload, separators=(',', ':')).encode('utf-8') + b'\n')
                if frame is not None:
                    sock.sendall(frame)
                # 逐字节读响应行：screencap 响应行后紧跟像素帧，大块读会吞帧
                buf = b''
                while not buf.endswith(b'\n'):
                    data = sock.recv(1)
                    if not data:
                        raise AzurPilotAndroidBridgeError('proxy closed connection')
                    buf += data
                    if len(buf) > 256 * 1024:
                        raise AzurPilotAndroidBridgeError('response line too long')
                return json.loads(buf.decode('utf-8'))
            except (OSError, AzurPilotAndroidBridgeError, json.JSONDecodeError) as e:
                last_error = e
                logger.warning(f'AzurPilotAndroid 代理异常: {e}，正在重连')
                try:
                    if AzurPilotAndroid._azurpilot_android_sock is not None:
                        AzurPilotAndroid._azurpilot_android_sock.close()
                except OSError:
                    pass
                AzurPilotAndroid._azurpilot_android_sock = None
        logger.critical(f'AzurPilotAndroid 代理不可达: {last_error}')
        raise RequestHumanTakeover

    def _azurpilot_android_call_ok(self, payload: dict, frame: bytes = None) -> dict:
        """发送请求并验证响应状态 ok 为 True。

        Args:
            payload: JSON 请求体字典。
            frame: 随附的二进制数据帧。

        Returns:
            dict: 响应字典。

        Raises:
            ScriptError: 代理返回执行失败。
        """
        resp = self._azurpilot_android_call(payload, frame)
        if not resp.get('ok'):
            raise ScriptError(f'AzurPilotAndroid proxy error: {resp.get("error", "unknown")}')
        return resp

    def _azurpilot_android_read_exact(self, n: int) -> bytes:
        """从套接字中精确读取指定字节数。

        Args:
            n: 需要读取的字节数。

        Returns:
            bytes: 读取到的完整字节数据。

        Raises:
            AzurPilotAndroidBridgeError: 数据传输过程中连接意外关闭。
        """
        sock = AzurPilotAndroid._azurpilot_android_sock
        chunks = []
        while n > 0:
            data = sock.recv(min(1048576, n))
            if not data:
                raise AzurPilotAndroidBridgeError('connection closed mid-frame')
            chunks.append(data)
            n -= len(data)
        return b''.join(chunks)

    # ---------------------------------------------------------------- 截图 / 触控

    def screenshot_azurpilot_android(self) -> np.ndarray:
        """通过 AzurPilot Android 代理截取虚拟屏屏幕图像。

        Returns:
            np.ndarray: RGB 格式的屏幕截图数组。
        """
        with self._azurpilot_android_lock:
            resp = self._azurpilot_android_call_ok({'method': 'screencap'})
            try:
                raw = self._azurpilot_android_read_exact(int(resp['length']))
            except (OSError, AzurPilotAndroidBridgeError):
                sock = AzurPilotAndroid._azurpilot_android_sock
                AzurPilotAndroid._azurpilot_android_sock = None
                if sock is not None:
                    sock.close()
                raise
        image = np.frombuffer(raw, dtype=np.uint8).reshape(
            int(resp['height']), int(resp['width']), int(resp['channels']))
        # 桥原始帧为 BGR(A)，AzurPilot 全局截图约定为 RGB。
        # 直接保留前三通道会让预览和模板识别的红蓝通道互换。
        if image.shape[2] >= 3:
            image = image[..., 2::-1]
        return np.ascontiguousarray(image)

    def click_azurpilot_android(self, x, y):
        """通过 AzurPilot Android 代理点击指定坐标。

        Args:
            x (int): 目标 X 坐标。
            y (int): 目标 Y 坐标。
        """
        self._azurpilot_android_call_ok({'method': 'click', 'x': int(x), 'y': int(y)})

    def long_click_azurpilot_android(self, x, y, duration):
        """通过 AzurPilot Android 代理在指定坐标执行长按（原地滑动）。

        Args:
            x (int): 目标 X 坐标。
            y (int): 目标 Y 坐标。
            duration (float): 长按持续时间（秒）。
        """
        # 等效长按：原地滑动，duration 单位为秒（ALAS 约定），代理侧为毫秒
        self._azurpilot_android_call_ok({
            'method': 'swipe',
            'x1': int(x), 'y1': int(y), 'x2': int(x), 'y2': int(y),
            'duration': int(duration * 1000),
        })

    def swipe_azurpilot_android(self, p1, p2, duration=0.1):
        """通过 AzurPilot Android 代理执行两点间滑动。

        Args:
            p1 (tuple[int, int]): 起始坐标 (x, y)。
            p2 (tuple[int, int]): 终点坐标 (x, y)。
            duration (float): 滑动持续时间（秒）。
        """
        self._azurpilot_android_call_ok({
            'method': 'swipe',
            'x1': int(p1[0]), 'y1': int(p1[1]),
            'x2': int(p2[0]), 'y2': int(p2[1]),
            'duration': int(duration * 1000),
        })

    # ---------------------------------------------------------------- shell 通道

    def azurpilot_android_shell(self, cmd: str, timeout: float = 30) -> dict:
        """经代理以 shell 权限执行系统命令。

        Args:
            cmd: 待执行的 shell 命令字符串。
            timeout: 命令超时时间（秒）。

        Returns:
            dict: 包含 ok、code、stdout、stderr 的执行结果字典。
        """
        return self._azurpilot_android_call({'method': 'shell', 'cmd': cmd, 'timeout': timeout})

    def azurpilot_android_shell_output(self, cmd: str, timeout: float = 30) -> str:
        """经代理执行 shell 命令并返回标准输出。

        Args:
            cmd: 待执行的 shell 命令字符串。
            timeout: 命令超时时间（秒）。

        Returns:
            str: 命令的标准输出内容。

        Raises:
            ScriptError: 命令执行失败。
        """
        resp = self.azurpilot_android_shell(cmd, timeout)
        if not resp.get('ok'):
            raise ScriptError(f'AzurPilotAndroid shell failed: {cmd!r}: {resp.get("stderr", "")[:200]}')
        return resp.get('stdout', '')

    @property
    def azurpilot_android_display_id(self) -> int:
        """获取当前虚拟屏的 displayId。

        Returns:
            int: 虚拟显示器的 displayId。

        Raises:
            ScriptError: 虚拟屏尚未就绪或返回值非法。
        """
        response = self._azurpilot_android_call_ok({'method': 'ping'})
        display_id = response.get('displayId')
        if not isinstance(display_id, int) or display_id < 1:
            raise ScriptError(f'AzurPilot Android 虚拟屏尚未就绪: {display_id!r}')
        logger.attr('AzurPilotAndroid', f'virtual display id={display_id}')
        return display_id

    # ---------------------------------------------------------------- App 控制

    def app_start_azurpilot_android(self, package=None, activity=None, wait=True):
        """在虚拟屏上启动指定应用 Activity。

        Args:
            package: 应用包名，默认为当前配置包名。
            activity: 目标 Activity 名称，默认为映射表中的默认入口。
            wait: 启动后是否休眠 1 秒等待生效。

        Raises:
            ScriptError: 未知应用包名对应的 Activity。
        """
        from module.config.server import DICT_PACKAGE_TO_ACTIVITY
        package = package or self.package
        if activity is None:
            activity = DICT_PACKAGE_TO_ACTIVITY.get(package)
            if activity is None:
                raise ScriptError(f'No known activity for package: {package}')
        self.azurpilot_android_shell_output(
            f'am start --display {self.azurpilot_android_display_id} -n {shlex.quote(package + "/" + activity)}')
        if wait:
            time.sleep(1)

    def app_stop_azurpilot_android(self, package=None):
        """强制停止指定应用。

        Args:
            package: 待停止的应用包名，默认为当前配置包名。
        """
        self.azurpilot_android_shell_output(f'am force-stop {shlex.quote(package or self.package)}')

    def app_current_azurpilot_android(self, timeout: float = 30) -> str:
        """虚拟屏的前台应用包名。

        dumpsys window displays 按 displayId 分块，取目标块内的 mCurrentFocus；找不到即视为未在本虚拟屏运行。

        Args:
            timeout: 命令超时时间（秒）。

        Returns:
            str: 前台应用包名，未在当前虚拟屏运行则返回空字符串。
        """
        out = self.azurpilot_android_shell_output('dumpsys window displays', timeout=timeout)
        vid = self.azurpilot_android_display_id
        current = ''
        for block in re.split(r'\n\s*(?=Display )', out):
            if f'displayId={vid}' in block:
                m = re.search(r'mCurrentFocus=\S+\s*\{[^}]*?\s([\w.]+)/[\w.]+', block)
                if m:
                    current = m.group(1)
                break
        logger.attr('App current (azurpilot_android)', current)
        return current

    def get_orientation(self):
        """桥接模式下虚拟屏始终横屏 1280x720，直接返回 0。

        注意：本方法在 AzurPilotAndroid 混入类上，MRO 先于 Connection 的 adb 实现。

        Returns:
            int: 屏幕方向角度（固定返回 0）。
        """
        if self.serial == 'azurpilot_android':
            self.orientation = 0
            return 0
        return super().get_orientation()

    def dump_hierarchy_azurpilot_android(self):
        """系统 uiautomator 只看主屏，不能把其结果误认为虚拟屏。

        Raises:
            ScriptError: Android 虚拟屏不支持 uiautomator 层级树。
        """
        raise ScriptError('Android 虚拟屏不支持 uiautomator 层级树，请使用截图识别')
