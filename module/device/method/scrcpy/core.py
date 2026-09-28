"""scrcpy 核心连接层模块。

管理与设备端 scrcpy-server 服务的 Socket 通信，处理 H.264 视频流解码、
控制通道创建与维护，提供连接生命周期管理。
"""

import socket
import struct
import threading
import time
import typing as t
from time import sleep

import numpy as np
from adbutils import AdbError, Network

from module.base.decorator import cached_property
from module.base.timer import Timer
from module.device.connection import Connection
from module.device.method.scrcpy.control import ControlSender
from module.device.method.scrcpy.options import ScrcpyOptions
from module.device.method.utils import AdbConnection, recv_all
from module.exception import RequestHumanTakeover
from module.logger import logger


class ScrcpyError(Exception):
    """scrcpy 通信或协议异常基类。"""
    pass


class ScrcpyCore(Connection):
    """scrcpy 核心通信与视频流接收处理类。

    管理与设备端 scrcpy-server 的连接，包括视频流 Socket 与控制 Socket，
    并在后台线程中解码 H.264 帧为 numpy ndarray 图像。
    """

    _scrcpy_last_frame: t.Optional[np.ndarray] = None
    _scrcpy_last_frame_time: float = 0.

    _scrcpy_alive = False
    _scrcpy_server_stream: t.Optional[AdbConnection] = None
    _scrcpy_video_socket: t.Optional[socket.socket] = None
    _scrcpy_control_socket: t.Optional[socket.socket] = None
    _scrcpy_control_socket_lock = threading.Lock()

    _scrcpy_stream_loop_thread = None
    _scrcpy_resolution: t.Tuple[int, int] = (1280, 720)

    @cached_property
    def _scrcpy_control(self) -> ControlSender:
        return ControlSender(self)

    def scrcpy_init(self):
        """初始化 scrcpy 服务：停止存量服务、推送服务端 jar 并启动连接。"""
        self._scrcpy_server_stop()

        logger.hr('[设备-Scrcpy] Scrcpy初始化')
        logger.info(f'[设备-Scrcpy] 推送中 {self.config.SCRCPY_FILEPATH_LOCAL}')
        self.adb_push(self.config.SCRCPY_FILEPATH_LOCAL, self.config.SCRCPY_FILEPATH_REMOTE)

        self._scrcpy_alive = False
        self.scrcpy_ensure_running()

    def scrcpy_ensure_running(self):
        """确保 scrcpy 服务正在运行，未运行则触发启动。"""
        if not self._scrcpy_alive:
            with self._scrcpy_control_socket_lock:
                self._scrcpy_server_start()

    def _scrcpy_server_start(self):
        """启动设备端的 scrcpy 服务进程并建立视频流与控制 Socket 连接。

        Raises:
            ScrcpyError: 服务启动异常或连接超时。
            adbutils.AdbTimeout: ADB 连接超时。
            socket.timeout: Socket 通信超时。
        """
        logger.hr('[设备-Scrcpy] Scrcpy服务器启动')
        commands = ScrcpyOptions.command_v120(jar_path=self.config.SCRCPY_FILEPATH_REMOTE)
        self._scrcpy_server_stream: AdbConnection = self.adb.shell(
            commands,
            stream=True,
        )
        self._scrcpy_server_stream.conn.settimeout(3)

        logger.info('[设备-Scrcpy] 创建服务器流')
        ret = self._scrcpy_server_stream.read(10)
        # b'Aborted \r\n'
        # 可能是 jar 文件不存在
        if b'Aborted' in ret:
            raise ScrcpyError('Aborted')
        if ret == b'[server] E':
            # [server] ERROR: ...
            ret += recv_all(self._scrcpy_server_stream)
            logger.error(ret)
            # 服务端与客户端版本不匹配
            if b'does not match the client' in ret:
                raise ScrcpyError('Server version does not match the client')
            else:
                raise ScrcpyError('Unknown scrcpy error')
        else:
            # [server] INFO: Device: ...
            ret += self._scrcpy_receive_from_server_stream()
            logger.info(ret)
            pass

        logger.info('[设备-Scrcpy] 创建视频Socket')
        timeout = Timer(3).start()
        while 1:
            if timeout.reached():
                raise ScrcpyError('Connect scrcpy-server timeout')

            try:
                self._scrcpy_video_socket = self.adb.create_connection(
                    Network.LOCAL_ABSTRACT, "scrcpy"
                )
                self._scrcpy_video_socket.settimeout(3)
                break
            except AdbError:
                sleep(0.1)
        dummy_byte = self._scrcpy_video_socket.recv(1)
        if not len(dummy_byte) or dummy_byte != b"\x00":
            raise ScrcpyError('Did not receive Dummy Byte from video stream')

        logger.info('[设备-Scrcpy] 创建控制Socket')
        self._scrcpy_control_socket = self.adb.create_connection(
            Network.LOCAL_ABSTRACT, "scrcpy"
        )
        self._scrcpy_control_socket.settimeout(3)

        logger.info('[设备-Scrcpy] 获取设备信息')
        device_name = self._scrcpy_video_socket.recv(64).decode("utf-8").rstrip("\x00")
        if len(device_name):
            logger.attr('[设备-Scrcpy] 设备名称', device_name)
        else:
            raise ScrcpyError('Did not receive Device Name')
        ret = self._scrcpy_video_socket.recv(4)
        self._scrcpy_resolution = struct.unpack(">HH", ret)
        logger.attr('[设备-Scrcpy] 分辨率', self._scrcpy_resolution)

        self._scrcpy_video_socket.setblocking(False)
        self._scrcpy_alive = True

        logger.info('[设备-Scrcpy] 启动视频流循环线程')
        self._scrcpy_stream_loop_thread = threading.Thread(
            target=self._scrcpy_stream_loop, daemon=True
        )
        self._scrcpy_stream_loop_thread.start()
        while 1:
            if self._scrcpy_stream_loop_thread is not None and self._scrcpy_stream_loop_thread.is_alive():
                break
            self.sleep(0.001)

        logger.info('[设备-Scrcpy] Scrcpy服务器已启动')

    def _scrcpy_server_stop(self):
        """停止 scrcpy 服务端并清理所有 Socket 和解码线程。"""
        logger.hr('[设备-Scrcpy] Scrcpy服务器停止')

        self._scrcpy_alive = False

        if self._scrcpy_stream_loop_thread is not None:
            self._scrcpy_stream_loop_thread.join(1)
            del self._scrcpy_stream_loop_thread
            self._scrcpy_stream_loop_thread = None

        if self._scrcpy_control_socket is not None:
            try:
                self._scrcpy_control_socket.close()
            except Exception as e:
                logger.error(e)
            del self._scrcpy_control_socket
            self._scrcpy_control_socket = None

        if self._scrcpy_video_socket is not None:
            try:
                self._scrcpy_video_socket.close()
            except Exception as e:
                logger.error(e)
            del self._scrcpy_video_socket
            self._scrcpy_video_socket = None

        if self._scrcpy_server_stream is not None:
            try:
                self._scrcpy_server_stream.close()
            except Exception as e:
                logger.error(e)
            del self._scrcpy_server_stream
            self._scrcpy_server_stream = None

        logger.info('[设备-Scrcpy] Scrcpy服务器已停止')

    def _scrcpy_receive_from_server_stream(self):
        """从 scrcpy 服务器流读取输出信息。"""
        if self._scrcpy_server_stream is not None:
            try:
                return self._scrcpy_server_stream.conn.recv(4096)
            except Exception:
                pass

    def _scrcpy_stream_loop(self) -> None:
        """后台视频流接收与 H.264 解码循环。

        Raises:
            RequestHumanTakeover: 缺失 PyAV (`av`) 依赖时提示人工处理。
            ScrcpyError: 视频流异常中断时抛出。
        """
        try:
            from av.codec import CodecContext
            from av.error import InvalidDataError
        except ImportError as e:
            logger.error(e)
            logger.error('[设备-Scrcpy] 您必须安装 `av` 才能使用scrcpy截图，请更新依赖')
            raise RequestHumanTakeover

        codec = CodecContext.create("h264", "r")
        while self._scrcpy_alive:
            try:
                raw_h264 = self._scrcpy_video_socket.recv(0x10000)
                if raw_h264 == b"":
                    if self._scrcpy_alive:
                        raise ScrcpyError("_scrcpy_stream_loop_thread: Video stream disconnected")
                packets = codec.parse(raw_h264)
                for packet in packets:
                    frames = codec.decode(packet)
                    for frame in frames:
                        frame = frame.to_ndarray(format="rgb24")
                        self._scrcpy_last_frame = frame
                        self._scrcpy_last_frame_time = time.time()
                        self._scrcpy_resolution = (frame.shape[1], frame.shape[0])
            except (BlockingIOError, InvalidDataError):
                # 仅返回非空帧，避免阻塞渲染
                time.sleep(0.001)
            except (ConnectionError, OSError) as e:  # Socket 已关闭
                if self._scrcpy_alive:
                    logger.error(f'_scrcpy_stream_loop_thread: {repr(e)}')
                    raise
            except Exception as e:
                logger.error(f'_scrcpy_stream_loop_thread exception: {repr(e)}')
                raise

        raise ScrcpyError('_scrcpy_stream_loop stopped')
