"""后台任务调度回归测试。"""
import threading
import time
import unittest
from module.runtime.task_handler import Task, TaskHandler


def iter_task(func):
    """创建符合后台调度协议的生成器。"""
    yield
    while True:
        func()
        yield

class TestTaskHandlerScheduling(unittest.TestCase):
    def test_add_accepts_callback_and_generator_without_running_during_registration(self):
        for as_generator in (False, True):
            with self.subTest(as_generator=as_generator):
                called = threading.Event()
                handler = TaskHandler()
                handler.add(iter_task(called.set) if as_generator else called.set, delay=60)
                self.assertFalse(called.is_set())
                handler.start()
                try:
                    self.assertTrue(called.wait(timeout=1))
                finally:
                    self.assertTrue(handler.stop())

    def test_overdue_task_does_not_run_in_catch_up_burst(self):
        calls = 0
        first_call = threading.Event()

        def run_once():
            nonlocal calls
            calls += 1
            first_call.set()

        handler = TaskHandler()
        task = Task(
            iter_task(run_once),
            delay=0.2,
            next_run=time.time() - 60,
        )
        handler.add_task(task)
        handler.start()
        try:
            self.assertTrue(first_call.wait(timeout=1))
            time.sleep(0.05)
            self.assertEqual(1, calls)
        finally:
            handler.stop()

    def test_wake_task_interrupts_scheduler_wait(self):
        called = threading.Event()
        handler = TaskHandler()
        task = Task(
            iter_task(called.set),
            delay=60,
            next_run=time.time() + 60,
            name="deferred",
        )
        handler.add_task(task)
        handler.start()
        try:
            self.assertTrue(handler.wake_task("deferred"))
            self.assertTrue(called.wait(timeout=1))
        finally:
            handler.stop()

    def test_wake_during_execution_is_not_lost(self):
        first_call_started = threading.Event()
        release_first_call = threading.Event()
        second_call = threading.Event()
        calls = 0

        def run_task():
            nonlocal calls
            calls += 1
            if calls == 1:
                first_call_started.set()
                release_first_call.wait(timeout=1)
            else:
                second_call.set()

        handler = TaskHandler()
        handler.add_task(Task(iter_task(run_task), delay=60, name="running"))
        handler.start()
        try:
            self.assertTrue(first_call_started.wait(timeout=1))
            self.assertTrue(handler.wake_task("running"))
            release_first_call.set()
            self.assertTrue(second_call.wait(timeout=1))
        finally:
            handler.stop()
