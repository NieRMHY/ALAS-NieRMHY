"""网络时间源模块。

通过 NTP 服务器校准本地时间，确保任务调度的时间准确性。
在长时间运行场景下，系统时钟可能存在漂移，
NTP 校时可以保证委托、科研等定时任务的精确触发。

特性：
- 启动时自动校准，后续读取使用缓存的偏移量
- 支持多个 NTP 服务器，自动故障转移
- 校时失败时回退到本机时间，不影响运行
- 可通过环境变量 AZURPILOT_NTP_DISABLE 禁用
- 可通过环境变量 AZURPILOT_NTP_SERVERS 自定义服务器
"""

import os
import socket
import struct
import threading
import time as time_
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# NTP 协议常量
NTP_EPOCH_DELTA = 2208988800  # NTP 时间纪元与 Unix 时间纪元的差值（秒）
NTP_PORT = 123
NTP_PACKET = b'\x1b' + b'\0' * 47
NTP_SERVERS_ENV = 'AZURPILOT_NTP_SERVERS'
NTP_DISABLE_ENV = 'AZURPILOT_NTP_DISABLE'
# 默认 NTP 服务器列表（中国优先）
DEFAULT_NTP_SERVERS = (
    'ntp.ntsc.ac.cn',
    'ntp.aliyun.com',
    'ntp.tencent.com',
    'cn.pool.ntp.org',
    'pool.ntp.org',
)


class NetworkTimeSource:
    """通过 NTP 服务器校准本地时间。

    只缓存本机时间与 NTP 时间的偏移量，后续读取不会频繁访问网络。

    Attributes:
        offset: 本地系统时间与网络时间的偏差量（秒）。
        base_timestamp: 基准网络时间戳。
        base_monotonic: 基准单调时钟时间。
        server: 当前已同步的 NTP 服务器域名。
        synced: 是否已成功完成过网络校时。
        last_sync_monotonic: 上次成功同步时的单调时钟。
        retry_after_monotonic: 下次允许重试的单调时钟节点。
        refresh_interval: 周期性重新同步时间间隔（秒）。
        retry_interval: 失败后的重试退避间隔（秒）。
        timeout: 网络查询单次超时时间（秒）。
    """

    def __init__(self) -> None:
        """初始化网络时间源管理器。"""
        self.offset = 0.0
        self.base_timestamp = 0.0
        self.base_monotonic = 0.0
        self.server: Optional[str] = None
        self.synced = False
        self.last_sync_monotonic = 0.0
        self.retry_after_monotonic = 0.0
        self.refresh_interval = 30 * 60
        self.retry_interval = 10 * 60
        self.timeout = 1.0
        self._lock = threading.RLock()
        self._warned = False

    @property
    def enabled(self) -> bool:
        """检查网络校时是否启用。

        Returns:
            bool: 环境变量未显式禁用时返回 True。
        """
        value = os.environ.get(NTP_DISABLE_ENV, '').strip().lower()
        return value not in {'1', 'true', 'yes', 'on'}

    @property
    def servers(self) -> List[str]:
        """获取当前配置的 NTP 服务器列表。

        Returns:
            List[str]: 有效的 NTP 服务器域名或 IP 列表。
        """
        value = os.environ.get(NTP_SERVERS_ENV, '').strip()
        if value:
            servers = [item.strip() for item in value.replace(';', ',').split(',')]
            servers = [item for item in servers if item]
            if servers:
                return servers

        return list(DEFAULT_NTP_SERVERS)

    def _query_server(self, host: str) -> float:
        """向指定主机发送 NTP UDP 请求并计算时间偏差。

        Args:
            host: 目标 NTP 服务器主机名或 IP。

        Returns:
            float: 计算出的网络时间与本地时间的秒数偏差。

        Raises:
            OSError: 网络连接失败或响应数据格式无效。
        """
        last_error = None
        addresses = socket.getaddrinfo(host, NTP_PORT, type=socket.SOCK_DGRAM)
        for family, socktype, proto, _, sockaddr in addresses:
            with socket.socket(family, socktype, proto) as sock:
                sock.settimeout(self.timeout)
                try:
                    sent = time_.time()
                    sock.sendto(NTP_PACKET, sockaddr)
                    data, _ = sock.recvfrom(48)
                    received = time_.time()
                except OSError as e:
                    last_error = e
                    continue

            if len(data) < 48:
                continue

            mode = data[0] & 0b00000111
            stratum = data[1]
            if mode not in {4, 5} or not 1 <= stratum <= 15:
                continue

            seconds, fraction = struct.unpack('!II', data[40:48])
            ntp_timestamp = seconds - NTP_EPOCH_DELTA + fraction / 2 ** 32
            local_timestamp = (sent + received) / 2
            if ntp_timestamp < 1577836800:  # 2020-01-01
                continue

            return ntp_timestamp - local_timestamp

        if last_error is not None:
            raise last_error
        raise OSError(f'无效的 NTP 响应: {host}')

    def refresh(self, force: bool = False) -> bool:
        """刷新 NTP 偏移量，失败时保留已有偏移并退回本机时间。

        Args:
            force: 是否忽略刷新间隔强制重新向服务器请求。

        Returns:
            bool: 当前时间已成功与网络同步返回 True，否则返回 False。
        """
        if not self.enabled:
            return False

        current = time_.monotonic()
        with self._lock:
            if not force and self.synced and current - self.last_sync_monotonic < self.refresh_interval:
                return True
            if not force and current < self.retry_after_monotonic:
                return self.synced

            errors = []
            for server in self.servers:
                try:
                    offset = self._query_server(server)
                except OSError as e:
                    errors.append(f'{server}: {e}')
                    continue

                self.offset = offset
                self.base_timestamp = time_.time() + offset
                self.base_monotonic = time_.monotonic()
                self.server = server
                self.synced = True
                self.last_sync_monotonic = time_.monotonic()
                self.retry_after_monotonic = 0.0
                self._warned = False
                self._log_info(f'网络时间已校准: {server}, offset={offset:.3f}s')
                return True

            self.retry_after_monotonic = time_.monotonic() + self.retry_interval
            if not self._warned:
                detail = '; '.join(errors) if errors else '没有可用服务器'
                self._log_warning(f'NTP 校时失败，暂时使用本机时间: {detail}')
                self._warned = True
            return self.synced

    def timestamp(self) -> float:
        """获取经网络校准后的当前绝对时间戳。

        Returns:
            float: 秒级浮点时间戳。
        """
        self.refresh()
        if self.synced:
            return self.base_timestamp + (time_.monotonic() - self.base_monotonic)
        return time_.time() + self.offset

    def now(self, tz: Optional[Any] = None) -> datetime:
        """获取经网络校准后的当前 datetime 对象。

        Args:
            tz: 可选的时区对象。

        Returns:
            datetime: 对应时区的当前日期时间对象。
        """
        return datetime.fromtimestamp(self.timestamp(), tz=tz)

    def status(self) -> Dict[str, Any]:
        """获取当前网络校时服务的运行状态详情。

        Returns:
            Dict[str, Any]: 包含同步状态、服务器、偏差与刷新间隔的字典。
        """
        self.refresh()
        return {
            'enabled': self.enabled,
            'synced': self.synced,
            'server': self.server or '-',
            'offset': self.offset,
            'refresh_interval': self.refresh_interval,
            'last_sync_elapsed': (
                time_.monotonic() - self.last_sync_monotonic
                if self.synced else None
            ),
        }

    @staticmethod
    def monotonic() -> float:
        """获取系统单调递增时钟秒数。

        Returns:
            float: 单调时钟秒数。
        """
        return time_.monotonic()

    @staticmethod
    def sleep(seconds: float) -> None:
        """系统挂起休眠指定秒数。

        Args:
            seconds: 休眠秒数。
        """
        time_.sleep(seconds)

    @staticmethod
    def _log_info(message: str) -> None:
        """输出安全信息日志。"""
        try:
            from module.logger import logger
            logger.info(message)
        except Exception:
            pass

    @staticmethod
    def _log_warning(message: str) -> None:
        """输出安全警告日志。"""
        try:
            from module.logger import logger
            logger.warning(message)
        except Exception:
            pass


network_time = NetworkTimeSource()


def refresh_time(force: bool = False) -> bool:
    """刷新网络校时偏移量。

    Args:
        force: 是否强制立即网络查询。

    Returns:
        bool: 当前是否已处于同步状态。
    """
    return network_time.refresh(force=force)


def now(tz: Optional[Any] = None) -> datetime:
    """获取当前校准后的本地 datetime。

    Args:
        tz: 可选时区。

    Returns:
        datetime: 当前日期时间。
    """
    return network_time.now(tz=tz)


def utcnow() -> datetime:
    """获取当前校准后的 UTC datetime。

    Returns:
        datetime: UTC 日期时间。
    """
    return now(timezone.utc)


def timestamp() -> float:
    """获取当前校准后的网络时间戳。

    Returns:
        float: 浮点秒数时间戳。
    """
    return network_time.timestamp()


def status() -> Dict[str, Any]:
    """获取网络时间源状态。

    Returns:
        Dict[str, Any]: 状态信息字典。
    """
    return network_time.status()


def monotonic() -> float:
    """获取系统单调时钟时间。

    Returns:
        float: 单调时钟数值。
    """
    return network_time.monotonic()


def sleep(seconds: float) -> None:
    """休眠指定秒数。

    Args:
        seconds: 休眠时长。
    """
    network_time.sleep(seconds)
