"""内存性能分析器。

后台轻量级内存采样工具，通过独立的滚动日志记录内存诊断信息。
使用 tracemalloc 追踪 Python 内存分配，RSS/USS 捕获原生库内存占用。
"""

import atexit
import gc
import logging
import os
import threading
import time
import tracemalloc
from logging.handlers import RotatingFileHandler
from pathlib import Path

try:
    import psutil
except ImportError:
    psutil = None


class MemoryProfiler:
    """轻量级后台内存采样分析器。

    将内存诊断信息写入独立的滚动日志中，避免污染主任务日志。
    tracemalloc 负责追踪 Python 对象分配；RSS/USS 用于捕获 OpenCV、ONNX 等
    原生底层库的内存占用。

    Attributes:
        name (str): 分析器标识名称。
        interval (float): 采样间隔时间（秒）。
        top (int): 记录前 N 个最大内存分配/增长项。
        max_bytes (int): 单个滚动日志文件的最大字节数。
        backup_count (int): 滚动日志文件保留数量。
        process (psutil.Process | None): 当前进程监控对象。
        stop_event (threading.Event): 停止线程事件。
        sample_event (threading.Event): 触发单次采样事件。
        thread (threading.Thread | None): 后台采样线程。
        current_task (str): 当前运行的任务名称。
        current_phase (str): 当前执行阶段。
        previous_snapshot (tracemalloc.Snapshot | None): 上一次采样的快照。
        previous_metrics (dict | None): 上一次采样的指标数据。
        task_start_metrics (dict | None): 任务开始时的指标数据。
        logger (logging.Logger): 专用文件日志记录器。
    """

    def __init__(
        self,
        name,
        interval=10.0,
        top=10,
        max_bytes=10 * 1024 * 1024,
        backup_count=5,
    ):
        """初始化内存分析器。

        Args:
            name (str): 分析器标识名称。
            interval (float, optional): 采样间隔（秒）。默认为 10.0。
            top (int, optional): 展示前 N 个内存分配项。默认为 10。
            max_bytes (int, optional): 日志文件滚动阈值字节数。默认为 10 MiB。
            backup_count (int, optional): 日志备份文件保留个数。默认为 5。
        """
        self.name = name
        self.interval = max(float(interval), 1.0)
        self.top = max(int(top), 1)
        self.max_bytes = max(int(max_bytes), 1024 * 1024)
        self.backup_count = max(int(backup_count), 1)
        self.process = psutil.Process(os.getpid()) if psutil is not None else None
        self.stop_event = threading.Event()
        self.sample_event = threading.Event()
        self.thread = None
        self.current_task = "idle"
        self.current_phase = "init"
        self.previous_snapshot = None
        self.previous_metrics = None
        self.task_start_metrics = None
        self._atexit_registered = False
        self.logger = self._create_logger()

    @classmethod
    def from_env(cls, name):
        """从环境变量读取配置并实例化内存分析器。

        Args:
            name (str): 分析器标识名称。

        Returns:
            MemoryProfiler: 内存分析器实例。
        """
        return cls(
            name=name,
            interval=os.getenv("ALAS_MEMORY_INTERVAL", "10"),
            top=os.getenv("ALAS_MEMORY_TOP", "10"),
            max_bytes=os.getenv("ALAS_MEMORY_LOG_MAX_BYTES", str(10 * 1024 * 1024)),
            backup_count=os.getenv("ALAS_MEMORY_LOG_BACKUP_COUNT", "5"),
        )

    @staticmethod
    def enabled():
        """检查环境变量中是否启用了内存分析。

        Returns:
            bool: 启用返回 True，禁用返回 False。
        """
        return os.getenv("ALAS_MEMORY_PROFILE", "1").strip().lower() not in {
            "0",
            "false",
            "no",
            "off",
        }

    def _create_logger(self):
        """创建独立的滚动文件日志器。

        Returns:
            logging.Logger: 内存采样专用日志器。
        """
        log_dir = Path("./log/memory")
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir.joinpath(f"{self.name}_memory.log")

        logger = logging.getLogger(f"alas.memory.{self.name}.{os.getpid()}")
        logger.setLevel(logging.INFO)
        logger.propagate = False
        logger.handlers.clear()

        handler = RotatingFileHandler(
            log_file,
            maxBytes=self.max_bytes,
            backupCount=self.backup_count,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(asctime)s.%(msecs)03d | %(message)s", "%Y-%m-%d %H:%M:%S"))
        logger.addHandler(handler)
        self.log_file = str(log_file)
        return logger

    def start(self):
        """启动内存分析器后台采样线程并开启 tracemalloc 追踪。"""
        if self.thread and self.thread.is_alive():
            return

        if not tracemalloc.is_tracing():
            tracemalloc.start(25)

        self.logger.info(
            "memory profiler started | pid=%s | interval=%.1fs | top=%s | log=%s",
            os.getpid(),
            self.interval,
            self.top,
            self.log_file,
        )
        if not self._atexit_registered:
            atexit.register(self.stop)
            self._atexit_registered = True
        self.thread = threading.Thread(target=self._run, name="MemoryProfiler", daemon=True)
        self.thread.start()
        self.sample("startup")

    def stop(self):
        """停止后台采样线程并记录终止采样。"""
        self.stop_event.set()
        self.sample_event.set()
        if self.thread:
            self.thread.join(timeout=2)
        self._write_sample("stop")
        if self._atexit_registered:
            try:
                atexit.unregister(self.stop)
            except Exception:
                pass
            self._atexit_registered = False

    def set_task(self, task, phase="running"):
        """设置当前关联任务及执行阶段，并立即触发一次采样。

        Args:
            task (str): 任务名称。
            phase (str, optional): 任务执行阶段（如 running, start, end）。默认为 "running"。
        """
        self.current_task = str(task)
        self.current_phase = str(phase)
        self._write_sample(f"task_{phase}")

    def sample(self, reason="manual"):
        """手动请求触发一次内存采样。

        Args:
            reason (str, optional): 采样原因说明。默认为 "manual"。
        """
        self.current_phase = str(reason)
        self.sample_event.set()

    def _run(self):
        """后台采样循环线程执行体。"""
        while not self.stop_event.is_set():
            self._write_sample(self.current_phase)
            self.sample_event.wait(self.interval)
            self.sample_event.clear()

    def _write_sample(self, reason):
        """采集当前进程与系统内存指标并输出至日志。

        Args:
            reason (str): 采样触发原因。
        """
        try:
            process_memory = self._process_memory()

            gc_counts = gc.get_count()
            system_memory = self._system_memory()
            traced_current, traced_peak = tracemalloc.get_traced_memory()
            metrics = {
                "rss": process_memory["rss"],
                "uss": process_memory["uss"],
                "traced": traced_current,
            }
            if reason == "task_start":
                self.task_start_metrics = metrics.copy()
            previous_delta = self._metrics_delta(metrics, self.previous_metrics)
            task_delta = self._metrics_delta(metrics, self.task_start_metrics)

            self.logger.info(
                (
                    "sample | reason=%s | task=%s | rss=%s | vms=%s | uss=%s | "
                    "traced=%s | traced_peak=%s | system_used=%s/%s %.1f%% | "
                    "cpu=%.1f%% | threads=%s | open_files=%s | gc=%s/%s/%s | "
                    "delta_prev=%s | delta_task=%s"
                ),
                reason,
                self.current_task,
                self._mb(process_memory["rss"]),
                self._mb(process_memory["vms"]),
                self._mb(process_memory["uss"]),
                self._mb(traced_current),
                self._mb(traced_peak),
                self._mb(system_memory["used"]),
                self._mb(system_memory["total"]),
                system_memory["percent"],
                process_memory["cpu_percent"],
                process_memory["thread_count"],
                process_memory["open_files"],
                gc_counts[0],
                gc_counts[1],
                gc_counts[2],
                self._format_delta(previous_delta),
                self._format_delta(task_delta),
            )
            if reason == "task_end":
                self.logger.info(
                    "task summary | task=%s | delta_task=%s",
                    self.current_task,
                    self._format_delta(task_delta),
                )
                self.task_start_metrics = None

            snapshot = tracemalloc.take_snapshot()
            self._write_top_allocations(snapshot)
            self._write_top_diffs(snapshot)
            self.previous_snapshot = snapshot
            self.previous_metrics = metrics
        except Exception as exc:
            self.logger.exception("memory profiler sample failed: %s", exc)

    def _full_memory_info(self):
        """获取当前进程的完整内存信息（包含 USS）。

        Returns:
            Any: psutil 内存信息对象。
        """
        try:
            return self.process.memory_full_info()
        except Exception:
            return self.process.memory_info()

    def _process_memory(self):
        """采集当前进程的内存、CPU、线程及文件句柄数据。

        Returns:
            dict: 包含 rss, vms, uss, cpu_percent, thread_count, open_files 的字典。
        """
        if self.process is None:
            return {
                "rss": 0,
                "vms": 0,
                "uss": 0,
                "cpu_percent": 0,
                "thread_count": threading.active_count(),
                "open_files": "n/a",
            }

        with self.process.oneshot():
            memory = self.process.memory_info()
            full_memory = self._full_memory_info()
            return {
                "rss": memory.rss,
                "vms": memory.vms,
                "uss": getattr(full_memory, "uss", 0),
                "cpu_percent": self.process.cpu_percent(interval=None),
                "thread_count": self.process.num_threads(),
                "open_files": self._safe_len(self.process.open_files),
            }

    @staticmethod
    def _system_memory():
        """采集操作系统级别的总内存使用量与占比。

        Returns:
            dict: 包含 used, total, percent 的字典。
        """
        if psutil is None:
            return {"used": 0, "total": 0, "percent": 0}
        memory = psutil.virtual_memory()
        return {"used": memory.used, "total": memory.total, "percent": memory.percent}

    def _write_top_allocations(self, snapshot):
        """输出前 N 个最大内存分配的文件与行号。

        Args:
            snapshot (tracemalloc.Snapshot): tracemalloc 快照对象。
        """
        stats = snapshot.statistics("lineno")[:self.top]
        self.logger.info("top allocations | count=%s", len(stats))
        for index, stat in enumerate(stats, 1):
            frame = stat.traceback[0]
            self.logger.info(
                "top #%02d | size=%s | count=%s | %s:%s",
                index,
                self._mb(stat.size),
                stat.count,
                frame.filename,
                frame.lineno,
            )

    def _write_top_diffs(self, snapshot):
        """对比上一次快照并输出内存增长量前 N 项。

        Args:
            snapshot (tracemalloc.Snapshot): 当前 tracemalloc 快照对象。
        """
        if self.previous_snapshot is None:
            return
        stats = snapshot.compare_to(self.previous_snapshot, "lineno")[:self.top]
        self.logger.info("top growth since previous sample | count=%s", len(stats))
        for index, stat in enumerate(stats, 1):
            if stat.size_diff <= 0:
                continue
            frame = stat.traceback[0]
            self.logger.info(
                "growth #%02d | diff=%s | count_diff=%+d | now=%s | %s:%s",
                index,
                self._mb(stat.size_diff),
                stat.count_diff,
                self._mb(stat.size),
                frame.filename,
                frame.lineno,
            )

    @staticmethod
    def _metrics_delta(current, previous):
        """计算两次采样间的内存指标变化量。

        Args:
            current (dict): 当前采样指标。
            previous (dict | None): 上次采样指标。

        Returns:
            dict | None: 各维度增量字典，无前置采样时返回 None。
        """
        if not previous:
            return None
        rss_delta = current["rss"] - previous["rss"]
        uss_delta = current["uss"] - previous["uss"]
        traced_delta = current["traced"] - previous["traced"]
        return {
            "rss": rss_delta,
            "uss": uss_delta,
            "traced": traced_delta,
            "native_est_rss": rss_delta - traced_delta,
            "native_est_uss": uss_delta - traced_delta,
        }

    def _format_delta(self, delta):
        """将增量指标字典格式化为可读字符串。

        Args:
            delta (dict | None): 增量字典。

        Returns:
            str: 格式化后的字符串。
        """
        if delta is None:
            return "n/a"
        return (
            f"rss={self._signed_mb(delta['rss'])}, "
            f"uss={self._signed_mb(delta['uss'])}, "
            f"traced={self._signed_mb(delta['traced'])}, "
            f"native_est_rss={self._signed_mb(delta['native_est_rss'])}, "
            f"native_est_uss={self._signed_mb(delta['native_est_uss'])}"
        )

    @staticmethod
    def _mb(value):
        """将字节数转换为 MiB 字符串。

        Args:
            value (int | float): 字节数。

        Returns:
            str: 格式化后的 MiB 字符串。
        """
        return f"{value / 1024 / 1024:.2f} MiB"

    @staticmethod
    def _signed_mb(value):
        """将有符号字节数转换为带正负号的 MiB 字符串。

        Args:
            value (int | float): 字节数。

        Returns:
            str: 格式化后带符号的 MiB 字符串。
        """
        return f"{value / 1024 / 1024:+.2f} MiB"

    @staticmethod
    def _safe_len(func):
        """安全计算集合或列表长度，发生异常时返回 'n/a'。

        Args:
            func (Callable): 返回可求长度对象的无参函数。

        Returns:
            int | str: 长度数值或 'n/a'。
        """
        try:
            return len(func())
        except Exception:
            return "n/a"


def start_memory_profiler(name):
    """根据环境配置启动内存分析器。

    Args:
        name (str): 实例或模块名称。

    Returns:
        MemoryProfiler | None: 已启动的分析器实例，未启用时返回 None。
    """
    if not MemoryProfiler.enabled():
        return None

    profiler = MemoryProfiler.from_env(name)
    profiler.start()
    return profiler
