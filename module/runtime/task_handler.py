"""不依赖界面的后台任务调度器。"""
import datetime
import operator
import threading
import time
from collections.abc import Callable, Generator
from typing import Optional

from module.logger import logger


def get_generator(func: Callable):
    """将普通回调包装为先预热、再按周期执行的生成器。

    Args:
        func: 目标可调用函数对象。

    Returns:
        Generator: 包装后的周期性生成器。
    """
    def generate():
        yield
        while True:
            yield func()

    generator = generate()
    generator.__name__ = getattr(func, '__name__', 'callback')
    return generator


class Task:
    """后台可调度任务包装类。

    Attributes:
        g: 任务实际迭代执行的生成器对象。
        delay: 任务单次执行完成后的重复间隔（秒）。
        next_run: 下次预期执行的时间戳。
        name: 任务名称标识。
        wake_requested: 是否收到了提前唤醒请求标记。
    """

    def __init__(
        self,
        g: Generator,
        delay: float,
        next_run: Optional[float] = None,
        name: Optional[str] = None,
    ) -> None:
        """初始化任务实例。

        Args:
            g: 目标生成器。
            delay: 执行周期间隔（秒）。
            next_run: 初始预期运行时间戳，为 None 则立即就绪。
            name: 任务名，为 None 则取生成器名。
        """
        self.g = g
        g.send(None)
        self.delay = delay
        self.next_run = next_run if next_run is not None else time.time()
        self.name = name if name is not None else self.g.__name__
        self.wake_requested = False

    def __str__(self) -> str:
        """返回任务的简短字符串表示。"""
        return f"<{self.name} (delay={self.delay})>"

    def __next__(self) -> None:
        """执行生成器的下一个迭代。"""
        return next(self.g)

    def send(self, obj) -> None:
        """向生成器发送值以驱动单步执行。

        Args:
            obj: 发送给生成器的对象。
        """
        return self.g.send(obj)

    __repr__ = __str__


class TaskHandler:
    """后台定时与周期性任务调度处理器。

    Attributes:
        tasks: 后台注册的任务列表。
        pending_remove_tasks: 标记为待移除的任务列表。
    """

    def __init__(self) -> None:
        """初始化任务处理器实例。"""
        # 后台运行的任务列表
        self.tasks: list[Task] = []
        # 待移除的任务列表
        self.pending_remove_tasks: list[Task] = []
        # 当前正在运行的任务
        self._task = None
        # 任务运行线程
        self._thread: Optional[threading.Thread] = None
        self._alive = False
        self._lock = threading.RLock()
        # 新增、移除或停止任务时主动唤醒调度线程，避免固定间隔空轮询。
        self._condition = threading.Condition(self._lock)

    def add(self, func, delay: float, pending_delete: bool = False) -> None:
        """添加后台运行的任务。

        `self.add_task()` 的便捷替代方式。

        Args:
            func: Callable 或 Generator 对象。
            delay: 任务执行间隔（秒）。
            pending_delete: 是否标记为执行后待删除。

        Raises:
            TypeError: 目标对象既非 Callable 也非 Generator。
        """
        if isinstance(func, Callable):
            g = get_generator(func)
        elif isinstance(func, Generator):
            g = func
        else:
            raise TypeError('后台任务必须为可调用对象或生成器')
        self.add_task(Task(g, delay), pending_delete=pending_delete)

    def add_task(self, task: Task, pending_delete: bool = False) -> None:
        """向调度队列中注册一个任务对象。

        Args:
            task: 待添加的任务实例。
            pending_delete: 是否标记为待批量删除。
        """
        with self._condition:
            if task in self.tasks:
                logger.warning(f"[WebUI-工具] 任务 {task} 已在任务列表中")
                return
            logger.info(f"添加任务 {task}")
            self.tasks.append(task)
            if pending_delete:
                self.pending_remove_tasks.append(task)
            self._condition.notify()

    def _remove_task(self, task: Task) -> None:
        """从调度列表中真正移除指定任务。

        Args:
            task: 待移除的任务实例。
        """
        if task in self.tasks:
            self.tasks.remove(task)
            logger.info(f"[WebUI-工具] 任务 {task} 已移除")
        else:
            logger.warning(
                f"[WebUI-工具] 移除任务 {task} 失败。当前任务列表: {self.tasks}"
            )

    def remove_task(self, task: Task, nowait: bool = False) -> None:
        """从任务列表中移除指定任务。

        Args:
            task: 要移除的任务。
            nowait: 为 True 时立即移除，否则在调用 `self.remove_pending_task` 时统一移除。
        """
        with self._condition:
            if nowait:
                self._remove_task(task)
            elif task not in self.pending_remove_tasks:
                self.pending_remove_tasks.append(task)
            self._condition.notify()

    def remove_pending_task(self) -> None:
        """移除所有已标记为待移除的任务。"""
        with self._condition:
            for task in self.pending_remove_tasks:
                self._remove_task(task)
            self.pending_remove_tasks = []
            self._condition.notify()

    def remove_current_task(self) -> None:
        """立即移除当前正在运行的任务。"""
        self.remove_task(self._task, nowait=True)

    def get_task(self, name: str) -> Optional[Task]:
        """根据名称检索已注册的任务实例。

        Args:
            name: 任务名称。

        Returns:
            Optional[Task]: 匹配的任务对象；若未找到则返回 None。
        """
        with self._lock:
            for task in self.tasks:
                if task.name == name:
                    return task
            return None

    def wake_task(self, name: str) -> bool:
        """让指定任务尽快执行，并唤醒正在等待的调度线程。

        Args:
            name: 目标任务名称。

        Returns:
            bool: 成功找到并唤醒返回 True，否则返回 False。
        """
        with self._condition:
            for task in self.tasks:
                if task.name == name:
                    if task is self._task:
                        task.wake_requested = True
                    else:
                        task.next_run = time.time()
                    self._condition.notify()
                    return True
            return False

    def loop(self) -> None:
        """启动后台任务主调度循环。

        此函数必须在独立线程中运行。
        """
        while True:
            with self._condition:
                while self._alive:
                    if not self.tasks:
                        self._condition.wait()
                        continue
                    self.tasks.sort(key=operator.attrgetter("next_run"))
                    task = self.tasks[0]
                    wait_seconds = task.next_run - time.time()
                    if wait_seconds > 0:
                        self._condition.wait(timeout=wait_seconds)
                        continue
                    self._task = task
                    break
                else:
                    break

            if not self._alive:
                break

            try:
                task.send(self)
            except Exception as e:
                logger.exception(e)
                self.remove_task(task, nowait=True)
            finally:
                with self._condition:
                    # 每次执行后从当前时间重新计时。系统休眠或事件循环长时间
                    # 阻塞后不会补跑大量已经过期的刷新任务。
                    if task in self.tasks:
                        if task.wake_requested:
                            task.wake_requested = False
                            task.next_run = time.time()
                        else:
                            task.next_run = time.time() + max(0, task.delay)
                    self._task = None
        logger.info("任务处理循环结束")

    def _get_thread(self) -> threading.Thread:
        """构建调度循环守护线程。

        Returns:
            threading.Thread: 初始化好的后台守护线程。
        """
        thread = threading.Thread(target=self.loop, daemon=True)
        return thread

    def start(self) -> None:
        """启动后台任务调度线程。"""
        with self._condition:
            logger.info("启动任务处理")
            if self._thread is not None and self._thread.is_alive():
                logger.warning("[WebUI-工具] 任务处理器已在运行！")
                return
            self._alive = True
            self._thread = self._get_thread()
            try:
                self._thread.start()
            except Exception:
                self._alive = False
                self._thread = None
                raise

    def stop(self) -> bool:
        """停止任务线程，并返回是否已能安全释放共享状态。

        Returns:
            bool: 线程成功停止或无需停止返回 True，超时未退出返回 False。
        """
        self.remove_pending_task()
        with self._condition:
            self._alive = False
            self._condition.notify_all()
        if self._thread is None:
            logger.info("[WebUI] 任务处理器未启动，跳过停止")
            return True
        if threading.current_thread() is not self._thread:
            self._thread.join(timeout=2)
            if not self._thread.is_alive():
                logger.info("完成任务处理")
                return True
            else:
                logger.warning("[WebUI] 任务处理器未在 2 秒内停止")
                return False
        else:
            logger.info("[WebUI] 任务处理器在其自身线程内调用了停止，跳过 join")
            return True


def get_next_time(t: datetime.time) -> float:
    """计算距离今天或明天指定时刻剩余的秒数。

    Args:
        t: 目标时间对象。

    Returns:
        float: 距离目标时刻的秒数。
    """
    now = datetime.datetime.today().time()
    second = (
        (t.hour - now.hour) * 3600
        + (t.minute - now.minute) * 60
        + (t.second - now.second)
    )
    if second < 0:
        second += 86400
    return float(second)
