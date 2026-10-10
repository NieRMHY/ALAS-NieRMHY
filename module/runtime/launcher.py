"""WebUI 启动器工具模块，提供实例管理的进程间通信和本地请求检测。

包括异步命令执行、WebSocket 连接管理、
本地请求判断等底层支持功能。
"""
from module.base.runtime_params import COMMAND_TIMEOUT, CONNECTION_EXPIRE
import asyncio
import json
import sys
import time
import uuid
from typing import Any

from module.logger import logger

LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}


def is_windows() -> bool:
    """检查当前运行平台是否为 Windows。

    Returns:
        bool: Windows 系统返回 True，否则返回 False。
    """
    return sys.platform == "win32"


def is_local_request(request) -> bool:
    """判断 HTTP 请求是否来自本机回环地址。

    Args:
        request: Starlette Request 请求对象。

    Returns:
        bool: 客户端 IP 与 Host 请求头均属于本机地址返回 True，否则返回 False。
    """
    client = getattr(request, "client", None)
    host = getattr(client, "host", "") if client is not None else ""
    header_host = _normalize_host(request.headers.get("host", ""))
    return host in LOCAL_HOSTS and header_host in LOCAL_HOSTS


def _normalize_host(host: str) -> str:
    """标准化 Host 字符串，剥离端口号与 IPv6 方括号。

    Args:
        host: 原始主机名或 IP。

    Returns:
        str: 规范化后的小写主机名。
    """
    host = str(host or "").strip().lower()
    if host.startswith("["):
        return host[1:].split("]", maxsplit=1)[0]
    return host.split(":", maxsplit=1)[0]


class LauncherControl:
    """维护 WebUI 与外部启动器之间的本地命令通道。

    Attributes:
        connected: 启动器当前是否连接。
        last_seen: 上次收到心跳的时间戳。
        autostart_enabled: 启动器汇报的开机自启状态。
        autostart_supported: 当前系统是否支持开机自启。
        last_error: 最后一次记录的错误信息。
    """

    def __init__(self) -> None:
        """初始化启动器控制通道。"""
        self._queue = asyncio.Queue()
        self._pending: dict[str, asyncio.Future] = {}
        self.connected = False
        self.last_seen = 0.0
        self.autostart_enabled: bool | None = None
        self.autostart_supported = is_windows()
        self.last_error = ""

    def _is_connected(self) -> bool:
        """检查启动器连接是否处于活跃状态（未超时）。

        Returns:
            bool: 连接正常返回 True，否则返回 False。
        """
        if not self.connected:
            return False
        if time.time() - self.last_seen > CONNECTION_EXPIRE:
            self.connected = False
            return False
        return True

    def status(self, request_local: bool = True) -> dict[str, Any]:
        """获取启动器连接与自启能力状态字典。

        Args:
            request_local: 请求是否来自本机。

        Returns:
            dict[str, Any]: 状态信息字典。
        """
        return {
            "success": True,
            "platform": sys.platform,
            "windows": is_windows(),
            "request_local": request_local,
            "launcher_connected": self._is_connected(),
            "autostart_supported": self.autostart_supported,
            "autostart_enabled": self.autostart_enabled,
            "last_error": self.last_error,
        }

    async def mark_connected(self) -> None:
        """标记启动器已连接并自动向队列下发自启状态查询命令。"""
        self.connected = True
        self.last_seen = time.time()
        await self._queue.put(self._build_command("startup.query"))

    def mark_disconnected(self) -> None:
        """标记启动器已断开连接。"""
        self.connected = False
        self.last_seen = time.time()

    def keep_alive(self) -> None:
        """更新启动器心跳活跃时间戳。"""
        self.connected = True
        self.last_seen = time.time()

    async def next_command(self) -> dict[str, Any]:
        """异步等待并获取下一个待下发给启动器的命令。

        Returns:
            dict[str, Any]: 命令字典。
        """
        return await self._queue.get()

    async def set_autostart(self, enabled: bool) -> dict[str, Any]:
        """向启动器发送设置开机自启命令并等待响应。

        Args:
            enabled: 是否启用开机自启。

        Returns:
            dict[str, Any]: 执行结果字典。
        """
        if not is_windows():
            return self._error("当前平台不支持开机自启动")
        if not self._is_connected():
            return self._error("启动器未连接，请通过启动器打开 AzurPilot")

        command = self._build_command(
            "startup.set",
            {"enabled": bool(enabled), "mode": "tray"},
        )
        future = asyncio.get_running_loop().create_future()
        self._pending[command["id"]] = future
        await self._queue.put(command)

        try:
            result = await asyncio.wait_for(future, timeout=COMMAND_TIMEOUT)
        except asyncio.TimeoutError:
            self._pending.pop(command["id"], None)
            self.last_error = "等待启动器响应超时"
            return self._error(self.last_error)

        if result.get("success"):
            data = result.get("data") or {}
            if "enabled" in data:
                self.autostart_enabled = bool(data["enabled"])
            self.last_error = ""
            return {"success": True, "data": self.status()}

        self.last_error = str(result.get("error") or "启动器设置失败")
        return self._error(self.last_error)

    async def report(self, data: dict[str, Any]) -> dict[str, Any]:
        """接收并处理启动器上报的执行结果或状态数据。

        Args:
            data: 上报的数据字典。

        Returns:
            dict[str, Any]: 处理成功确认字典。
        """
        self.keep_alive()
        command_id = data.get("id")
        payload = data.get("data") or {}
        success = bool(data.get("success"))

        if success and "enabled" in payload:
            self.autostart_enabled = bool(payload["enabled"])
            self.last_error = ""
        elif not success:
            self.last_error = str(data.get("error") or "启动器命令执行失败")

        if command_id:
            future = self._pending.pop(command_id, None)
            if future is not None and not future.done():
                future.set_result(data)

        return {"success": True}

    @staticmethod
    def event(command: dict[str, Any]) -> str:
        """将命令字典打包为 SSE (Server-Sent Events) 数据帧。

        Args:
            command: 命令字典。

        Returns:
            str: 格式化后的 SSE 事件字符串。
        """
        return f"data: {json.dumps(command, ensure_ascii=False)}\n\n"

    @staticmethod
    def keepalive_event() -> str:
        """生成 SSE 保活注释帧。

        Returns:
            str: SSE 注释行。
        """
        return ": keepalive\n\n"

    @staticmethod
    def _build_command(command_type: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """构造带有唯一 ID 的下发命令字典。

        Args:
            command_type: 命令类型字符串。
            payload: 命令参数字典。

        Returns:
            dict[str, Any]: 结构化的命令字典。
        """
        return {
            "id": uuid.uuid4().hex,
            "type": command_type,
            "payload": payload or {},
        }

    @staticmethod
    def _error(message: str) -> dict[str, Any]:
        """记录警告日志并构造统一的错误响应。

        Args:
            message: 错误描述信息。

        Returns:
            dict[str, Any]: 包含 success: False 和 error 的字典。
        """
        logger.warning(message)
        return {"success": False, "error": message}


launcher_control = LauncherControl()
