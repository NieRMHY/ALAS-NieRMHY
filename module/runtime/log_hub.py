"""运行日志到达通知：只传实例名，日志内容仍由 RuntimeService 统一渲染。"""
import threading


class LogHub:
    """把日志队列的逐条到达事件广播给 WebSocket 会话。"""

    def __init__(self):
        self.listeners = set()
        self.lock = threading.Lock()

    def publish(self, instance):
        with self.lock:
            listeners = tuple(self.listeners)
        for listener in listeners:
            listener(instance)

    def subscribe(self, listener):
        with self.lock:
            self.listeners.add(listener)

    def unsubscribe(self, listener):
        with self.lock:
            self.listeners.discard(listener)


hub = LogHub()
