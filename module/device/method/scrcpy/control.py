"""scrcpy 控制指令发送器模块。

封装触摸、按键、剪贴板等输入事件的二进制打包和 Socket 发送逻辑，
通过 inject 装饰器实现协议注入。
"""

import functools
import socket
import struct
import time

import module.device.method.scrcpy.const as const


def inject(control_type: int):
    """注入控制类型头并发送二进制数据包的装饰器。

    Args:
        control_type (int): 待发送的事件类型，对应 const.TYPE_* 常量。

    Returns:
        Callable: 包装后的方法，自动加上控制类型前缀并在 Socket 可用时发送。
    """

    def wrapper(f):
        @functools.wraps(f)
        def inner(self, *args, **kwargs):
            package = struct.pack(">B", control_type) + f(self, *args, **kwargs)
            if self.control_socket is not None:
                with self.control_socket_lock:
                    self.control_socket.send(package)
            return package

        return inner

    return wrapper


class ControlSender:
    """scrcpy 控制指令构建与发送类。"""

    def __init__(self, parent):
        """初始化控制发送器。

        Args:
            parent: 持有 control_socket 等属性的宿主对象。
        """
        self.parent = parent

    @property
    def control_socket(self):
        return self.parent._scrcpy_control_socket

    @property
    def control_socket_lock(self):
        return self.parent._scrcpy_control_socket_lock

    @property
    def resolution(self):
        return self.parent._scrcpy_resolution

    @inject(const.TYPE_INJECT_KEYCODE)
    def keycode(
            self, keycode: int, action: int = const.ACTION_DOWN, repeat: int = 0
    ) -> bytes:
        """向设备发送按键事件。

        Args:
            keycode (int): 按键编码，见 const.KEYCODE_*。
            action (int): 动作类型，ACTION_DOWN 或 ACTION_UP。
            repeat (int): 重复触发次数。

        Returns:
            bytes: 打包的二进制控制包。
        """
        return struct.pack(">Biii", action, keycode, repeat, 0)

    @inject(const.TYPE_INJECT_TEXT)
    def text(self, text: str) -> bytes:
        """向设备注入文本输入。

        Args:
            text (str): 待注入的字符串文本。

        Returns:
            bytes: 打包的二进制控制包。
        """
        buffer = text.encode("utf-8")
        return struct.pack(">i", len(buffer)) + buffer

    @inject(const.TYPE_INJECT_TOUCH_EVENT)
    def touch(
            self, x: int, y: int, action: int = const.ACTION_DOWN, touch_id: int = -1
    ) -> bytes:
        """向设备发送屏幕触摸事件。

        Args:
            x (int): 横坐标像素值。
            y (int): 纵坐标像素值。
            action (int): 触摸动作类型，ACTION_DOWN、ACTION_UP 或 ACTION_MOVE。
            touch_id (int): 触控点 ID，默认虚拟 ID -1，可用于模拟多指触控。

        Returns:
            bytes: 打包的二进制控制包。
        """
        x, y = max(x, 0), max(y, 0)
        return struct.pack(
            ">BqiiHHHi",
            action,
            touch_id,
            int(x),
            int(y),
            int(self.resolution[0]),
            int(self.resolution[1]),
            0xFFFF,
            1,
        )

    @inject(const.TYPE_INJECT_SCROLL_EVENT)
    def scroll(self, x: int, y: int, h: int, v: int) -> bytes:
        """向设备发送滚轮滑动事件。

        Args:
            x (int): 横坐标位置。
            y (int): 纵坐标位置。
            h (int): 水平滚动偏移量。
            v (int): 垂直滚动偏移量。

        Returns:
            bytes: 打包的二进制控制包。
        """
        x, y = max(x, 0), max(y, 0)
        return struct.pack(
            ">iiHHii",
            int(x),
            int(y),
            int(self.resolution[0]),
            int(self.resolution[1]),
            int(h),
            int(v),
        )

    @inject(const.TYPE_BACK_OR_SCREEN_ON)
    def back_or_turn_screen_on(self, action: int = const.ACTION_DOWN) -> bytes:
        """触发返回键或点亮屏幕。当屏幕熄灭时仅 ACTION_DOWN 会点亮屏幕。

        Args:
            action (int): 动作类型，ACTION_DOWN 或 ACTION_UP。

        Returns:
            bytes: 打包的二进制控制包。
        """
        return struct.pack(">B", action)

    @inject(const.TYPE_EXPAND_NOTIFICATION_PANEL)
    def expand_notification_panel(self) -> bytes:
        """展开通知面板。

        Returns:
            bytes: 空字节负载。
        """
        return b""

    @inject(const.TYPE_EXPAND_SETTINGS_PANEL)
    def expand_settings_panel(self) -> bytes:
        """展开快速设置面板。

        Returns:
            bytes: 空字节负载。
        """
        return b""

    @inject(const.TYPE_COLLAPSE_PANELS)
    def collapse_panels(self) -> bytes:
        """收起所有下拉面板。

        Returns:
            bytes: 空字节负载。
        """
        return b""

    def get_clipboard(self) -> str:
        """获取设备剪贴板文本。

        Returns:
            str: 剪贴板中的字符串内容。
        """
        # 由于需要读取 Socket 响应数据，无法直接使用 inject 装饰器自动发送
        s: socket.socket = self.control_socket

        with self.control_socket_lock:
            # 清空接收缓冲区
            s.setblocking(False)
            while True:
                try:
                    s.recv(1024)
                except BlockingIOError:
                    break
            s.setblocking(True)

            # 发送请求包并读取数据
            package = struct.pack(">B", const.TYPE_GET_CLIPBOARD)
            s.send(package)
            (code,) = struct.unpack(">B", s.recv(1))
            assert code == 0
            (length,) = struct.unpack(">i", s.recv(4))

            return s.recv(length).decode("utf-8")

    @inject(const.TYPE_SET_CLIPBOARD)
    def set_clipboard(self, text: str, paste: bool = False) -> bytes:
        """设置设备剪贴板内容。

        Args:
            text (str): 待设置的字符串内容。
            paste (bool): 设置后是否立即执行粘贴。

        Returns:
            bytes: 打包的二进制控制包。
        """
        buffer = text.encode("utf-8")
        return struct.pack(">?i", paste, len(buffer)) + buffer

    @inject(const.TYPE_SET_SCREEN_POWER_MODE)
    def set_screen_power_mode(self, mode: int = const.POWER_MODE_NORMAL) -> bytes:
        """设置屏幕电源模式（息屏或亮屏）。

        Args:
            mode (int): 模式常量，POWER_MODE_OFF 或 POWER_MODE_NORMAL。

        Returns:
            bytes: 打包的二进制控制包。
        """
        return struct.pack(">b", mode)

    @inject(const.TYPE_ROTATE_DEVICE)
    def rotate_device(self) -> bytes:
        """旋转设备屏幕方向。

        Returns:
            bytes: 空字节负载。
        """
        return b""

    def swipe(
            self,
            start_x: int,
            start_y: int,
            end_x: int,
            end_y: int,
            move_step_length: int = 5,
            move_steps_delay: float = 0.005,
    ) -> None:
        """在屏幕上执行平滑滑动操作。

        Args:
            start_x (int): 起始横坐标。
            start_y (int): 起始纵坐标。
            end_x (int): 终点横坐标。
            end_y (int): 终点纵坐标。
            move_step_length (int): 单步移动像素步长。
            move_steps_delay (float): 每步之间的延迟时间（秒）。
        """
        self.touch(start_x, start_y, const.ACTION_DOWN)
        next_x = start_x
        next_y = start_y

        if end_x > self.resolution[0]:
            end_x = self.resolution[0]

        if end_y > self.resolution[1]:
            end_y = self.resolution[1]

        decrease_x = True if start_x > end_x else False
        decrease_y = True if start_y > end_y else False
        while True:
            if decrease_x:
                next_x -= move_step_length
                if next_x < end_x:
                    next_x = end_x
            else:
                next_x += move_step_length
                if next_x > end_x:
                    next_x = end_x

            if decrease_y:
                next_y -= move_step_length
                if next_y < end_y:
                    next_y = end_y
            else:
                next_y += move_step_length
                if next_y > end_y:
                    next_y = end_y

            self.touch(next_x, next_y, const.ACTION_MOVE)

            if next_x == end_x and next_y == end_y:
                self.touch(next_x, next_y, const.ACTION_UP)
                break
            time.sleep(move_steps_delay)
