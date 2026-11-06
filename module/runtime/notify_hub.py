"""任务通知到达事件：把 notify_webui 的推送实时广播给 WebSocket 会话。"""
import threading
from typing import Any, Callable


class NotifyHub:
    """任务通知事件广播中心。

    通知是一次性消息（非状态），广播只负责送达 payload，不缓存历史：
    页面没在订阅时就错过，符合「送达正在看 WebUI 的用户」的定位。

    Attributes:
        listeners: 订阅监听器集合。
        lock: 保护监听器集合的互斥锁。
    """

    def __init__(self):
        """初始化任务通知广播中心。"""
        self.listeners = set()
        self.lock = threading.Lock()

    def publish(self, notification: dict[str, Any]):
        """广播一条任务通知。

        Args:
            notification: 通知载荷，含 instance/title/content 字段。
        """
        with self.lock:
            listeners = tuple(self.listeners)
        for listener in listeners:
            listener(notification)

    def subscribe(self, listener: Callable[[dict[str, Any]], None]):
        """注册通知事件监听器。

        Args:
            listener: 回调函数，接收通知载荷字典作为参数。
        """
        with self.lock:
            self.listeners.add(listener)

    def unsubscribe(self, listener: Callable[[dict[str, Any]], None]):
        """注销通知事件监听器。

        Args:
            listener: 待移除的回调函数。
        """
        with self.lock:
            self.listeners.discard(listener)


hub = NotifyHub()
