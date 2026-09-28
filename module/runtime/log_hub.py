"""运行日志到达通知：只传实例名，日志内容仍由 RuntimeService 统一渲染。"""
import threading
from typing import Callable


class LogHub:
    """运行日志到达事件广播中心。

    把日志队列的逐条到达事件广播给 WebSocket 会话。

    Attributes:
        listeners: 订阅监听器集合。
        lock: 保护监听器集合的互斥锁。
    """

    def __init__(self):
        """初始化日志事件广播中心。"""
        self.listeners = set()
        self.lock = threading.Lock()

    def publish(self, instance: str):
        """广播指定实例的新日志到达事件。

        Args:
            instance: 产生新日志的实例名称。
        """
        with self.lock:
            listeners = tuple(self.listeners)
        for listener in listeners:
            listener(instance)

    def subscribe(self, listener: Callable[[str], None]):
        """注册日志事件监听器。

        Args:
            listener: 回调函数，接收实例名称作为参数。
        """
        with self.lock:
            self.listeners.add(listener)

    def unsubscribe(self, listener: Callable[[str], None]):
        """注销日志事件监听器。

        Args:
            listener: 待移除的回调函数。
        """
        with self.lock:
            self.listeners.discard(listener)


hub = LogHub()
