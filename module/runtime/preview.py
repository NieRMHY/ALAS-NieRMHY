"""被动截图通道：游戏线程只投递图像，后台编码，父进程分发最新帧。"""
import base64
import io
import queue
import threading
from datetime import datetime
from typing import Callable


class PreviewHub:
    """运行预览截图广播中心。

    每实例只保留最新一帧，订阅者通过通知取最新值，不累积视频队列。

    Attributes:
        frames: 各实例最新帧数据缓存映射。
        listeners: 订阅监听器回调集合。
        lock: 互斥锁。
    """

    def __init__(self):
        """初始化预览截图广播中心。"""
        self.frames = {}
        self.listeners = set()
        self.lock = threading.Lock()

    def publish(self, instance: str, frame: dict):
        """发布并更新指定实例的最新一帧截图。

        Args:
            instance: 实例名称。
            frame: 包含时间戳与 Base64 图像数据的帧字典。
        """
        with self.lock:
            self.frames[instance] = frame
            listeners = tuple(self.listeners)
        for listener in listeners:
            listener(instance)

    def get(self, instance: str) -> dict:
        """获取指定实例当前缓存的最新一帧截图。

        Args:
            instance: 实例名称。

        Returns:
            dict: 帧字典；若无缓存则返回空图占位字典。
        """
        with self.lock:
            return self.frames.get(instance, {'instance': instance, 'image': None, 'capturedAt': None})

    def discard(self, instance: str):
        """清除指定实例的预览帧缓存。

        Args:
            instance: 实例名称。
        """
        with self.lock:
            self.frames.pop(instance, None)

    def subscribe(self, listener: Callable[[str], None]):
        """注册新帧到达监听器。

        Args:
            listener: 接收实例名的回调函数。
        """
        with self.lock:
            self.listeners.add(listener)

    def unsubscribe(self, listener: Callable[[str], None]):
        """注销新帧到达监听器。

        Args:
            listener: 待注销的回调函数。
        """
        with self.lock:
            self.listeners.discard(listener)


hub = PreviewHub()
_images = None


def initialize(instance: str, output: queue.Queue, task_sink: queue.Queue, run_id: str = None):
    """在运行子进程中安装输出通道，独立脚本无需初始化。

    启动后台 JPEG 编码工作线程，持续将主线程截图转换为 Web 友好的 Base64 数据。

    Args:
        instance: 实例名称。
        output: 跨进程帧传输输出队列。
        task_sink: 任务事件状态输出队列。
        run_id: 可选的运行会话 ID。
    """
    from module.runtime.worker_events import initialize as initialize_events

    global _images
    initialize_events(task_sink, run_id)
    _images = queue.Queue(maxsize=1)

    def encode():
        from PIL import Image
        while True:
            image, timestamp = _images.get()
            try:
                buffer = io.BytesIO()
                # 各后端在统一截图入口返回 RGB 图像。
                Image.fromarray(image).save(buffer, format='JPEG', quality=85)
                frame = {'instance': instance, 'capturedAt': timestamp, 'runId': run_id,
                         'image': 'data:image/jpeg;base64,' + base64.b64encode(buffer.getvalue()).decode()}
                try:
                    output.put_nowait(frame)
                except queue.Full:
                    try:
                        output.get_nowait()
                    except queue.Empty:
                        pass
                    output.put_nowait(frame)
            except (OSError, EOFError, BrokenPipeError):
                return
            except (ValueError, queue.Full):
                # 预览丢帧不能中断实际任务或造成无界积压。
                continue

    threading.Thread(target=encode, daemon=True, name='preview-encoder').start()


def publish(image):
    """接收统一截图入口的结果，复制后交给编码线程。

    避免后续游戏逻辑在图像上绘制调试标注产生画面污染。

    Args:
        image: NumPy RGB 图像数组。
    """
    if _images is None:
        return
    frame = (image.copy(), datetime.now().isoformat())
    try:
        _images.put_nowait(frame)
    except queue.Full:
        try:
            _images.get_nowait()
        except queue.Empty:
            pass
        try:
            _images.put_nowait(frame)
        except queue.Full:
            pass


def set_task(command: str):
    """通过可靠的进程队列传递当前执行的任务边界。

    避免上层从非结构化的日志文字反向推测运行状态。

    Args:
        command: 当前执行的任务命令名称。
    """
    from module.runtime.worker_events import set_task as publish_task

    publish_task(command)
