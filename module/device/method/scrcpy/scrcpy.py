"""scrcpy 截图与控制后端模块。

整合 ScrcpyCore 与 ControlSender，提供带自动重试机制的帧捕获、点击、长按、滑动与拖拽控制实现。
"""

import socket
import time
from functools import partial

import numpy as np
from adbutils.errors import AdbError, AdbTimeout

import module.device.method.scrcpy.const as const
from module.base.utils import ensure_time, random_rectangle_point
from module.device.method.retry import retry_backend, recover_adb, recover_unknown
from module.device.method.minitouch import insert_swipe
from module.device.method.scrcpy.core import ScrcpyCore, ScrcpyError
from module.device.method.uiautomator_2 import Uiautomator2
from module.exception import EmulatorNotRunningError
from module.logger import logger


def _retry_recover(self, error, trial):
    # AdbTimeout 是 AdbError 的子类，必须先保留 Scrcpy 自身的重建策略。
    if isinstance(error, (ScrcpyError, AdbTimeout, socket.timeout)):
        logger.error(error)
        return self.scrcpy_init
    if isinstance(error, (ConnectionResetError, ConnectionAbortedError, AdbError)):
        return recover_adb(self, error)
    return recover_unknown(error)


retry = partial(retry_backend, recover=_retry_recover, label='设备-Scrcpy')


class Scrcpy(ScrcpyCore, Uiautomator2):
    """基于 scrcpy 协议的截图与输入控制实现类。"""

    def _scrcpy_resolution_check(self):
        """检查并校准屏幕分辨率。"""
        if not self._scrcpy_alive:
            with self._scrcpy_control_socket_lock:
                self.resolution_check_uiautomator2()

    @retry(on_exhausted=EmulatorNotRunningError)
    def screenshot_scrcpy(self):
        """通过 scrcpy 视频流获取最新一帧屏幕截图。

        Returns:
            np.ndarray: RGB 格式的屏幕截图数组。

        Raises:
            ScrcpyError: 视频接收线程异常或超时退出。
        """
        self._scrcpy_resolution_check()
        self.scrcpy_ensure_running()

        with self._scrcpy_control_socket_lock:
            # 等待新的一帧到达
            now = time.time()
            while 1:
                time.sleep(0.001)
                thread = self._scrcpy_stream_loop_thread
                if thread is None or not thread.is_alive():
                    raise ScrcpyError('_scrcpy_stream_loop_thread died')
                if self._scrcpy_last_frame_time > now:
                    # 直接返回当前帧引用，避免无意义深拷贝
                    screenshot = self._scrcpy_last_frame
                    return screenshot

    @retry
    def click_scrcpy(self, x, y):
        """通过 scrcpy 控制 Socket 发送单次点击事件。

        Args:
            x (int): 点击横坐标。
            y (int): 点击纵坐标。
        """
        self.scrcpy_ensure_running()

        with self._scrcpy_control_socket_lock:
            self._scrcpy_control.touch(x, y, const.ACTION_DOWN)
            self._scrcpy_control.touch(x, y, const.ACTION_UP)
            self.sleep(0.05)

    @retry
    def long_click_scrcpy(self, x, y, duration=1.0):
        """通过 scrcpy 发送长按事件。

        Args:
            x (int): 点击横坐标。
            y (int): 点击纵坐标。
            duration (float): 按下持续时间（秒）。
        """
        self.scrcpy_ensure_running()

        with self._scrcpy_control_socket_lock:
            self._scrcpy_control.touch(x, y, const.ACTION_DOWN)
            self.sleep(duration)
            self._scrcpy_control.touch(x, y, const.ACTION_UP)
            self.sleep(0.05)

    @retry
    def swipe_scrcpy(self, p1, p2):
        """通过 scrcpy 发送平滑滑动轨迹。

        Args:
            p1 (tuple[int, int]): 起始点坐标 (x, y)。
            p2 (tuple[int, int]): 终点坐标 (x, y)。
        """
        self.scrcpy_ensure_running()

        with self._scrcpy_control_socket_lock:
            # 不同于 minitouch，scrcpy 滑动需要更平滑连贯的轨迹插值
            points = insert_swipe(p0=p1, p3=p2, speed=4, min_distance=2)
            self._scrcpy_control.touch(*p1, const.ACTION_DOWN)

            for point in points[1:-1]:
                self._scrcpy_control.touch(*point, const.ACTION_MOVE)
                self.sleep(0.002)

            self._scrcpy_control.touch(*p2, const.ACTION_MOVE)
            self._scrcpy_control.touch(*p2, const.ACTION_UP)
            self.sleep(0.05)

    @retry
    def drag_scrcpy(self, p1, p2, point_random=(-10, -10, 10, 10), hold_duration=0.0):
        """通过 scrcpy 发送拖拽操作（支持随机偏移与终点长按停顿）。

        Args:
            p1 (tuple[int, int]): 起始坐标。
            p2 (tuple[int, int]): 终点坐标。
            point_random (tuple[int, int, int, int]): 坐标随机偏移矩形。
            hold_duration (float): 达到终点后的悬停保持时间（秒）。
        """
        self.scrcpy_ensure_running()

        with self._scrcpy_control_socket_lock:
            p1 = np.array(p1) - random_rectangle_point(point_random)
            p2 = np.array(p2) - random_rectangle_point(point_random)
            points = insert_swipe(p0=p1, p3=p2, speed=4, min_distance=2)

            self._scrcpy_control.touch(*p1, const.ACTION_DOWN)

            for point in points[1:-1]:
                self._scrcpy_control.touch(*point, const.ACTION_MOVE)
                self.sleep(0.002)

            # 保持 280ms
            for _ in range(int(0.14 // 0.002) * 2):
                self._scrcpy_control.touch(*p2, const.ACTION_MOVE)
                self.sleep(0.002)

            hold_duration = ensure_time(hold_duration) - 0.28
            if hold_duration > 0:
                step = 0.002
                repeats = int(hold_duration // step)
                for _ in range(repeats):
                    self._scrcpy_control.touch(*p2, const.ACTION_MOVE)
                    self.sleep(step)
                remainder = hold_duration - (repeats * step)
                if remainder > 0:
                    self._scrcpy_control.touch(*p2, const.ACTION_MOVE)
                    self.sleep(remainder)

            self._scrcpy_control.touch(*p2, const.ACTION_UP)
            self.sleep(0.05)
