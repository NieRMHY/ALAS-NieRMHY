import argparse
# 此文件专门用于管理 Alas 运行时各实例进程的生存周期及其子进程。
# 负责多账号多开时的进程池维护、状态（运行中、停止、异常）追踪及进程间通信的安全处理逻辑。
import os
import queue
import re
import threading
from multiprocessing import Process
from typing import Dict, List, Union

import inflection
from rich.console import Console, ConsoleRenderable

# Since this file does not run under the same process or subprocess of app.py
# the following code needs to be repeated
# Import fake module before import pywebio to avoid importing unnecessary module PIL
from module.webui.fake_pil_module import *

import_fake_pil_module()

from module.logger import logger, set_file_logger, set_func_logger
from module.submodule.submodule import load_mod
from module.submodule.utils import get_available_func, get_available_mod, get_available_mod_func, get_config_mod, \
    get_func_mod, list_mod_instance
from module.webui.lang import t
from module.webui.setting import State


class ProcessManager:
    _processes: Dict[str, "ProcessManager"] = {}

    def __init__(self, config_name: str = "alas") -> None:
        self.config_name = config_name
        self._renderable_queue: queue.Queue[ConsoleRenderable] = State.manager.Queue()
        self._screenshot_data_queue = None
        self.renderables: List[ConsoleRenderable] = []
        self.renderables_max_length = 400
        self.renderables_reduce_length = 80
        self.renderables_total = 0
        self.timeline_steps: List[dict] = []
        self.timeline_steps_max_length = 800
        self.timeline_steps_reduce_length = 200
        self.timeline_detail_lines_max_length = 120
        self.timeline_version = 0
        self._process: Process = None
        self._process_locks: Dict[str, threading.Lock] = {}
        self.thd_log_queue_handler: threading.Thread = None

    def start(self, func, ev: threading.Event = None) -> None:
        if not self.alive:
            if func is None:
                func = get_config_mod(self.config_name)
            try:
                import multiprocessing
                if getattr(self, "_screenshot_data_queue", None) is not None:
                    try:
                        self._screenshot_data_queue.close()
                    except Exception:
                        pass
                    try:
                        self._screenshot_data_queue.join_thread()
                    except Exception:
                        pass
                self._screenshot_data_queue = multiprocessing.Queue(maxsize=8)
                try:
                    enabled = 1 if getattr(State, "display_screenshots", False) else 0
                except Exception:
                    enabled = 1
                try:
                    self._screenshot_enabled_flag = multiprocessing.Value('b', enabled)
                except Exception:
                    self._screenshot_enabled_flag = None
            except Exception:
                logger.exception("雪风大人提醒无法创建多进程截图队列")
            args = (
                self.config_name,
                func,
                self._renderable_queue,
                self._screenshot_data_queue,
                ev,
            )
            if getattr(self, '_screenshot_enabled_flag', None) is not None:
                args = args + (self._screenshot_enabled_flag,)
            self._process = Process(
                target=ProcessManager.run_process,
                args=args,
            )
            self._process.start()
            self.start_log_queue_handler()

    def start_log_queue_handler(self):
        if (
            self.thd_log_queue_handler is not None
            and self.thd_log_queue_handler.is_alive()
        ):
            return
        self.thd_log_queue_handler = threading.Thread(
            target=self._thread_log_queue_handler
        )
        self.thd_log_queue_handler.start()

    def stop(self) -> None:
        try:
            lock = self._process_locks[self.config_name]
        except KeyError:
            lock = threading.Lock()
            self._process_locks[self.config_name] = lock

        with lock:
            if self.alive:
                self._process.kill()
                stop_message = f"[{self.config_name}] exited. Reason: Manual stop\n"
                self.renderables.append(stop_message)
                self.renderables_total += 1
                self._ingest_timeline_renderable(stop_message)
                self._sync_timeline_state()
            if self.thd_log_queue_handler is not None:
                self.thd_log_queue_handler.join(timeout=1)
                if self.thd_log_queue_handler.is_alive():
                    logger.warning(
                        "Log queue handler thread does not stop within 1 seconds"
                    )
        logger.info(f"[{self.config_name}] exited")

    def _thread_log_queue_handler(self) -> None:
        while self.alive:
            try:
                log = self._renderable_queue.get(timeout=1)
            except queue.Empty:
                continue
            self.renderables.append(log)
            self.renderables_total += 1
            self._ingest_timeline_renderable(log)
            if len(self.renderables) > self.renderables_max_length:
                self.renderables = self.renderables[self.renderables_reduce_length :]
        self._sync_timeline_state()
        logger.info("End of log queue handler loop")

    @property
    def alive(self) -> bool:
        if self._process is not None:
            return self._process.is_alive()
        else:
            return False

    @property
    def state(self) -> int:
        if self.alive:
            return 1
        reason = self._infer_exit_reason()
        if reason in ("manual_stop", "finish"):
            return 2
        elif reason == "update":
            return 4
        elif reason == "crash":
            return 3
        elif len(self.renderables) == 0:
            return 2
        else:
            return 3

    @staticmethod
    def _renderable_to_text(renderable: ConsoleRenderable) -> str:
        if isinstance(renderable, str):
            return renderable.strip()
        console = Console(no_color=True)
        with console.capture() as capture:
            console.print(renderable)
        return capture.get().strip()

    def _infer_exit_reason(self) -> Union[str, None]:
        for renderable in reversed(self.renderables[-20:]):
            text = self._renderable_to_text(renderable)
            if not text:
                continue
            lower = text.lower()
            if "reason: manual stop" in lower:
                return "manual_stop"
            if "reason: finish" in lower:
                return "finish"
            if "reason: update" in lower or "原因: 更新" in text:
                return "update"

        if self._process is None:
            return None
        if self._process.exitcode == 0:
            return "finish"
        if self._process.exitcode is not None:
            return "crash"
        return None

    @staticmethod
    def _normalize_spaces(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _is_error_text(text: str) -> bool:
        return any(
            token in text
            for token in (
                " ERROR ",
                " CRITICAL ",
                "Traceback",
                "Exception",
                "RuntimeError",
                "ValueError",
                "AssertionError",
                "更新失败",
                "执行失败",
                "崩溃",
                "报错",
            )
        )

    @staticmethod
    def _map_task_name(task_name: str) -> str:
        translated = t(f"Task.{task_name}.name")
        if translated == f"Task.{task_name}.name":
            return task_name
        return translated

    def _extract_task_title(self, text: str) -> tuple[Union[str, None], bool]:
        scheduler_start = re.search(r"调度器:\s*开始任务\s*`?([A-Za-z0-9_]+)`?", text)
        if scheduler_start:
            return self._map_task_name(scheduler_start.group(1)), True

        task_bind = re.search(r"\[Task\]\s*([A-Za-z0-9_]+)", text)
        if task_bind:
            return self._map_task_name(task_bind.group(1)), True

        return None, False

    @staticmethod
    def _create_timeline_step(title: str, status: str = "active") -> dict:
        return {
            "title": title,
            "status": status,
            "line_count": 0,
            "last_message": "",
            "summary_message": "",
            "detail_lines": [],
            "has_error": False,
        }

    def _trim_timeline_steps(self) -> None:
        if len(self.timeline_steps) > self.timeline_steps_max_length:
            del self.timeline_steps[:self.timeline_steps_reduce_length]

    def _finalize_timeline_step(self, step: dict, terminal_status: Union[str, None] = None) -> None:
        step["status"] = terminal_status or ("warning" if step.get("has_error") else "completed")

    def _ensure_timeline_step(self, title: Union[str, None] = None) -> dict:
        changed = False
        if not self.timeline_steps:
            self.timeline_steps.append(self._create_timeline_step(title or "启动中", status="active"))
            changed = True
        elif title and self.timeline_steps[-1]["title"] != title:
            if self.timeline_steps[-1]["status"] == "active":
                self._finalize_timeline_step(self.timeline_steps[-1])
            self.timeline_steps.append(self._create_timeline_step(title, status="active"))
            changed = True
        elif title and self.timeline_steps[-1]["title"] == title:
            if self.timeline_steps[-1]["status"] != "failed":
                self.timeline_steps[-1]["status"] = "active"

        self._trim_timeline_steps()
        if changed:
            self.timeline_version += 1
        return self.timeline_steps[-1]

    def _pick_summary_message(self, detail_lines: List[str], fallback: str = "") -> str:
        for line in reversed(detail_lines):
            if self._is_error_text(line):
                return line
        return detail_lines[-1] if detail_lines else fallback

    def _append_detail_lines(self, step: dict, raw_lines: List[str]) -> None:
        lines = step["detail_lines"]
        lines.extend(raw_lines)
        if len(lines) > self.timeline_detail_lines_max_length:
            del lines[: len(lines) - self.timeline_detail_lines_max_length]

    def _ingest_timeline_renderable(self, renderable: ConsoleRenderable) -> None:
        text_content = self._renderable_to_text(renderable)
        task_title, is_strong_boundary = self._extract_task_title(text_content)

        if not self.timeline_steps:
            step = self._ensure_timeline_step(task_title)
        elif is_strong_boundary and task_title:
            step = self._ensure_timeline_step(task_title)
        else:
            step = self.timeline_steps[-1]

        raw_lines = [line.rstrip() for line in text_content.splitlines()]
        raw_lines = [line for line in raw_lines if line.strip()]
        detail_lines = [self._normalize_spaces(line) for line in raw_lines]
        if raw_lines:
            step["line_count"] += len(raw_lines)
            step["last_message"] = detail_lines[-1]
            step["summary_message"] = self._pick_summary_message(
                detail_lines,
                fallback=step["summary_message"],
            )
            self._append_detail_lines(step, raw_lines)
            self.timeline_version += 1

        if self._is_error_text(text_content):
            step["has_error"] = True
            if step["status"] == "active":
                step["status"] = "warning"
            self.timeline_version += 1

    def _sync_timeline_state(self) -> None:
        if not self.timeline_steps:
            if self.alive:
                self.timeline_steps.append(self._create_timeline_step("运行中", status="active"))
                self.timeline_version += 1
            elif self.state == 3:
                self.timeline_steps.append(self._create_timeline_step("运行失败", status="failed"))
                self.timeline_version += 1
            return

        last_step = self.timeline_steps[-1]
        new_status = last_step["status"]
        if self.alive:
            if new_status not in ("failed", "warning"):
                new_status = "active"
        elif self.state == 3:
            new_status = "failed"
            last_step["has_error"] = True
        else:
            new_status = "warning" if last_step.get("has_error") else "completed"

        if last_step["status"] != new_status:
            last_step["status"] = new_status
            self.timeline_version += 1

    @property
    def get_latest_screenshot(self):
        """
        获取最新的截图数据（Base64编码）。
        """
        if self._screenshot_data_queue is None:
            return None

        latest_screenshot = None
        while not self._screenshot_data_queue.empty():
            try:
                latest_screenshot = self._screenshot_data_queue.get_nowait()
                State.last_screenshot_base64 = latest_screenshot
            except queue.Empty:
                break  # 队列为空
            except Exception as e:
                logger.error(f"从截图队列获取数据失败: {e}")
                break
        return latest_screenshot

    def set_screenshot_enabled(self, enabled: bool):
        """Set shared screenshot enabled flag for the running process (if supported)."""
        try:
            if getattr(self, '_screenshot_enabled_flag', None) is not None:
                self._screenshot_enabled_flag.value = 1 if enabled else 0
        except Exception:
            logger.debug('Unable to set screenshot_enabled_flag for %s', self.config_name)

    @classmethod
    def get_manager(cls, config_name: str) -> "ProcessManager":
        """
        Create a new alas if not exists.
        """
        if config_name not in cls._processes:
            cls._processes[config_name] = ProcessManager(config_name)
        return cls._processes[config_name]

    @staticmethod
    def run_process(
        config_name, func: str, q: queue.Queue, screenshot_q: queue.Queue, e: threading.Event = None, screenshot_enabled=None
    ) -> None:
        import sys
        if sys.platform != "win32":
            import resource
            try:
                _soft, _hard = resource.getrlimit(resource.RLIMIT_NOFILE)
                _target = 65536 if _hard == resource.RLIM_INFINITY else min(65536, _hard)
                if _soft < _target:
                    resource.setrlimit(resource.RLIMIT_NOFILE, (_target, _hard))
            except Exception:
                pass
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "--electron", action="store_true", help="Runs by electron client."
        )
        args, _ = parser.parse_known_args()
        State.electron = args.electron

        # Setup logger
        set_file_logger(name=config_name)
        if State.electron:
            # https://github.com/LmeSzinc/AzurLaneAutoScript/issues/2051
            logger.info("Electron detected, remove log output to stdout")
            from module.logger import console_hdlr
            logger.removeHandler(console_hdlr)
        set_func_logger(func=q.put)

        from module.config.config import AzurLaneConfig

        # Remove fake PIL module, because subprocess will use it
        remove_fake_pil_module()

        # Set environment variable so eager modules (like al_ocr.py) can read the configuration early
        os.environ['ALAS_CONFIG_NAME'] = config_name

        AzurLaneConfig.stop_event = e
        try:
            # Run alas
            if func == "alas":
                from alas import AzurLaneAutoScript

                if e is not None:
                    AzurLaneAutoScript.stop_event = e
                if screenshot_enabled is not None:
                    AzurLaneAutoScript(config_name=config_name, screenshot_queue=screenshot_q, screenshot_enabled=screenshot_enabled).loop()
                else:
                    AzurLaneAutoScript(config_name=config_name, screenshot_queue=screenshot_q).loop()
            elif func in get_available_func():
                from alas import AzurLaneAutoScript

                if screenshot_enabled is not None:
                    AzurLaneAutoScript(config_name=config_name, screenshot_enabled=screenshot_enabled).run(inflection.underscore(func), skip_first_screenshot=True)
                else:
                    AzurLaneAutoScript(config_name=config_name).run(inflection.underscore(func), skip_first_screenshot=True)
            elif func in get_available_mod():
                mod = load_mod(func)

                if e is not None:
                    mod.set_stop_event(e)
                mod.loop(config_name)
            elif func in get_available_mod_func():
                getattr(load_mod(get_func_mod(func)), inflection.underscore(func))(config_name)
            else:
                logger.critical(f"未找到对应的功能模块: {func}")
            logger.info(f"[{config_name}] exited. Reason: Finish\n")
        except Exception as e:
            logger.exception(e)

    @classmethod
    def running_instances(cls) -> List["ProcessManager"]:
        l = []
        for process in cls._processes.values():
            if process.alive:
                l.append(process)
        return l

    @staticmethod
    def restart_processes(
        instances: List[Union["ProcessManager", str]] = None, ev: threading.Event = None
    ):
        """
        After update and reload, or failed to perform an update,
        restart all alas that running before update
        """
        logger.hr("Restart alas")

        # Load MOD_CONFIG_DICT
        list_mod_instance()

        if instances is None:
            instances = []

        _instances = set()

        for instance in instances:
            if isinstance(instance, str):
                _instances.add(ProcessManager.get_manager(instance))
            elif isinstance(instance, ProcessManager):
                _instances.add(instance)

        try:
            with open("./config/reloadalas", mode="r") as f:
                for line in f.readlines():
                    line = line.strip()
                    _instances.add(ProcessManager.get_manager(line))
        except FileNotFoundError:
            pass

        for process in _instances:
            logger.info(f"Starting [{process.config_name}]")
            process.start(func=get_config_mod(process.config_name), ev=ev)

        try:
            os.remove("./config/reloadalas")
        except:
            pass
        logger.info("Start alas complete")
